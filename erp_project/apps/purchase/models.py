"""
Purchase Models - Vendors, Purchase Requests, Purchase Orders, Vendor Bills
All bill postings create journal entries in accounting as single source of truth.

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


class Vendor(BaseModel):
    """
    Vendor/Supplier model.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    
    vendor_number = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='United Arab Emirates')
    trn = models.CharField(max_length=20, blank=True, verbose_name='Tax Registration Number (TRN)',
                          help_text='UAE VAT TRN for B2B transactions')
    payment_terms = models.CharField(max_length=50, blank=True, default='Net 30')
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.vendor_number} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.vendor_number:
            self.vendor_number = generate_number('VENDOR', Vendor, 'vendor_number')
        super().save(*args, **kwargs)


class PurchaseRequest(BaseModel):
    """
    Purchase Request (PR) model.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('returned', 'Returned for Revision'),
        ('converted', 'Converted to PO'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    pr_number = models.CharField(max_length=50, unique=True, editable=False)
    date = models.DateField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='purchase_requests'
    )
    required_by_date = models.DateField(null=True, blank=True)
    department = models.ForeignKey(
        'hr.Department',
        on_delete=models.PROTECT,
        related_name='purchase_requests',
        null=True,
        blank=True
    )
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    
    # Calculated
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Rejection/return comments from approver
    rejection_reason = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.pr_number
    
    def save(self, *args, **kwargs):
        if not self.pr_number:
            self.pr_number = generate_number('PURCHASE_REQUEST', PurchaseRequest, 'pr_number')
        super().save(*args, **kwargs)
    
    def calculate_total(self):
        self.total_amount = sum(item.total for item in self.items.all())
        self.save(update_fields=['total_amount'])


class PurchaseRequestItem(models.Model):
    """
    Line items for purchase requests.
    """
    UNIT_CHOICES = [
        ('pcs', 'Pcs'),
        ('box', 'Box'),
        ('kg', 'Kg'),
        ('ltr', 'Ltr'),
        ('set', 'Set'),
        ('other', 'Other'),
    ]
    
    purchase_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.CASCADE,
        related_name='items'
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='pcs')
    estimated_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['id']
    
    def save(self, *args, **kwargs):
        self.total = (self.quantity * self.estimated_price).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class PurchaseRequestAttachment(models.Model):
    """Attachments for purchase requests."""
    purchase_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    file = models.FileField(upload_to='purchase_request_attachments/%Y/%m/')
    filename = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    class Meta:
        ordering = ['-uploaded_at']


class PurchaseOrder(BaseModel):
    """
    Purchase Order (PO) model.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('confirmed', 'Confirmed'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ]
    
    po_number = models.CharField(max_length=50, unique=True, editable=False)
    purchase_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_orders'
    )
    service_request = models.ForeignKey(
        'service_request.ServiceRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_orders'
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name='purchase_orders'
    )
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    
    # Amounts
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.po_number} - {self.vendor.name}"
    
    def save(self, *args, **kwargs):
        if not self.po_number:
            self.po_number = generate_number('PURCHASE_ORDER', PurchaseOrder, 'po_number')
        super().save(*args, **kwargs)
    
    def calculate_totals(self):
        items = self.items.all()
        self.subtotal = sum(item.total for item in items)
        self.vat_amount = sum(item.vat_amount for item in items)
        self.total_amount = self.subtotal + self.vat_amount
        self.save(update_fields=['subtotal', 'vat_amount', 'total_amount'])


class PurchaseOrderItem(models.Model):
    """
    Line items for purchase orders.
    Supports both VAT-exclusive and VAT-inclusive pricing.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - vat_rate is computed from tax_code.rate (read-only, for display)
    - No tax_code = Out of Scope (0% VAT)
    """
    purchase_order = models.ForeignKey(
        PurchaseOrder,
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
        related_name='purchase_order_items',
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


class VendorBill(BaseModel):
    """
    Vendor Bill model.
    Posts to Accounting: Debit Expense/Asset, Debit VAT Recoverable, Credit AP
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),  # Posted to accounting
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('overdue', 'Overdue'),
    ]
    
    bill_number = models.CharField(max_length=50, unique=True, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bills'
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name='bills'
    )
    vendor_invoice_number = models.CharField(max_length=100, blank=True)
    bill_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    
    # Amounts
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    goods_received = models.BooleanField(
        default=False,
        help_text=(
            "If True, this bill is for goods already received into inventory. "
            "Posting will debit GRN Clearing (2010) instead of Expense to close "
            "the 3-way match: PO → GRN → Bill."
        ),
    )

    # Link to accounting journal entry (single source of truth)
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendor_bills'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.bill_number} - {self.vendor.name}"
    
    def save(self, *args, **kwargs):
        if not self.bill_number:
            self.bill_number = generate_number('BILL', VendorBill, 'bill_number')
        super().save(*args, **kwargs)
    
    @property
    def balance(self):
        return self.total_amount - self.paid_amount
    
    def calculate_totals(self):
        items = self.items.all()
        self.subtotal = sum(item.total for item in items)
        self.vat_amount = sum(item.vat_amount for item in items)
        self.total_amount = self.subtotal + self.vat_amount
        self.save(update_fields=['subtotal', 'vat_amount', 'total_amount'])
    
    def post_to_accounting(self, user=None):
        """
        Post bill to accounting — creates journal entry.

        Two modes based on goods_received flag:

        A) goods_received=True  (bill for inventory already received via GRN):
           Dr GRN Clearing (2010)   ← closes the liability created by Stock In
           Dr VAT Recoverable       ← if applicable
           Cr Accounts Payable      ← recognizes vendor liability

        B) goods_received=False (service / direct expense bill):
           Dr Expense Account       ← direct P&L hit
           Dr VAT Recoverable       ← if applicable
           Cr Accounts Payable      ← recognizes vendor liability
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.status != 'draft':
            raise ValidationError("Only draft bills can be posted.")

        if self.total_amount <= 0:
            raise ValidationError("Bill amount must be greater than zero.")

        FiscalYear.validate_posting_allowed(self.bill_date)

        if self.goods_received and not self.purchase_order:
            raise ValidationError(
                "A goods-received bill must be linked to a Purchase Order. "
                "Set the PO reference or uncheck 'Goods Received'."
            )

        ap_account = AccountMapping.get_account_or_default('vendor_bill_payable', '2000')
        if not ap_account:
            raise ValidationError(
                "Accounts Payable account not configured. "
                "Expected account 2000 or set up 'vendor_bill_payable' in Finance → Account Mapping."
            )

        if self.goods_received:
            debit_account = AccountMapping.get_account_or_default('inventory_grn_clearing', '2010')
            if not debit_account:
                raise ValidationError(
                    "GRN Clearing account not configured. "
                    "Expected account 2010 or set up 'inventory_grn_clearing' in Finance → Account Mapping."
                )
            debit_label = "GRN Clearing"
        else:
            debit_account = AccountMapping.get_account_or_default('vendor_bill_expense', '5000')
            if not debit_account:
                raise ValidationError(
                    "Expense account not configured. "
                    "Expected account 5000 or set up 'vendor_bill_expense' in Finance → Account Mapping."
                )
            debit_label = "Expense"

        vat_account = AccountMapping.get_account_or_default('vendor_bill_vat', '1300')

        journal = JournalEntry.objects.create(
            date=self.bill_date,
            reference=self.bill_number,
            description=f"Vendor Bill: {self.bill_number} - {self.vendor.name}",
            entry_type='standard',
            source_module='purchase',
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=debit_account,
            description=f"{debit_label} - {self.bill_number}",
            debit=self.subtotal,
            credit=Decimal('0.00'),
        )

        if self.vat_amount > 0:
            if not vat_account:
                raise ValidationError(
                    "VAT Recoverable account not configured. "
                    "Expected account 1300 or set up 'vendor_bill_vat' in Finance → Account Mapping."
                )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_account,
                description=f"Input VAT - {self.bill_number}",
                debit=self.vat_amount,
                credit=Decimal('0.00'),
            )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f"AP - {self.vendor.name}",
            debit=Decimal('0.00'),
            credit=self.total_amount,
        )

        journal.calculate_totals()
        journal.post(user)

        self.journal_entry = journal
        self.status = 'posted'
        self.save(update_fields=['journal_entry', 'status'])

        return journal


class VendorBillItem(models.Model):
    """
    Line items for vendor bills.
    Supports both VAT-exclusive and VAT-inclusive pricing.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - vat_rate is computed from tax_code.rate (read-only, for display)
    - No tax_code = Out of Scope (0% VAT)
    """
    bill = models.ForeignKey(
        VendorBill,
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
        related_name='vendor_bill_items',
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


# ============ PURCHASE CREDIT NOTE ============

class PurchaseCreditNote(BaseModel):
    """
    Purchase Credit Note - reverses all or part of a vendor bill.
    Accounting:
        Cr Expense / Asset
        Cr VAT Input
        Dr Accounts Payable
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ]
    
    REASON_CHOICES = [
        ('return', 'Goods Returned'),
        ('discount', 'Discount Received'),
        ('error', 'Bill Error'),
        ('cancelled', 'Order Cancelled'),
        ('other', 'Other'),
    ]
    
    credit_note_number = models.CharField(max_length=50, unique=True, editable=False)
    bill = models.ForeignKey(
        VendorBill,
        on_delete=models.PROTECT,
        related_name='credit_notes'
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name='purchase_credit_notes'
    )
    date = models.DateField()
    vendor_credit_note_ref = models.CharField(max_length=100, blank=True, help_text="Vendor's credit note reference")
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
        related_name='purchase_credit_notes'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.credit_note_number} - {self.vendor.name}"
    
    def save(self, *args, **kwargs):
        if not self.credit_note_number:
            self.credit_note_number = generate_number('PCN', PurchaseCreditNote, 'credit_note_number')
        if not self.vendor_id and self.bill_id:
            self.vendor = self.bill.vendor
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
        Post credit note to accounting - reverses bill posting.
        Cr Expense (reverses expense)
        Cr VAT Input (reverses VAT recoverable)
        Dr Accounts Payable
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.status != 'draft':
            raise ValidationError("Only draft credit notes can be posted.")

        FiscalYear.validate_posting_allowed(self.date)

        if self.total_amount <= 0:
            raise ValidationError("Credit note amount must be greater than zero.")
        
        # Validate against original bill
        if self.total_amount > self.bill.total_amount:
            raise ValidationError("Credit note cannot exceed original bill amount.")
        
        # Get accounts
        ap_account = AccountMapping.get_account_or_default('vendor_bill_payable', '2000')
        expense_account = AccountMapping.get_account_or_default('vendor_bill_expense', '5000')
        vat_account = AccountMapping.get_account_or_default('vendor_bill_vat', '1300')
        
        if not ap_account:
            raise ValidationError("Accounts Payable account not configured.")
        if not expense_account:
            raise ValidationError("Expense account not configured.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.date,
            reference=self.credit_note_number,
            description=f"Purchase Credit Note: {self.credit_note_number} - {self.vendor.name} (Ref: {self.bill.bill_number})",
            entry_type='standard',
            source_module='purchase',
        )
        
        # Debit Accounts Payable (reduces what we owe)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f"AP Reduction - {self.vendor.name}",
            debit=self.total_amount,
            credit=Decimal('0.00'),
        )
        
        # Credit Expense (reverses expense)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=expense_account,
            description=f"Expense Reversal - {self.credit_note_number}",
            debit=Decimal('0.00'),
            credit=self.subtotal,
        )
        
        # Credit VAT Input (reverses VAT recoverable)
        if self.vat_amount > 0 and vat_account:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_account,
                description=f"VAT Reversal - {self.credit_note_number}",
                debit=Decimal('0.00'),
                credit=self.vat_amount,
            )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update credit note
        self.journal_entry = journal
        self.status = 'posted'
        self.save()
        
        # Update bill paid amount (credit note reduces payable)
        self.bill.paid_amount += self.total_amount
        if self.bill.paid_amount >= self.bill.total_amount:
            self.bill.status = 'paid'
        elif self.bill.paid_amount > 0:
            self.bill.status = 'partial'
        self.bill.save(update_fields=['paid_amount', 'status'])
        
        return journal


class PurchaseCreditNoteItem(models.Model):
    """
    Line items for purchase credit notes.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - vat_rate is computed from tax_code.rate (read-only, for display)
    - No tax_code = Out of Scope (0% VAT)
    """
    credit_note = models.ForeignKey(
        PurchaseCreditNote,
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
        related_name='purchase_credit_note_items',
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


# ============ EXPENSE CLAIMS ============
# Employee expense reimbursement - posts to accounting on approval

class ExpenseClaim(BaseModel):
    """
    Employee expense claims - moved from Finance to Purchase module.
    Acts as a purchase transaction (employee as vendor).
    
    Accounting on APPROVAL:
    Dr  Expense Account (per line item)
    Dr  VAT Recoverable (if applicable, with receipt)
    Cr  Employee Payable (liability)
    
    Accounting on PAYMENT:
    Dr  Employee Payable
    Cr  Bank / Cash Account
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('paid', 'Paid'),
    ]
    
    claim_number = models.CharField(max_length=50, unique=True, editable=False)
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='purchase_expense_claims'
    )
    claim_date = models.DateField()
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Totals
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_vat = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Approval workflow
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_purchase_claims'
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # Journal entry created on approval
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_expense_claims'
    )
    
    # Payment journal entry
    payment_journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expense_claim_payments'
    )
    
    # Bank account for payment
    paid_from_bank = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    paid_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ['-claim_date', '-created_at']
    
    def __str__(self):
        return f"{self.claim_number} - {self.employee.get_full_name()}"
    
    def save(self, *args, **kwargs):
        if not self.claim_number:
            self.claim_number = generate_number('EXP-CLM', ExpenseClaim, 'claim_number')
        super().save(*args, **kwargs)
    
    def calculate_totals(self):
        """Calculate totals from items."""
        items = self.items.all()
        self.total_amount = sum(item.amount + item.vat_amount for item in items)
        self.total_vat = sum(item.vat_amount for item in items if item.has_receipt)
        self.save(update_fields=['total_amount', 'total_vat'])
    
    def post_approval_journal(self, user=None):
        """
        Post journal entry on approval.
        Uses Account Mapping (SAP/Oracle-style Account Determination) for account selection.
        
        Dr  Expense Account (for each line)
        Dr  VAT Recoverable (if applicable)
        Cr  Employee Payable (liability)
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account, AccountType, AccountMapping
        
        if self.status != 'approved':
            raise ValidationError("Only approved claims can be posted to accounting.")
        
        if self.journal_entry:
            raise ValidationError("Journal entry already exists for this claim.")
        
        # Get Employee Payable account using Account Mapping (SAP/Oracle standard)
        employee_payable = AccountMapping.get_account_or_default('expense_claim_payable', '2100')
        if not employee_payable:
            employee_payable = Account.objects.filter(
                account_type=AccountType.LIABILITY, is_active=True, name__icontains='payable'
            ).first()
        if not employee_payable:
            raise ValidationError(
                "Employee Payable account not configured. "
                "Please set up Account Mapping in Finance → Account Mapping."
            )
        
        # Get VAT Recoverable account using Account Mapping
        vat_recoverable = AccountMapping.get_account_or_default('expense_claim_vat', '1300')
        if not vat_recoverable:
            vat_recoverable = Account.objects.filter(
                account_type=AccountType.ASSET, is_active=True, code__startswith='13'
            ).first()
        
        # Get default expense account using Account Mapping
        default_expense = AccountMapping.get_account_or_default('expense_claim_expense', '5000')
        if not default_expense:
            default_expense = Account.objects.filter(
                account_type=AccountType.EXPENSE, is_active=True
            ).first()
        
        if not default_expense:
            raise ValidationError(
                "Expense account not configured. "
                "Please set up Account Mapping in Finance → Account Mapping."
            )
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.claim_date,
            reference=self.claim_number,
            description=f"Expense Claim: {self.claim_number} - {self.employee.get_full_name()}",
            entry_type='standard',
            source_module='expense_claim',
        )
        
        total_expense = Decimal('0.00')
        total_vat = Decimal('0.00')
        
        # Debit each expense line to appropriate account
        # Each line can have its own expense account, fallback to default
        for item in self.items.all():
            expense_account = item.expense_account or default_expense
            
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=expense_account,
                description=f"{item.get_category_display()}: {item.description}",
                debit=item.amount,
                credit=Decimal('0.00'),
            )
            total_expense += item.amount
            
            # VAT only if has receipt
            if item.vat_amount > 0 and item.has_receipt and vat_recoverable:
                JournalEntryLine.objects.create(
                    journal_entry=journal,
                    account=vat_recoverable,
                    description=f"Input VAT - {item.description}",
                    debit=item.vat_amount,
                    credit=Decimal('0.00'),
                )
                total_vat += item.vat_amount
        
        # Credit Employee Payable (total including VAT if claimed)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=employee_payable,
            description=f"Employee Payable - {self.employee.get_full_name()}",
            debit=Decimal('0.00'),
            credit=total_expense + total_vat,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.journal_entry = journal
        self.save(update_fields=['journal_entry'])
        
        return journal
    
    def post_payment_journal(self, bank_account, payment_date, reference='', user=None):
        """
        Post journal entry on payment.
        Uses Account Mapping (SAP/Oracle-style Account Determination) for account selection.
        
        Dr  Employee Payable
        Cr  Bank / Cash Account
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account, AccountType, AccountMapping
        
        if self.status != 'approved':
            raise ValidationError("Only approved claims can be paid.")
        
        if self.payment_journal_entry:
            raise ValidationError("Payment journal already exists for this claim.")
        
        # Get Employee Payable account using Account Mapping (SAP/Oracle standard)
        employee_payable = AccountMapping.get_account_or_default('expense_claim_clear', '2100')
        if not employee_payable:
            employee_payable = Account.objects.filter(
                account_type=AccountType.LIABILITY, is_active=True, name__icontains='payable'
            ).first()
        
        # Get bank account GL account
        if not bank_account.gl_account:
            raise ValidationError("Bank account has no linked GL account.")
        
        payment_amount = self.total_amount
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=payment_date,
            reference=reference or f"PAY-{self.claim_number}",
            description=f"Payment: Expense Claim {self.claim_number} - {self.employee.get_full_name()}",
            entry_type='standard',
            source_module='payment',
        )
        
        # Debit Employee Payable (clear liability)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=employee_payable,
            description=f"Clear Employee Payable - {self.employee.get_full_name()}",
            debit=payment_amount,
            credit=Decimal('0.00'),
        )
        
        # Credit Bank Account
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account.gl_account,
            description=f"Payment to {self.employee.get_full_name()}",
            debit=Decimal('0.00'),
            credit=payment_amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.payment_journal_entry = journal
        self.paid_from_bank = bank_account
        self.paid_date = payment_date
        self.payment_reference = reference
        self.status = 'paid'
        self.save(update_fields=['payment_journal_entry', 'paid_from_bank', 'paid_date', 'payment_reference', 'status'])
        
        return journal


class ExpenseClaimItem(models.Model):
    """
    Individual expense items within a claim.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - VAT only claimed if has_receipt = True
    - No tax_code = Out of Scope (0% VAT)
    """
    CATEGORY_CHOICES = [
        ('travel', 'Travel'),
        ('meals', 'Meals & Entertainment'),
        ('accommodation', 'Accommodation'),
        ('transport', 'Transport'),
        ('office', 'Office Supplies'),
        ('communication', 'Communication'),
        ('other', 'Other'),
    ]
    
    expense_claim = models.ForeignKey(
        ExpenseClaim,
        on_delete=models.CASCADE,
        related_name='items'
    )
    date = models.DateField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Tax Code - source of truth for VAT (SAP/Oracle Standard)
    tax_code = models.ForeignKey(
        'finance.TaxCode',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='expense_claim_items',
        help_text='Tax Code determines VAT rate. No selection = Out of Scope (0%)'
    )
    
    # Computed VAT amount from tax_code (only if has_receipt)
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    has_receipt = models.BooleanField(default=False)
    receipt = models.FileField(upload_to='expense_receipts/', blank=True, null=True)
    is_non_deductible = models.BooleanField(default=False, help_text="Non-deductible for Corporate Tax")
    
    # Account to post to
    expense_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='purchase_expense_items'
    )
    
    class Meta:
        ordering = ['date']
    
    def __str__(self):
        return f"{self.category} - {self.amount}"
    
    def save(self, *args, **kwargs):
        # Derive VAT amount from Tax Code (No Tax Code or no receipt = 0%)
        if self.tax_code and self.has_receipt:
            self.vat_amount = (self.amount * (self.tax_code.rate / 100)).quantize(Decimal('0.01'))
        else:
            self.vat_amount = Decimal('0.00')
        super().save(*args, **kwargs)


# ============ RECURRING EXPENSES ============
# System-generated periodic expenses (rent, utilities, subscriptions, etc.)

class RecurringExpense(BaseModel):
    """
    Recurring Expense setup for periodic expenses.
    Auto-generates expense transactions and posts to accounting.
    
    Examples: Rent, Utilities, Subscriptions, AMC/Maintenance, Insurance
    
    On each cycle execution:
    Dr  Expense Account
    Dr  VAT Recoverable (if applicable)
    Cr  Accounts Payable / Bank (based on configuration)
    """
    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-Annual'),
        ('yearly', 'Yearly'),
    ]
    
    PAYMENT_MODE_CHOICES = [
        ('ap', 'Create Payable (AP)'),
        ('bank', 'Direct Bank Payment'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
    ]
    
    name = models.CharField(max_length=200, help_text="E.g., Office Rent, Internet Subscription")
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name='recurring_expenses'
    )
    expense_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.PROTECT,
        related_name='recurring_expenses',
        help_text="Expense account to debit"
    )
    tax_code = models.ForeignKey(
        'finance.TaxCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="VAT Tax Code"
    )
    
    # Amount
    amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Amount excluding VAT")
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Schedule
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Leave blank for indefinite")
    next_run_date = models.DateField(help_text="Next date to generate expense")
    
    # Payment configuration
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='ap')
    bank_account = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Required if payment mode is Direct Bank"
    )
    
    # Auto-post
    auto_post = models.BooleanField(default=True, help_text="Auto-post journal entry when created")
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Tracking
    description = models.TextField(blank=True)
    last_run_date = models.DateField(null=True, blank=True)
    total_generated = models.IntegerField(default=0, help_text="Number of expenses generated")
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} - {self.vendor.name} ({self.get_frequency_display()})"
    
    def save(self, *args, **kwargs):
        # Calculate total with VAT
        if self.tax_code and self.tax_code.rate > 0:
            self.vat_amount = self.amount * (self.tax_code.rate / 100)
        self.total_amount = self.amount + self.vat_amount
        
        # Set next_run_date if not set
        if not self.next_run_date:
            self.next_run_date = self.start_date
        
        super().save(*args, **kwargs)
    
    def get_next_date(self, from_date):
        """Calculate the next run date based on frequency."""
        from dateutil.relativedelta import relativedelta
        
        if self.frequency == 'monthly':
            return from_date + relativedelta(months=1)
        elif self.frequency == 'quarterly':
            return from_date + relativedelta(months=3)
        elif self.frequency == 'semi_annual':
            return from_date + relativedelta(months=6)
        elif self.frequency == 'yearly':
            return from_date + relativedelta(years=1)
        return from_date
    
    def execute(self, user=None):
        """
        Execute the recurring expense - SAP/Oracle Standard Implementation.
        
        IMPORTANT: Recurring Expense is a TEMPLATE only.
        It generates a VendorBill document that follows normal approval → posting flow.
        The generated document then uses Account Mapping for posting to ledger.
        
        Returns the created RecurringExpenseLog or None if skipped.
        """
        from apps.finance.models import AccountingPeriod, AccountingSettings
        from datetime import date
        
        # Check if active
        if self.status != 'active':
            return None
        
        # Check end date
        if self.end_date and self.next_run_date > self.end_date:
            self.status = 'completed'
            self.save(update_fields=['status'])
            return None
        
        # Check if period is locked (only if auto_post is enabled)
        if self.auto_post:
            period = AccountingPeriod.objects.filter(
                start_date__lte=self.next_run_date,
                end_date__gte=self.next_run_date,
                is_active=True
            ).first()
            
            if period and period.is_locked:
                # Log failure - cannot post to locked period
                log = RecurringExpenseLog.objects.create(
                    recurring_expense=self,
                    execution_date=date.today(),
                    expense_date=self.next_run_date,
                    status='failed',
                    error_message=f"Period {period.name} is locked. Cannot post.",
                )
                return log
        
        # Calculate due date based on vendor terms
        due_date = self.next_run_date + timedelta(days=self.vendor.payment_terms or 30)
        
        # Generate a VendorBill document (SAP/Oracle Standard)
        # The VendorBill follows normal approval → posting flow
        vendor_bill = VendorBill.objects.create(
            vendor=self.vendor,
            vendor_invoice_number=f"REC-{self.pk}-{self.total_generated + 1}",
            bill_date=self.next_run_date,
            due_date=due_date,
            status='draft',  # IMPORTANT: Always starts as draft
            notes=f"Auto-generated from Recurring Expense: {self.name}",
        )
        
        # Create bill item with Tax Code
        VendorBillItem.objects.create(
            bill=vendor_bill,
            description=f"{self.name} - {self.next_run_date.strftime('%B %Y')}",
            quantity=Decimal('1.00'),
            unit_price=self.amount,
            tax_code=self.tax_code,  # Tax Code determines VAT
        )
        
        # Calculate bill totals
        vendor_bill.calculate_totals()
        
        # Store reference to generated bill
        journal_entry = None
        
        # Auto-post if enabled (check both recurring expense setting and global settings)
        if self.auto_post:
            # Check global settings
            accounting_settings = AccountingSettings.get_settings()
            if accounting_settings.auto_post_vendor_bill:
                try:
                    # Post the bill to accounting - this follows normal VendorBill posting flow
                    # which uses Account Mapping for account determination
                    journal_entry = vendor_bill.post_to_accounting(user)
                except Exception as e:
                    log = RecurringExpenseLog.objects.create(
                        recurring_expense=self,
                        execution_date=date.today(),
                        expense_date=self.next_run_date,
                        status='failed',
                        error_message=f"Bill created but failed to post: {str(e)}",
                        vendor_bill=vendor_bill,
                    )
                    return log
        
        # Create success log
        log = RecurringExpenseLog.objects.create(
            recurring_expense=self,
            execution_date=date.today(),
            expense_date=self.next_run_date,
            status='success',
            vendor_bill=vendor_bill,
            journal_entry=journal_entry,
            amount=vendor_bill.total_amount,
        )
        
        # Update recurring expense
        self.last_run_date = self.next_run_date
        self.next_run_date = self.get_next_date(self.next_run_date)
        self.total_generated += 1
        
        # Check if completed after this run
        if self.end_date and self.next_run_date > self.end_date:
            self.status = 'completed'
        
        self.save(update_fields=['last_run_date', 'next_run_date', 'total_generated', 'status'])
        
        return log


class RecurringExpenseLog(models.Model):
    """
    Log of recurring expense executions for audit trail.
    
    SAP/Oracle Standard: Recurring expenses generate VendorBill documents.
    The journal_entry is created when the VendorBill is posted (not directly).
    """
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]
    
    recurring_expense = models.ForeignKey(
        RecurringExpense,
        on_delete=models.CASCADE,
        related_name='logs'
    )
    execution_date = models.DateField()
    expense_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(blank=True)
    
    # Generated VendorBill (SAP/Oracle: template generates document)
    vendor_bill = models.ForeignKey(
        'VendorBill',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_expense_logs'
    )
    
    # Journal Entry (set when VendorBill is posted)
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-execution_date', '-created_at']
    
    def __str__(self):
        return f"{self.recurring_expense.name} - {self.expense_date} ({self.status})"

