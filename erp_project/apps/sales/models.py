"""
Sales Models - Estimates and Invoices
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


class Estimate(BaseModel):
    """
    Sales estimate (formerly quotation).
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('under_negotiation', 'Under Negotiation'),
        ('quotation_won', 'Quot Won'),
        ('quotation_lost', 'Quot Lost'),
    ]

    #: Estimates allowed to convert to invoice / project (won or internally approved).
    FOLLOW_ON_STATUSES = frozenset({'approved', 'quotation_won'})

    EDIT_APPROVAL_STATUS_CHOICES = [
        ('none', 'No pending edit review'),
        ('pending', 'Pending edit approval'),
        ('rejected', 'Edit rejected'),
    ]

    DISCOUNT_TYPE_CHOICES = [
        ('none', 'None'),
        ('percent', 'Percentage'),
        ('amount', 'Fixed amount'),
    ]

    SCOPE_CHOICES = [
        ('amc', 'AMC'),
        ('snag', 'Snag'),
        ('amc_fitout', 'AMC Fitout'),
        ('fitout', 'Fitout'),
        ('project', 'Project'),
        ('amc_certification', 'AMC Certification'),
        ('fitout_certification', 'Fitout Certification'),
    ]

    OCCUPANCY_TYPE_CHOICES = [
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('labour_accommodation', 'Labour Accommodation'),
        ('restaurants', 'Restaurants'),
        ('factories_industries', 'Factories - Industries'),
    ]

    TYPE_OF_WORK_CHOICES = [
        ('installation_with_amc', 'Installation with AMC'),
        ('installation_without_amc', 'Installation without AMC'),
        ('amc', 'AMC'),
        ('maintenance', 'Maintenance'),
        ('direct_sale', 'Direct Sale'),
    ]

    SCOPE_OF_WORK_CHOICES = [
        ('two_way_manifold', '2 Way Manifold System'),
        ('four_way_manifold', '4 Way Manifold System'),
        ('central_tank', 'Central Tank System'),
        ('rectification', 'Rectification Work'),
        ('fitout', 'Fitout'),
    ]
    
    estimate_number = models.CharField(max_length=50, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer, 
        on_delete=models.PROTECT, 
        related_name='estimates'
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_estimates',
    )
    prepared_by = models.CharField(max_length=200, blank=True, help_text='Name shown on estimate document')
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='estimates',
    )
    scope = models.JSONField(default=list, blank=True, help_text='Legacy scope tags (deprecated)')
    type_of_occupancy = models.CharField(
        max_length=40,
        blank=True,
        default='',
        choices=OCCUPANCY_TYPE_CHOICES,
        verbose_name='Type of occupancy',
    )
    type_of_work = models.CharField(
        max_length=40,
        blank=True,
        default='',
        choices=TYPE_OF_WORK_CHOICES,
        verbose_name='Type of work',
    )
    scope_of_work = models.CharField(
        max_length=40,
        blank=True,
        default='',
        choices=SCOPE_OF_WORK_CHOICES,
        verbose_name='Scope of work',
    )
    date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    edit_approval_status = models.CharField(
        max_length=20,
        choices=EDIT_APPROVAL_STATUS_CHOICES,
        default='none',
        help_text='When approval is configured for estimates, edits from non-approvers queue here.',
    )
    edit_approval_submitted_at = models.DateTimeField(null=True, blank=True)
    edit_approval_submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='estimate_edit_approval_submissions',
    )
    revision_count = models.PositiveIntegerField(
        default=0,
        help_text='Increments when resubmitted for approval after an edit rejection (R1, R2, … on PDF).',
    )
    approval_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='estimate_status_approval_requests',
        help_text='User who last sent the estimate for status approval (Sent).',
    )
    awaiting_resubmit_revision = models.BooleanField(
        default=False,
        help_text='Set when status is rejected; next Mark as Sent bumps revision (R1, R2, …).',
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text='Reason given when the approver rejected this estimate.',
    )
    notes = models.TextField(blank=True, help_text='Internal notes (optional)')
    client_note = models.TextField(blank=True, help_text='Note for the client (shown on estimate)')
    terms_and_conditions = models.TextField(blank=True)

    discount_type = models.CharField(
        max_length=20, choices=DISCOUNT_TYPE_CHOICES, default='none',
    )
    discount_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    authorized_signature = models.ImageField(
        upload_to='estimate_signatures/', blank=True, null=True,
        help_text='Authorized signatory image',
    )
    customer_signature = models.ImageField(
        upload_to='estimate_signatures/', blank=True, null=True,
        help_text='Customer signature image (e.g. scan)',
    )
    show_rates_on_pdf = models.BooleanField(
        default=True,
        help_text='If off, PDF shows description and quantity only; totals still show VAT and amount.',
    )
    show_group_totals_on_pdf = models.BooleanField(
        default=False,
        help_text='If on, PDF shows each group heading and a subtotal after its line items.',
    )
    show_brand_name_on_pdf = models.BooleanField(
        default=False,
        help_text='If on, PDF shows the inventory item brand name on each line.',
    )

    # Calculated fields
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    discount_applied = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        help_text='Last calculated discount amount on total',
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.display_estimate_number} - {self.customer.name}"

    @property
    def revision_label(self):
        """Revision suffix after resubmit post-rejection, e.g. R1."""
        if self.revision_count and self.revision_count > 0:
            return f'R{self.revision_count}'
        return ''

    @property
    def display_estimate_number(self):
        """Quotation / PDF number including revision suffix when applicable."""
        base = self.estimate_number
        label = self.revision_label
        return f'{base}-{label}' if label else base

    @property
    def display_proforma_number(self):
        return f'PI-{self.display_estimate_number}'

    @property
    def proforma_vat_rate_percent(self):
        from apps.sales.proforma_calculation import resolve_proforma_vat_rate_percent

        return resolve_proforma_vat_rate_percent(self)
    
    def save(self, *args, **kwargs):
        if not self.estimate_number:
            self.estimate_number = generate_number('ESTIMATE', Estimate, 'estimate_number')
        super().save(*args, **kwargs)
    
    def total_cost(self) -> Decimal:
        """Sum of line base cost (qty × unit_price) before profit markup; used when converting to project budget."""
        from django.db.models import DecimalField, ExpressionWrapper, F, Sum

        agg = self.items.aggregate(
            s=Sum(
                ExpressionWrapper(
                    F('quantity') * F('unit_price'),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                )
            )
        )
        val = agg['s']
        if val is None:
            return Decimal('0.00')
        return val.quantize(Decimal('0.01'))

    def calculate_totals(self):
        """Calculate subtotal, VAT, discount, and total from line items."""
        items = list(self.items.all())
        subtotal = Decimal('0.00')
        vat_sum = Decimal('0.00')
        for item in items:
            item.save()  # refresh rate, total, vat from line
            subtotal += item.total
            vat_sum += item.vat_amount
        gross_before = subtotal + vat_sum
        discount_amt = Decimal('0.00')
        if self.discount_type == 'percent' and self.discount_value > 0:
            discount_amt = (gross_before * self.discount_value / Decimal('100')).quantize(Decimal('0.01'))
        elif self.discount_type == 'amount' and self.discount_value > 0:
            discount_amt = min(self.discount_value, gross_before)
        self.subtotal = subtotal
        self.vat_amount = vat_sum
        self.discount_applied = discount_amt
        self.total_amount = gross_before - discount_amt
        self.save(update_fields=['subtotal', 'vat_amount', 'total_amount', 'discount_applied'])

    @property
    def scope_display_labels(self):
        """Human-readable work classification (new fields + legacy scope)."""
        labels = []
        if self.type_of_occupancy:
            labels.append(self.get_type_of_occupancy_display())
        if self.type_of_work:
            labels.append(self.get_type_of_work_display())
        if self.scope_of_work:
            labels.append(self.get_scope_of_work_display())
        if labels:
            return labels
        if not self.scope:
            return []
        legacy = dict(self.SCOPE_CHOICES)
        return [legacy.get(code, code) for code in self.scope]

    @property
    def has_work_classification(self) -> bool:
        return bool(self.type_of_occupancy or self.type_of_work or self.scope_of_work)

    @property
    def allows_follow_on_conversion(self) -> bool:
        """True when the estimate may be converted to an invoice or project."""
        return self.status in self.FOLLOW_ON_STATUSES

    def allows_edit_by(self, user) -> bool:
        from apps.sales.approval_rules import user_can_edit_estimate

        return user_can_edit_estimate(user, self)


class EstimateProformaInvoice(models.Model):
    """Partial proforma invoice generated from a won quotation (advance / milestone billing)."""

    CHARGE_TYPE_CHOICES = [
        ('percent', 'Percentage of quotation subtotal'),
        ('amount', 'Fixed amount (excl. VAT)'),
    ]

    estimate = models.ForeignKey(
        Estimate,
        on_delete=models.CASCADE,
        related_name='proforma_invoices',
    )
    proforma_number = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    charge_type = models.CharField(max_length=20, choices=CHARGE_TYPE_CHOICES)
    charge_value = models.DecimalField(max_digits=15, decimal_places=2)
    line_subtotal = models.DecimalField(max_digits=15, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='estimate_proforma_invoices_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.proforma_number

    @classmethod
    def allocate_number(cls, estimate) -> str:
        seq = cls.objects.filter(estimate=estimate).count() + 1
        return f'PI-{estimate.display_estimate_number}-{seq:02d}'


class EstimateItem(models.Model):
    """
    Line items for estimates.
    Supports both VAT-exclusive and VAT-inclusive pricing.
    
    VAT LOGIC (Tax Code Driven):
    - tax_code FK is the source of truth for VAT
    - vat_rate is computed from tax_code.rate (read-only, for display)
    - No tax_code = Out of Scope (0% VAT)
    """
    estimate = models.ForeignKey(
        Estimate, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    group_name = models.CharField(max_length=200, blank=True, help_text='Section / group heading')
    group_qty_multiplier = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text='Multiplied with line qty for all items sharing this group name.',
    )
    sort_order = models.PositiveIntegerField(default=0)
    inventory_item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='estimate_lines',
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_price = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text='Base price per unit (before profit).',
    )
    PROFIT_TYPE_CHOICES = [
        ('none', 'None'),
        ('percent', 'Percent'),
        ('amount', 'Amount'),
    ]
    profit_type = models.CharField(max_length=20, choices=PROFIT_TYPE_CHOICES, default='none')
    profit_value = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Per unit: % markup on base, or AED added to base (not total for the whole line).',
    )
    rate = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        help_text='Selling price per unit after profit: Base + profit (AED) or Base × (1 + profit%).',
    )
    
    # Tax Code - source of truth for VAT (SAP/Oracle Standard)
    tax_code = models.ForeignKey(
        'finance.TaxCode',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='estimate_items',
        help_text='Tax Code determines VAT rate. No selection = Out of Scope (0%)'
    )
    
    # Computed VAT rate from tax_code (read-only, for display/reporting)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    is_vat_inclusive = models.BooleanField(default=False, help_text='If true, rate includes VAT')
    
    # Calculated
    total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['sort_order', 'id']
    
    def __str__(self):
        return f"{self.description} - {self.quantity}"

    @property
    def effective_quantity(self):
        mult = self.group_qty_multiplier if self.group_qty_multiplier else Decimal('1')
        return (self.quantity * mult).quantize(Decimal('0.01'))

    def compute_rate(self):
        """
        Unit selling price after profit (per unit).
        - none: rate = base
        - percent: rate = base × (1 + profit% / 100)  e.g. base 10 + 100% → 20
        - amount: rate = base + profit (AED per unit)  e.g. base 10 + 100 AED → 110
        """
        base = self.unit_price or Decimal('0')
        pv = self.profit_value or Decimal('0')
        if self.profit_type == 'percent':
            return (base * (Decimal('1') + pv / Decimal('100'))).quantize(Decimal('0.01'))
        if self.profit_type == 'amount':
            return (base + pv).quantize(Decimal('0.01'))
        return base.quantize(Decimal('0.01'))
    
    def save(self, *args, **kwargs):
        self.rate = self.compute_rate()
        # Derive VAT rate from Tax Code (No Tax Code = 0%)
        if self.tax_code:
            self.vat_rate = self.tax_code.rate
        else:
            self.vat_rate = Decimal('0.00')
        
        gross = self.quantity * self.rate
        
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
    estimate = models.ForeignKey(
        Estimate, 
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

