"""
Sales Models - Quotations and Invoices
All invoice postings create journal entries in accounting as single source of truth.

VAT LOGIC (Tax Code Driven - SAP/Oracle Standard):
- VAT is ALWAYS derived from a TaxCode (no hard-coded percentages)
- No Tax Code = No VAT (Out of Scope)
- Tax Code classification preserved for VAT reporting: Standard, Zero Rated, Exempt, Out of Scope
"""
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.core.models import BaseModel
from apps.core.utils import generate_number
from apps.crm.models import Customer


class Quotation(BaseModel):
    """
    Sales Quotation model.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    
    quotation_number = models.CharField(max_length=50, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer, 
        on_delete=models.PROTECT, 
        related_name='quotations'
    )
    date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    terms_and_conditions = models.TextField(blank=True)
    
    # Calculated fields
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.quotation_number} - {self.customer.name}"
    
    def save(self, *args, **kwargs):
        if not self.quotation_number:
            self.quotation_number = generate_number('QUOTATION', Quotation, 'quotation_number')
        super().save(*args, **kwargs)
    
    def calculate_totals(self):
        """Calculate subtotal, VAT, and total from items."""
        items = self.items.all()
        self.subtotal = sum(item.total for item in items)
        self.vat_amount = sum(item.vat_amount for item in items)
        self.total_amount = self.subtotal + self.vat_amount
        self.save(update_fields=['subtotal', 'vat_amount', 'total_amount'])


class QuotationItem(models.Model):
    """
    Line items for quotations.
    Supports both VAT-exclusive and VAT-inclusive pricing.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - vat_rate is computed from tax_code.rate (read-only, for display)
    - No tax_code = Out of Scope (0% VAT)
    """
    quotation = models.ForeignKey(
        Quotation, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Tax Code - source of truth for VAT (SAP/Oracle Standard)
    tax_code = models.ForeignKey(
        'finance.TaxCode',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='quotation_items',
        help_text='Tax Code determines VAT rate. No selection = Out of Scope (0%)'
    )
    
    # Computed VAT rate from tax_code (read-only, for display/reporting)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    is_vat_inclusive = models.BooleanField(default=False, help_text='If true, unit_price includes VAT')
    
    # Calculated
    total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.description} - {self.quantity}"
    
    def save(self, *args, **kwargs):
        # Derive VAT rate from Tax Code (No Tax Code = 0%)
        if self.tax_code:
            self.vat_rate = self.tax_code.rate
        else:
            self.vat_rate = Decimal('0.00')
        
        gross = self.quantity * self.unit_price
        
        if self.is_vat_inclusive and self.vat_rate > 0:
            # VAT-inclusive: Back-calculate net amount and VAT
            divisor = 1 + (self.vat_rate / 100)
            self.total = (gross / divisor).quantize(Decimal('0.01'))
            self.vat_amount = (gross - self.total).quantize(Decimal('0.01'))
        else:
            # VAT-exclusive: Standard calculation
            self.total = gross
            self.vat_amount = (self.total * (self.vat_rate / 100)).quantize(Decimal('0.01'))
        
        super().save(*args, **kwargs)


class Invoice(BaseModel):
    """
    Sales Invoice model.
    Posts to Accounting: Debit AR, Credit Sales, Credit VAT Payable
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),  # Posted to accounting
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    quotation = models.ForeignKey(
        Quotation, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='invoices'
    )
    customer = models.ForeignKey(
        Customer, 
        on_delete=models.PROTECT, 
        related_name='invoices'
    )
    invoice_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    
    # Amounts
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Link to accounting journal entry (single source of truth)
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_invoices'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.invoice_number} - {self.customer.name}"
    
    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = generate_number('INVOICE', Invoice, 'invoice_number')
        super().save(*args, **kwargs)
    
    @property
    def balance(self):
        """Calculate outstanding balance."""
        return self.total_amount - self.paid_amount
    
    def calculate_totals(self):
        """Calculate subtotal, VAT, and total from items."""
        items = self.items.all()
        self.subtotal = sum(item.total for item in items)
        self.vat_amount = sum(item.vat_amount for item in items)
        self.total_amount = self.subtotal + self.vat_amount
        self.save(update_fields=['subtotal', 'vat_amount', 'total_amount'])
    
    def post_to_accounting(self, user=None):
        """
        Post invoice to accounting - creates journal entry.
        Uses Account Mapping (SAP/Oracle-style Account Determination) for account selection.
        
        Debit: Accounts Receivable (full amount)
        Credit: Sales Revenue (subtotal)
        Credit: VAT Payable (VAT amount)
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account, AccountType, AccountMapping, FiscalYear

        if self.status != 'draft':
            raise ValidationError("Only draft invoices can be posted.")

        FiscalYear.validate_posting_allowed(self.invoice_date)

        if self.total_amount <= 0:
            raise ValidationError("Invoice amount must be greater than zero.")
        
        # Get accounts using Account Mapping (SAP/Oracle standard)
        # Fallback to hardcoded codes for backward compatibility
        ar_account = AccountMapping.get_account_or_default('sales_invoice_receivable', '1200')
        if not ar_account:
            ar_account = Account.objects.filter(
                account_type=AccountType.ASSET, is_active=True, name__icontains='receivable'
            ).first()
        if not ar_account:
            ar_account = Account.objects.filter(
                account_type=AccountType.ASSET, is_active=True
            ).first()
        if not ar_account:
            raise ValidationError(
                "Accounts Receivable account not configured. "
                "Please set up Account Mapping in Finance → Account Mapping."
            )
        
        sales_account = AccountMapping.get_account_or_default('sales_invoice_revenue', '4000')
        if not sales_account:
            sales_account = Account.objects.filter(
                account_type=AccountType.INCOME, is_active=True, name__icontains='sales'
            ).first()
        if not sales_account:
            sales_account = Account.objects.filter(
                account_type=AccountType.INCOME, is_active=True
            ).first()
        if not sales_account:
            raise ValidationError(
                "Sales Revenue account not configured. "
                "Please set up Account Mapping in Finance → Account Mapping."
            )
        
        vat_payable_account = AccountMapping.get_account_or_default('sales_invoice_vat', '2100')
        if not vat_payable_account:
            vat_payable_account = Account.objects.filter(
                account_type=AccountType.LIABILITY, is_active=True, name__icontains='vat'
            ).first()
        if not vat_payable_account:
            vat_payable_account = Account.objects.filter(
                account_type=AccountType.LIABILITY, is_active=True
            ).first()
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.invoice_date,
            reference=self.invoice_number,
            description=f"Sales Invoice: {self.invoice_number} - {self.customer.name}",
            entry_type='standard',
            source_module='sales',
        )
        
        # Debit Accounts Receivable (total amount incl VAT)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f"AR - {self.customer.name}",
            debit=self.total_amount,
            credit=Decimal('0.00'),
        )
        
        # Credit Sales Revenue (subtotal excl VAT)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=sales_account,
            description=f"Sales - {self.invoice_number}",
            debit=Decimal('0.00'),
            credit=self.subtotal,
        )
        
        # Credit VAT Payable (if VAT exists and account found)
        if self.vat_amount > 0 and vat_payable_account:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_payable_account,
                description=f"Output VAT - {self.invoice_number}",
                debit=Decimal('0.00'),
                credit=self.vat_amount,
            )
        elif self.vat_amount > 0 and not vat_payable_account:
            # If VAT amount exists but no VAT account, add to sales
            # This ensures journal balances
            journal.lines.filter(account=sales_account).update(
                credit=self.subtotal + self.vat_amount
            )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Link journal to invoice and update status
        self.journal_entry = journal
        self.status = 'posted'
        self.save()
        
        return journal


class InvoiceItem(models.Model):
    """
    Line items for invoices.
    Supports both VAT-exclusive and VAT-inclusive pricing.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - vat_rate is computed from tax_code.rate (read-only, for display)
    - No tax_code = Out of Scope (0% VAT)
    """
    invoice = models.ForeignKey(
        Invoice, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Tax Code - source of truth for VAT (SAP/Oracle Standard)
    tax_code = models.ForeignKey(
        'finance.TaxCode',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='invoice_items',
        help_text='Tax Code determines VAT rate. No selection = Out of Scope (0%)'
    )
    
    # Computed VAT rate from tax_code (read-only, for display/reporting)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    is_vat_inclusive = models.BooleanField(default=False, help_text='If true, unit_price includes VAT')
    
    # Calculated
    total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.description} - {self.quantity}"
    
    def save(self, *args, **kwargs):
        # Derive VAT rate from Tax Code (No Tax Code = 0%)
        if self.tax_code:
            self.vat_rate = self.tax_code.rate
        else:
            self.vat_rate = Decimal('0.00')
        
        gross = self.quantity * self.unit_price
        
        if self.is_vat_inclusive and self.vat_rate > 0:
            # VAT-inclusive: Back-calculate net amount and VAT
            # Gross = Net + (Net * VAT_Rate/100) = Net * (1 + VAT_Rate/100)
            # Net = Gross / (1 + VAT_Rate/100)
            divisor = 1 + (self.vat_rate / 100)
            self.total = (gross / divisor).quantize(Decimal('0.01'))
            self.vat_amount = (gross - self.total).quantize(Decimal('0.01'))
        else:
            # VAT-exclusive: Standard calculation
            # VAT = Net * VAT_Rate/100
            self.total = gross
            self.vat_amount = (self.total * (self.vat_rate / 100)).quantize(Decimal('0.01'))
        
        super().save(*args, **kwargs)


class SalesCreditNote(BaseModel):
    """
    Sales Credit Note - reverses all or part of an invoice.
    Accounting: 
        Dr Sales Returns / Revenue
        Dr VAT Output
        Cr Accounts Receivable
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ]
    
    REASON_CHOICES = [
        ('return', 'Goods Returned'),
        ('discount', 'Discount Given'),
        ('error', 'Invoice Error'),
        ('cancelled', 'Order Cancelled'),
        ('other', 'Other'),
    ]
    
    credit_note_number = models.CharField(max_length=50, unique=True, editable=False)
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        related_name='credit_notes'
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='sales_credit_notes'
    )
    date = models.DateField()
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='return')
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Amounts
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Accounting link
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_credit_notes'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.credit_note_number} - {self.customer.name}"
    
    def save(self, *args, **kwargs):
        if not self.credit_note_number:
            self.credit_note_number = generate_number('SCN', SalesCreditNote, 'credit_note_number')
        if not self.customer_id and self.invoice_id:
            self.customer = self.invoice.customer
        super().save(*args, **kwargs)
    
    def calculate_totals(self):
        """Calculate totals from items."""
        items = self.items.all()
        self.subtotal = sum(item.total for item in items)
        self.vat_amount = sum(item.vat_amount for item in items)
        self.total_amount = self.subtotal + self.vat_amount
        self.save(update_fields=['subtotal', 'vat_amount', 'total_amount'])
    
    def post_to_accounting(self, user=None):
        """
        Post credit note to accounting - reverses invoice posting.
        Dr Sales Returns / Revenue
        Dr VAT Output  
        Cr Accounts Receivable
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.status != 'draft':
            raise ValidationError("Only draft credit notes can be posted.")

        FiscalYear.validate_posting_allowed(self.date)

        if self.total_amount <= 0:
            raise ValidationError("Credit note amount must be greater than zero.")
        
        # Validate against original invoice
        if self.total_amount > self.invoice.total_amount:
            raise ValidationError("Credit note cannot exceed original invoice amount.")
        
        # Get accounts
        ar_account = AccountMapping.get_account_or_default('sales_invoice_receivable', '1200')
        sales_account = AccountMapping.get_account_or_default('sales_invoice_revenue', '4000')
        vat_account = AccountMapping.get_account_or_default('sales_invoice_vat', '2100')
        
        if not ar_account:
            raise ValidationError("Accounts Receivable account not configured.")
        if not sales_account:
            raise ValidationError("Sales Revenue account not configured.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.date,
            reference=self.credit_note_number,
            description=f"Sales Credit Note: {self.credit_note_number} - {self.customer.name} (Ref: {self.invoice.invoice_number})",
            entry_type='standard',
            source_module='sales',
        )
        
        # Debit Sales Returns (reverses revenue)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=sales_account,
            description=f"Sales Return - {self.credit_note_number}",
            debit=self.subtotal,
            credit=Decimal('0.00'),
        )
        
        # Debit VAT Output (reverses VAT)
        if self.vat_amount > 0 and vat_account:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_account,
                description=f"VAT Reversal - {self.credit_note_number}",
                debit=self.vat_amount,
                credit=Decimal('0.00'),
            )
        
        # Credit Accounts Receivable
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f"AR Reduction - {self.customer.name}",
            debit=Decimal('0.00'),
            credit=self.total_amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update credit note
        self.journal_entry = journal
        self.status = 'posted'
        self.save()
        
        # Update invoice paid amount (credit note reduces receivable)
        self.invoice.paid_amount += self.total_amount
        if self.invoice.paid_amount >= self.invoice.total_amount:
            self.invoice.status = 'paid'
        elif self.invoice.paid_amount > 0:
            self.invoice.status = 'partial'
        self.invoice.save(update_fields=['paid_amount', 'status'])
        
        return journal


class SalesCreditNoteItem(models.Model):
    """
    Line items for sales credit notes.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - vat_rate is computed from tax_code.rate (read-only, for display)
    - No tax_code = Out of Scope (0% VAT)
    """
    credit_note = models.ForeignKey(
        SalesCreditNote,
        on_delete=models.CASCADE,
        related_name='items'
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Tax Code - source of truth for VAT (SAP/Oracle Standard)
    tax_code = models.ForeignKey(
        'finance.TaxCode',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='sales_credit_note_items',
        help_text='Tax Code determines VAT rate. No selection = Out of Scope (0%)'
    )
    
    # Computed VAT rate from tax_code (read-only, for display/reporting)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Calculated
    total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['id']
    
    def save(self, *args, **kwargs):
        # Derive VAT rate from Tax Code (No Tax Code = 0%)
        if self.tax_code:
            self.vat_rate = self.tax_code.rate
        else:
            self.vat_rate = Decimal('0.00')
        
        self.total = self.quantity * self.unit_price
        self.vat_amount = self.total * (self.vat_rate / 100)
        super().save(*args, **kwargs)

