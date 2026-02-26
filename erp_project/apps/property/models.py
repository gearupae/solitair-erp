"""
Property Management Models - PDC & Bank Reconciliation
Enterprise-grade handling of Post-Dated Cheques with proper accounting integration.

Key Features:
- Composite uniqueness for cheque identification
- PDC Control Account handling
- Ambiguous match detection in bank reconciliation
- Manual allocation for multiple PDC matching
- Cheque bounce handling with full audit trail
"""
from django.db import models
from django.db.models import Sum, Q
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from datetime import date
from apps.core.models import BaseModel
from apps.core.utils import generate_number


class Property(BaseModel):
    """
    Property/Building for rental management.
    """
    property_number = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100, default='Dubai')
    emirate = models.CharField(max_length=50, default='Dubai')
    country = models.CharField(max_length=100, default='United Arab Emirates')
    property_type = models.CharField(max_length=50, choices=[
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('mixed', 'Mixed Use'),
        ('industrial', 'Industrial'),
    ], default='residential')
    total_units = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    
    # Accounting
    ar_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.PROTECT,
        related_name='property_ar',
        null=True, blank=True,
        help_text='Trade Debtors - Property Account'
    )
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Properties'
    
    def __str__(self):
        return f"{self.property_number} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.property_number:
            self.property_number = generate_number('PROP', Property, 'property_number')
        super().save(*args, **kwargs)


class Unit(BaseModel):
    """
    Individual unit within a property.
    """
    unit_number = models.CharField(max_length=50)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='units')
    unit_type = models.CharField(max_length=50, choices=[
        ('apartment', 'Apartment'),
        ('villa', 'Villa'),
        ('office', 'Office'),
        ('shop', 'Shop/Retail'),
        ('warehouse', 'Warehouse'),
        ('parking', 'Parking'),
        ('storage', 'Storage'),
    ], default='apartment')
    floor = models.CharField(max_length=20, blank=True)
    area_sqft = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bedrooms = models.PositiveIntegerField(default=0)
    bathrooms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=[
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('maintenance', 'Under Maintenance'),
        ('reserved', 'Reserved'),
    ], default='available')
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    class Meta:
        ordering = ['property', 'unit_number']
        unique_together = ['property', 'unit_number']
    
    def __str__(self):
        return f"{self.property.name} - {self.unit_number}"


class Tenant(BaseModel):
    """
    Tenant for property rental.
    Links to CRM Customer for unified customer management.
    """
    tenant_number = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    mobile = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=200, blank=True)
    
    # Emirates ID / Trade License
    emirates_id = models.CharField(max_length=20, blank=True)
    trade_license = models.CharField(max_length=50, blank=True)
    trn = models.CharField(max_length=20, blank=True, verbose_name='Tax Registration Number')
    
    # Address
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, default='Dubai')
    country = models.CharField(max_length=100, default='United Arab Emirates')
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('blacklisted', 'Blacklisted'),
    ], default='active')
    
    # Accounting - Tenant-specific AR sub-account
    ar_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='tenant_ar',
        help_text='Tenant-specific Trade Debtors account'
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.tenant_number} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.tenant_number:
            self.tenant_number = generate_number('TEN', Tenant, 'tenant_number')
        super().save(*args, **kwargs)
    
    @property
    def outstanding_balance(self):
        """Calculate total outstanding balance for this tenant."""
        from apps.finance.models import JournalEntryLine
        if not self.ar_account:
            return Decimal('0.00')
        balance = JournalEntryLine.objects.filter(
            account=self.ar_account,
            journal_entry__status='posted'
        ).aggregate(
            total=Sum('debit') - Sum('credit')
        )['total'] or Decimal('0.00')
        return balance


class Lease(BaseModel):
    """
    Lease/Tenancy contract.
    """
    lease_number = models.CharField(max_length=50, unique=True, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='leases', null=True, blank=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='leases')
    
    # Lease period
    start_date = models.DateField()
    end_date = models.DateField()
    
    # Rent details
    annual_rent = models.DecimalField(max_digits=12, decimal_places=2)
    payment_frequency = models.CharField(max_length=20, choices=[
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-Annual'),
        ('annual', 'Annual'),
    ], default='monthly')
    number_of_cheques = models.PositiveIntegerField(default=12)
    
    # Security deposit
    security_deposit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deposit_paid = models.BooleanField(default=False)
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('terminated', 'Terminated'),
        ('renewed', 'Renewed'),
    ], default='draft')
    
    # Ejari (UAE rental registration)
    ejari_number = models.CharField(max_length=50, blank=True)
    ejari_registered = models.BooleanField(default=False)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-start_date']
    
    def __str__(self):
        return f"{self.lease_number} - {self.tenant.name}"
    
    def save(self, *args, **kwargs):
        if not self.lease_number:
            self.lease_number = generate_number('LEASE', Lease, 'lease_number')
        super().save(*args, **kwargs)
    
    @property
    def monthly_rent(self):
        """Calculate monthly rent amount."""
        return self.annual_rent / 12
    
    @property
    def payment_amount(self):
        """Calculate amount per payment based on frequency."""
        if self.payment_frequency == 'monthly':
            return self.annual_rent / 12
        elif self.payment_frequency == 'quarterly':
            return self.annual_rent / 4
        elif self.payment_frequency == 'semi_annual':
            return self.annual_rent / 2
        else:  # annual
            return self.annual_rent
    
    @property
    def num_cheques(self):
        """Alias for number_of_cheques."""
        return self.number_of_cheques
    
    @property
    def days_until_expiry(self):
        """Calculate days until lease expires."""
        if self.end_date:
            delta = self.end_date - date.today()
            return delta.days if delta.days >= 0 else None
        return None
    
    @property
    def lease_type(self):
        """Get lease type from unit type."""
        if self.unit:
            if self.unit.unit_type in ['apartment', 'villa']:
                return 'residential'
            else:
                return 'commercial'
        return 'residential'


class PDCCheque(BaseModel):
    """
    Post-Dated Cheque (PDC) with composite uniqueness.
    
    UNIQUE IDENTIFICATION (Composite):
    - Cheque Number
    - Bank Name
    - Cheque Date
    - Amount
    - Tenant ID
    
    This allows same cheque number/amount/bank for DIFFERENT tenants.
    """
    STATUS_CHOICES = [
        ('received', 'Received'),
        ('deposited', 'Deposited'),
        ('cleared', 'Cleared'),
        ('bounced', 'Bounced'),
        ('returned', 'Returned to Tenant'),
        ('replaced', 'Replaced'),
        ('cancelled', 'Cancelled'),
    ]
    
    DEPOSIT_STATUS_CHOICES = [
        ('pending', 'Pending Deposit'),
        ('in_clearing', 'In Clearing'),
        ('cleared', 'Cleared'),
        ('bounced', 'Bounced'),
    ]
    
    pdc_number = models.CharField(max_length=50, unique=True, editable=False)
    
    # Cheque details - composite uniqueness
    cheque_number = models.CharField(max_length=50)
    bank_name = models.CharField(max_length=200)
    cheque_date = models.DateField(help_text='Post-dated cheque date')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='pdc_cheques')
    
    # Additional cheque info
    drawer_name = models.CharField(max_length=200, blank=True, help_text='Name on cheque')
    drawer_account = models.CharField(max_length=50, blank=True)
    
    # Link to lease
    lease = models.ForeignKey(Lease, on_delete=models.SET_NULL, null=True, blank=True, related_name='pdc_cheques')
    
    # Purpose
    purpose = models.CharField(max_length=50, choices=[
        ('rent', 'Rent Payment'),
        ('security_deposit', 'Security Deposit'),
        ('maintenance', 'Maintenance Fee'),
        ('other', 'Other'),
    ], default='rent')
    payment_period_start = models.DateField(null=True, blank=True, help_text='Rent period start date')
    payment_period_end = models.DateField(null=True, blank=True, help_text='Rent period end date')
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    deposit_status = models.CharField(max_length=20, choices=DEPOSIT_STATUS_CHOICES, default='pending')
    
    # Receipt details
    received_date = models.DateField(default=date.today)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='received_pdcs'
    )
    
    # Deposit details
    deposited_date = models.DateField(null=True, blank=True)
    deposited_to_bank = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deposited_pdcs'
    )
    deposited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deposited_pdcs'
    )
    
    # Clearing details
    cleared_date = models.DateField(null=True, blank=True)
    clearing_reference = models.CharField(max_length=100, blank=True)
    
    # Accounting
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pdc_cheques',
        help_text='Journal entry on clearing'
    )
    pdc_control_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pdc_control_entries',
        help_text='Journal entry for PDC Control on deposit'
    )
    
    # Bounce details
    bounce_date = models.DateField(null=True, blank=True)
    bounce_reason = models.CharField(max_length=200, blank=True)
    bounce_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bounce_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='bounced_pdcs'
    )
    
    # Replacement tracking
    replaced_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='replaces'
    )
    
    # Bank reconciliation
    bank_statement_line = models.ForeignKey(
        'finance.BankStatementLine',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='matched_pdcs'
    )
    reconciled = models.BooleanField(default=False)
    reconciled_date = models.DateField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reconciled_pdcs'
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['cheque_date']
        # Composite uniqueness - allows same cheque number for different tenants
        constraints = [
            models.UniqueConstraint(
                fields=['cheque_number', 'bank_name', 'cheque_date', 'amount', 'tenant'],
                name='unique_pdc_identification'
            )
        ]
    
    def __str__(self):
        return f"PDC {self.pdc_number} - {self.cheque_number} ({self.tenant.name})"
    
    def save(self, *args, **kwargs):
        if not self.pdc_number:
            self.pdc_number = generate_number('PDC', PDCCheque, 'pdc_number')
        super().save(*args, **kwargs)
    
    def clean(self):
        """Validate PDC before saving."""
        # Cheque date should not be in the past for new PDCs
        if not self.pk and self.cheque_date and self.cheque_date < date.today():
            raise ValidationError({'cheque_date': 'Post-dated cheque date cannot be in the past.'})
        
        # Amount must be positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'Amount must be positive.'})
    
    def post_received_journal(self, user):
        """
        Post journal when PDC is received from tenant.
        Immediately recognizes the cheque as a current asset and clears AR.

        Journal Entry:
        Dr PDC Receivable (1210)
        Cr Trade Debtors / Tenant AR
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.pdc_control_journal:
            raise ValidationError("Receipt journal already exists for this PDC.")

        FiscalYear.validate_posting_allowed(self.received_date or date.today())

        pdc_receivable = AccountMapping.get_account_or_default('pdc_control', '1210')
        if not pdc_receivable:
            raise ValidationError(
                "PDC Receivable account not configured. "
                "Expected account 1210 or set up 'pdc_control' in Finance → Account Mapping."
            )

        ar_account = self.tenant.ar_account
        if not ar_account:
            raise ValidationError(f'Tenant {self.tenant.name} does not have AR account configured.')

        journal = JournalEntry.objects.create(
            date=self.received_date or date.today(),
            reference=f"PDC Received - {self.cheque_number}",
            description=f"PDC received from {self.tenant.name} - Cheque: {self.cheque_number}",
            source_module='pdc',
            entry_type='standard',
            status='draft',
            created_by=user,
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=pdc_receivable,
            debit=self.amount,
            credit=Decimal('0.00'),
            description=f"PDC {self.cheque_number} from {self.tenant.name}",
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            debit=Decimal('0.00'),
            credit=self.amount,
            description=f"AR cleared by PDC {self.cheque_number}",
        )

        journal.calculate_totals()
        journal.post(user)

        self.pdc_control_journal = journal
        self.save(update_fields=['pdc_control_journal'])

        return journal

    def deposit(self, bank_account, user, deposit_date=None):
        """
        Submit PDC to bank for clearing.
        Status change only — the GL already recognized the PDC asset on receipt.
        """
        if self.status != 'received':
            raise ValidationError('Only received PDCs can be deposited.')

        if not deposit_date:
            deposit_date = date.today()

        self.status = 'deposited'
        self.deposit_status = 'in_clearing'
        self.deposited_date = deposit_date
        self.deposited_to_bank = bank_account
        self.deposited_by = user
        self.save()
    
    def clear(self, user, clearing_date=None, clearing_reference=''):
        """
        Mark PDC as cleared in bank.
        Converts PDC Receivable asset to cash.

        Journal Entry:
        Dr Bank
        Cr PDC Receivable (1210)
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.status != 'deposited' or self.deposit_status != 'in_clearing':
            raise ValidationError('Only deposited PDCs in clearing can be cleared.')

        if not clearing_date:
            clearing_date = date.today()

        FiscalYear.validate_posting_allowed(clearing_date)

        pdc_receivable = AccountMapping.get_account_or_default('pdc_control', '1210')
        if not pdc_receivable:
            raise ValidationError(
                "PDC Receivable account not configured. "
                "Expected account 1210 or set up 'pdc_control' in Finance → Account Mapping."
            )

        bank_account = self.deposited_to_bank
        if not bank_account or not bank_account.gl_account:
            raise ValidationError('Bank account not configured for this PDC.')

        journal = JournalEntry.objects.create(
            date=clearing_date,
            reference=f"PDC Cleared - {self.cheque_number}",
            description=f"PDC cleared for {self.tenant.name} - Cheque: {self.cheque_number}",
            source_module='pdc',
            entry_type='standard',
            status='draft',
            created_by=user,
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account.gl_account,
            debit=self.amount,
            credit=Decimal('0.00'),
            description=f"PDC {self.cheque_number} cleared",
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=pdc_receivable,
            debit=Decimal('0.00'),
            credit=self.amount,
            description=f"PDC {self.cheque_number} cleared from receivable",
        )

        journal.calculate_totals()
        journal.post(user)

        self.status = 'cleared'
        self.deposit_status = 'cleared'
        self.cleared_date = clearing_date
        self.clearing_reference = clearing_reference
        self.journal_entry = journal
        self.save()

        return journal
    
    def bounce(self, user, bounce_date=None, bounce_reason='', bounce_charges=Decimal('0.00')):
        """
        Mark PDC as bounced. Reverses the receipt entry and, if cleared, the clearing entry.

        Net effect:
        - If deposited (not yet cleared): Dr Tenant AR, Cr PDC Receivable (1210)
        - If cleared: Dr Tenant AR, Cr Bank

        Optional bounce charges: Dr Bounce Expense (6800), Cr Tenant AR
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account, AccountMapping, FiscalYear

        if self.status not in ['deposited', 'cleared']:
            raise ValidationError('Only deposited or cleared PDCs can bounce.')

        if not bounce_date:
            bounce_date = date.today()

        FiscalYear.validate_posting_allowed(bounce_date)

        ar_account = self.tenant.ar_account
        if not ar_account:
            raise ValidationError(f'Tenant {self.tenant.name} does not have AR account configured.')

        if self.status == 'cleared':
            credit_account = self.deposited_to_bank.gl_account
        else:
            pdc_receivable = AccountMapping.get_account_or_default('pdc_control', '1210')
            if not pdc_receivable:
                raise ValidationError(
                    "PDC Receivable account not configured. "
                    "Expected account 1210 or set up 'pdc_control' in Finance → Account Mapping."
                )
            credit_account = pdc_receivable

        journal = JournalEntry.objects.create(
            date=bounce_date,
            reference=f"PDC Bounce - {self.cheque_number}",
            description=f"Cheque bounced for {self.tenant.name} - Reason: {bounce_reason}",
            source_module='pdc',
            entry_type='reversal',
            status='draft',
            created_by=user,
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            debit=self.amount,
            credit=Decimal('0.00'),
            description=f"PDC {self.cheque_number} bounced - AR restored",
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=credit_account,
            debit=Decimal('0.00'),
            credit=self.amount,
            description=f"PDC {self.cheque_number} bounced",
        )

        if bounce_charges > 0:
            try:
                bounce_expense = Account.objects.get(code='6800', account_type='expense')
            except Account.DoesNotExist:
                raise ValidationError(
                    "Bounce Charges Expense account (6800) not found. "
                    "Create the account before processing bounced cheques."
                )

            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=bounce_expense,
                debit=bounce_charges,
                credit=Decimal('0.00'),
                description=f"Bounce charges for {self.cheque_number}",
            )

            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=ar_account,
                debit=Decimal('0.00'),
                credit=bounce_charges,
                description=f"Bounce charges billed to tenant",
            )

        journal.calculate_totals()
        journal.post(user)

        self.status = 'bounced'
        self.deposit_status = 'bounced'
        self.bounce_date = bounce_date
        self.bounce_reason = bounce_reason
        self.bounce_charges = bounce_charges
        self.bounce_journal = journal
        self.reconciled = False
        self.save()

        return journal


class PDCBankMatch(BaseModel):
    """
    Tracks potential matches between bank statement lines and PDCs.
    Used for identifying ambiguous matches requiring manual allocation.
    """
    MATCH_STATUS_CHOICES = [
        ('potential', 'Potential Match'),
        ('ambiguous', 'Ambiguous - Multiple Matches'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ]
    
    bank_statement_line = models.ForeignKey(
        'finance.BankStatementLine',
        on_delete=models.CASCADE,
        related_name='pdc_matches'
    )
    pdc = models.ForeignKey(PDCCheque, on_delete=models.CASCADE, related_name='bank_matches')
    
    match_status = models.CharField(max_length=20, choices=MATCH_STATUS_CHOICES, default='potential')
    match_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, 
                                       help_text='Match confidence score (0-100)')
    
    # Match criteria flags
    amount_matched = models.BooleanField(default=False)
    date_matched = models.BooleanField(default=False)
    cheque_number_matched = models.BooleanField(default=False)
    bank_matched = models.BooleanField(default=False)
    
    # Manual allocation
    allocated_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pdc_allocations'
    )
    allocated_at = models.DateTimeField(null=True, blank=True)
    allocation_reason = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-match_score']
        unique_together = ['bank_statement_line', 'pdc']
    
    def __str__(self):
        return f"Match: {self.bank_statement_line} <-> {self.pdc}"


class PDCAllocation(BaseModel):
    """
    Records manual allocation of a bank statement line to multiple PDCs.
    Required when one bank transaction matches multiple PDCs.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('reversed', 'Reversed'),
    ]
    
    allocation_number = models.CharField(max_length=50, unique=True, editable=False)
    bank_statement_line = models.ForeignKey(
        'finance.BankStatementLine',
        on_delete=models.PROTECT,
        related_name='pdc_allocations'
    )
    
    allocation_date = models.DateField(default=date.today)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Audit
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_pdc_allocations'
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='confirmed_pdc_allocations'
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    
    reason = models.TextField(blank=True, help_text='Reason for manual allocation')
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-allocation_date']
    
    def __str__(self):
        return f"Allocation {self.allocation_number}"
    
    def save(self, *args, **kwargs):
        if not self.allocation_number:
            self.allocation_number = generate_number('ALLOC', PDCAllocation, 'allocation_number')
        super().save(*args, **kwargs)
    
    def confirm(self, user):
        """
        Confirm allocation and mark all related PDCs as reconciled.
        """
        if self.status != 'draft':
            raise ValidationError('Only draft allocations can be confirmed.')
        
        # Validate total allocation matches bank line
        total_allocated = self.lines.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        if total_allocated != self.total_amount:
            raise ValidationError(f'Total allocated ({total_allocated}) does not match bank line ({self.total_amount})')
        
        # Mark all PDCs as reconciled
        for line in self.lines.all():
            pdc = line.pdc
            pdc.reconciled = True
            pdc.reconciled_date = date.today()
            pdc.reconciled_by = user
            pdc.bank_statement_line = self.bank_statement_line
            
            # Clear PDC if not already cleared
            if pdc.status == 'deposited' and pdc.deposit_status == 'in_clearing':
                pdc.clear(user, clearing_date=self.allocation_date)
            
            pdc.save()
        
        # Update bank statement line
        self.bank_statement_line.reconciliation_status = 'matched'
        self.bank_statement_line.match_method = 'manual'
        self.bank_statement_line.save()
        
        # Update allocation
        self.status = 'confirmed'
        self.confirmed_by = user
        self.confirmed_at = timezone.now()
        self.save()


class PDCAllocationLine(models.Model):
    """
    Individual line in a PDC allocation.
    """
    allocation = models.ForeignKey(PDCAllocation, on_delete=models.CASCADE, related_name='lines')
    pdc = models.ForeignKey(PDCCheque, on_delete=models.PROTECT, related_name='allocation_lines')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.CharField(max_length=200, blank=True)
    
    class Meta:
        unique_together = ['allocation', 'pdc']
    
    def __str__(self):
        return f"{self.allocation} - {self.pdc}: {self.amount}"


class AmbiguousMatchLog(BaseModel):
    """
    Audit log for ambiguous matches detected during bank reconciliation.
    No hard delete - maintains full audit trail.
    """
    RESOLUTION_CHOICES = [
        ('pending', 'Pending Resolution'),
        ('allocated', 'Manually Allocated'),
        ('rejected', 'Rejected'),
        ('auto_resolved', 'Auto-Resolved'),
    ]
    
    bank_statement_line = models.ForeignKey(
        'finance.BankStatementLine',
        on_delete=models.PROTECT,
        related_name='ambiguous_match_logs'
    )
    
    detected_at = models.DateTimeField(auto_now_add=True)
    detected_by_system = models.BooleanField(default=True)
    
    # Matching PDCs (stored as JSON for audit)
    matching_pdc_ids = models.JSONField(default=list)
    match_criteria = models.JSONField(default=dict, help_text='Criteria used for matching')
    
    # Resolution
    resolution_status = models.CharField(max_length=20, choices=RESOLUTION_CHOICES, default='pending')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='resolved_ambiguous_matches'
    )
    resolution_notes = models.TextField(blank=True)
    
    # Link to allocation if manually allocated
    allocation = models.ForeignKey(
        PDCAllocation,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='ambiguous_match_logs'
    )
    
    class Meta:
        ordering = ['-detected_at']
    
    def __str__(self):
        return f"Ambiguous Match - {self.bank_statement_line} ({len(self.matching_pdc_ids)} PDCs)"


class PDCRegisterEntry(models.Model):
    """
    View/Report model for PDC Register.
    This is a database view for reporting purposes.
    """
    class Meta:
        managed = False
        db_table = 'property_pdc_register_view'


class RentInvoice(BaseModel):
    """
    Rent Invoice for Property Management.
    Auto-posts to accounting on approval:
    
    Journal Entry:
    Dr Accounts Receivable - Tenant
    Cr Rental Income
    Cr VAT Payable (if taxable property - commercial)
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('cancelled', 'Cancelled'),
    ]
    
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='rent_invoices')
    lease = models.ForeignKey(Lease, on_delete=models.SET_NULL, null=True, blank=True, related_name='rent_invoices')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name='rent_invoices')
    
    # Invoice details
    invoice_date = models.DateField()
    due_date = models.DateField()
    period_start = models.DateField(help_text='Rent period start')
    period_end = models.DateField(help_text='Rent period end')
    
    # Amounts
    rent_amount = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'),
                                   help_text='VAT rate (0% for residential, 5% for commercial)')
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Accounting
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rent_invoices'
    )
    
    # Linked PDC
    pdc = models.ForeignKey(
        PDCCheque,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rent_invoices'
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-invoice_date', '-created_at']
    
    def __str__(self):
        return f"{self.invoice_number} - {self.tenant.name}"
    
    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = generate_number('RENT-INV', RentInvoice, 'invoice_number')
        # Calculate totals
        self.vat_amount = self.rent_amount * (self.vat_rate / 100)
        self.total_amount = self.rent_amount + self.vat_amount
        super().save(*args, **kwargs)
    
    @property
    def balance(self):
        return self.total_amount - self.paid_amount
    
    def post_to_accounting(self, user=None):
        """
        Post rent invoice to accounting.
        
        Journal Entry:
        Dr Accounts Receivable - Tenant (total amount)
        Cr Rental Income (rent amount)
        Cr VAT Payable (vat amount, if applicable)
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account, AccountMapping, FiscalYear

        if self.status != 'draft':
            raise ValidationError('Only draft invoices can be posted.')

        FiscalYear.validate_posting_allowed(self.invoice_date)

        if self.total_amount <= 0:
            raise ValidationError('Invoice amount must be greater than zero.')
        
        # Get AR account (tenant-specific or default)
        ar_account = self.tenant.ar_account
        if not ar_account:
            try:
                ar_account = AccountMapping.objects.get(transaction_type='trade_debtors_property').account
            except AccountMapping.DoesNotExist:
                raise ValidationError(
                    "Trade Debtors (Property) account not configured. "
                    "Set tenant AR account or configure 'trade_debtors_property' in Account Mapping."
                )

        rental_income = AccountMapping.get_account_or_default('rental_income', '4200')
        if not rental_income:
            raise ValidationError(
                "Rental Income account not configured. "
                "Expected account 4200 or set up 'rental_income' in Finance → Account Mapping."
            )
        
        # Get VAT Payable account (if applicable)
        vat_account = None
        if self.vat_amount > 0:
            try:
                vat_account = AccountMapping.objects.get(transaction_type='vat_output').account
            except AccountMapping.DoesNotExist:
                vat_account = Account.objects.filter(
                    account_type='liability', name__icontains='vat'
                ).first()
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.invoice_date,
            reference=self.invoice_number,
            description=f"Rent Invoice: {self.invoice_number} - {self.tenant.name}",
            source_module='property',
            entry_type='standard',
            status='draft',
            created_by=user
        )
        
        # Dr Accounts Receivable
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            debit=self.total_amount,
            credit=Decimal('0.00'),
            description=f"Rent - {self.tenant.name} ({self.period_start} to {self.period_end})"
        )
        
        # Cr Rental Income
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=rental_income,
            debit=Decimal('0.00'),
            credit=self.rent_amount,
            description=f"Rental Income - {self.unit.property.name if self.unit else 'N/A'}"
        )
        
        # Cr VAT Payable (if applicable)
        if self.vat_amount > 0 and vat_account:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_account,
                debit=Decimal('0.00'),
                credit=self.vat_amount,
                description=f"VAT Output - Rent {self.invoice_number}"
            )
        
        # Post journal
        journal.status = 'posted'
        if user:
            journal.posted_by = user
        journal.posted_at = timezone.now()
        journal.save()
        
        # Update account balances
        ar_account.balance += self.total_amount
        ar_account.save()
        rental_income.balance -= self.rent_amount  # Credit increases income
        rental_income.save()
        if vat_account and self.vat_amount > 0:
            vat_account.balance -= self.vat_amount  # Credit increases liability
            vat_account.save()
        
        # Update invoice
        self.journal_entry = journal
        self.status = 'posted'
        self.save()
        
        return journal


class SecurityDeposit(BaseModel):
    """
    Security Deposit for Lease.
    NOT income - recorded as Liability.
    
    On Receipt:
    Dr Bank
    Cr Security Deposit Liability
    
    On Refund:
    Dr Security Deposit Liability
    Cr Bank
    
    On Forfeit (deductions):
    Dr Security Deposit Liability
    Cr Other Income (forfeited portion)
    Cr Bank (refunded portion)
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('received', 'Received'),
        ('partially_refunded', 'Partially Refunded'),
        ('refunded', 'Fully Refunded'),
        ('forfeited', 'Forfeited'),
    ]
    
    deposit_number = models.CharField(max_length=50, unique=True, editable=False)
    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name='security_deposits')
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='security_deposits')
    
    # Amounts
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    received_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    refunded_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    forfeited_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Dates
    received_date = models.DateField(null=True, blank=True)
    refund_date = models.DateField(null=True, blank=True)
    
    # Bank account
    bank_account = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Accounting
    receipt_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deposit_receipts'
    )
    refund_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deposit_refunds'
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.deposit_number} - {self.tenant.name}"
    
    def save(self, *args, **kwargs):
        if not self.deposit_number:
            self.deposit_number = generate_number('SD', SecurityDeposit, 'deposit_number')
        super().save(*args, **kwargs)
    
    @property
    def balance(self):
        """Outstanding deposit balance."""
        return self.received_amount - self.refunded_amount - self.forfeited_amount
    
    def receive(self, bank_account, user, receive_date=None, amount=None):
        """
        Record receipt of security deposit.
        
        Journal Entry:
        Dr Bank
        Cr Security Deposit Liability
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account
        
        if self.status != 'pending':
            raise ValidationError('Only pending deposits can be received.')
        
        receive_date = receive_date or date.today()
        amount = amount or self.amount
        
        # Get Security Deposit Liability account
        deposit_liability = Account.objects.filter(
            account_type='liability',
            name__icontains='security deposit'
        ).first()
        if not deposit_liability:
            deposit_liability = Account.objects.filter(
                account_type='liability',
                name__icontains='deposit'
            ).first()
        if not deposit_liability:
            raise ValidationError('Security Deposit Liability account not configured.')
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=receive_date,
            reference=self.deposit_number,
            description=f"Security Deposit Received - {self.tenant.name}",
            source_module='property',
            entry_type='standard',
            status='draft',
            created_by=user
        )
        
        # Dr Bank
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account.gl_account,
            debit=amount,
            credit=Decimal('0.00'),
            description=f"Security Deposit - {self.tenant.name}"
        )
        
        # Cr Security Deposit Liability
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=deposit_liability,
            debit=Decimal('0.00'),
            credit=amount,
            description=f"Security Deposit Liability - {self.lease.lease_number}"
        )
        
        # Post journal
        journal.status = 'posted'
        journal.posted_by = user
        journal.posted_at = timezone.now()
        journal.save()
        
        # Update account balances
        bank_account.gl_account.balance += amount
        bank_account.gl_account.save()
        deposit_liability.balance -= amount  # Credit increases liability
        deposit_liability.save()
        
        # Update deposit record
        self.received_amount = amount
        self.received_date = receive_date
        self.bank_account = bank_account
        self.receipt_journal = journal
        self.status = 'received'
        self.save()
        
        # Update lease
        self.lease.deposit_paid = True
        self.lease.save()
        
        return journal
    
    def refund(self, user, refund_date=None, refund_amount=None, forfeit_amount=Decimal('0.00'), reason=''):
        """
        Refund security deposit (full or partial).
        
        Journal Entry:
        Dr Security Deposit Liability (full amount)
        Cr Bank (refund amount)
        Cr Other Income (forfeited amount, if any)
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account
        
        if self.status not in ['received', 'partially_refunded']:
            raise ValidationError('Only received deposits can be refunded.')
        
        refund_date = refund_date or date.today()
        refund_amount = refund_amount or self.balance
        
        if refund_amount + forfeit_amount > self.balance:
            raise ValidationError('Refund + forfeit cannot exceed remaining balance.')
        
        # Get accounts
        deposit_liability = Account.objects.filter(
            account_type='liability',
            name__icontains='security deposit'
        ).first()
        if not deposit_liability:
            deposit_liability = Account.objects.filter(
                account_type='liability',
                name__icontains='deposit'
            ).first()
        
        forfeit_income = None
        if forfeit_amount > 0:
            forfeit_income = Account.objects.filter(
                account_type='income',
                name__icontains='forfeit'
            ).first()
            if not forfeit_income:
                forfeit_income = Account.objects.filter(
                    account_type='income',
                    name__icontains='other'
                ).first()
        
        if not self.bank_account:
            raise ValidationError('No bank account associated with this deposit.')
        
        # Create journal entry
        total_return = refund_amount + forfeit_amount
        journal = JournalEntry.objects.create(
            date=refund_date,
            reference=f"{self.deposit_number}-REF",
            description=f"Security Deposit Refund - {self.tenant.name}",
            source_module='property',
            entry_type='standard',
            status='draft',
            created_by=user
        )
        
        # Dr Security Deposit Liability
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=deposit_liability,
            debit=total_return,
            credit=Decimal('0.00'),
            description=f"Security Deposit Released - {self.lease.lease_number}"
        )
        
        # Cr Bank (refund)
        if refund_amount > 0:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=self.bank_account.gl_account,
                debit=Decimal('0.00'),
                credit=refund_amount,
                description=f"Security Deposit Refund to {self.tenant.name}"
            )
        
        # Cr Other Income (forfeit)
        if forfeit_amount > 0 and forfeit_income:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=forfeit_income,
                debit=Decimal('0.00'),
                credit=forfeit_amount,
                description=f"Security Deposit Forfeited - {reason}"
            )
        
        # Post journal
        journal.status = 'posted'
        journal.posted_by = user
        journal.posted_at = timezone.now()
        journal.save()
        
        # Update account balances
        deposit_liability.balance += total_return  # Debit decreases liability
        deposit_liability.save()
        if refund_amount > 0:
            self.bank_account.gl_account.balance -= refund_amount
            self.bank_account.gl_account.save()
        if forfeit_amount > 0 and forfeit_income:
            forfeit_income.balance -= forfeit_amount  # Credit increases income
            forfeit_income.save()
        
        # Update deposit record
        self.refunded_amount += refund_amount
        self.forfeited_amount += forfeit_amount
        self.refund_date = refund_date
        self.refund_journal = journal
        
        if self.balance == 0:
            if self.forfeited_amount > 0:
                self.status = 'forfeited'
            else:
                self.status = 'refunded'
        else:
            self.status = 'partially_refunded'
        
        self.save()
        
        return journal

