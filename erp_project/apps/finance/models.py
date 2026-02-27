"""
Finance Models - UAE VAT & Corporate Tax Compliant
Double-entry accounting with IFRS-based reporting

Compliance:
- UAE VAT Law (Federal Decree-Law No. 8 of 2017)
- UAE Corporate Tax Law (Federal Decree-Law No. 47 of 2022)
- IFRS-based financial reporting
- Accrual accounting
"""
from django.db import models
from django.db.models import Sum
from django.conf import settings
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import date
from apps.core.models import BaseModel
from apps.core.utils import generate_number


class AccountType(models.TextChoices):
    """Account types for Chart of Accounts."""
    ASSET = 'asset', 'Asset'
    LIABILITY = 'liability', 'Liability'
    EQUITY = 'equity', 'Equity'
    INCOME = 'income', 'Income'
    EXPENSE = 'expense', 'Expense'


class AccountCategory(models.TextChoices):
    """Account categories for Trial Balance & Financial Statement grouping."""
    # Assets
    CASH_BANK = 'cash_bank', 'Cash & Bank'
    TRADE_RECEIVABLES = 'trade_receivables', 'Trade Receivables'
    TAX_RECEIVABLES = 'tax_receivables', 'Taxes & Statutory Receivables'
    INVENTORY = 'inventory', 'Inventory'
    PREPAID = 'prepaid', 'Prepaid Expenses'
    OTHER_CURRENT_ASSETS = 'other_current_assets', 'Other Current Assets'
    FIXED_ASSETS_FURNITURE = 'fixed_furniture', 'Furniture & Fixtures'
    FIXED_ASSETS_IT = 'fixed_it', 'IT Equipment'
    FIXED_ASSETS_VEHICLES = 'fixed_vehicles', 'Vehicles'
    FIXED_ASSETS_OTHER = 'fixed_other', 'Other Fixed Assets'
    ACCUMULATED_DEPRECIATION = 'accum_depreciation', 'Accumulated Depreciation'
    INTANGIBLE_ASSETS = 'intangible', 'Intangible Assets'
    
    # Liabilities
    TRADE_PAYABLES = 'trade_payables', 'Trade Payables'
    TAX_PAYABLES = 'tax_payables', 'Taxes Payable'
    ACCRUED_LIABILITIES = 'accrued_liabilities', 'Accrued Liabilities'
    OTHER_CURRENT_LIABILITIES = 'other_current_liabilities', 'Other Current Liabilities'
    LONG_TERM_LIABILITIES = 'long_term_liabilities', 'Long Term Liabilities'
    
    # Equity
    CAPITAL = 'capital', 'Capital Accounts'
    RESERVES = 'reserves', 'Reserves & Surplus'
    RETAINED_EARNINGS = 'retained_earnings', 'Retained Earnings'
    
    # Income
    OPERATING_REVENUE = 'operating_revenue', 'Operating Revenue'
    OTHER_INCOME = 'other_income', 'Other Income'
    
    # Expenses
    COST_OF_SALES = 'cost_of_sales', 'Cost of Sales'
    RENT_EXPENSE = 'rent_expense', 'Rent Expenses'
    SALARY_EXPENSE = 'salary_expense', 'Salary & Staff Costs'
    BANKING_EXPENSE = 'banking_expense', 'Banking Expenses'
    BAD_DEBTS = 'bad_debts', 'Bad Debts'
    DEPRECIATION_EXPENSE = 'depreciation_expense', 'Depreciation'
    UTILITIES = 'utilities', 'Utilities'
    PROJECT_COSTS = 'project_costs', 'Project Costs'
    MARKETING = 'marketing', 'Marketing'
    ADMIN_EXPENSE = 'admin_expense', 'Administrative Expenses'
    OTHER_EXPENSE = 'other_expense', 'Other Expenses'


class Account(BaseModel):
    """
    Chart of Accounts - UAE compliant.
    Only leaf accounts (accounts without children) can be posted to.
    """
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    
    # Category for Trial Balance & Financial Statement grouping
    account_category = models.CharField(
        max_length=50, 
        choices=AccountCategory.choices, 
        blank=True, 
        null=True,
        help_text="Category for grouping in Trial Balance and Financial Statements"
    )
    
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)  # System accounts can't be deleted
    
    # Contra account flag (for Accumulated Depreciation, etc.)
    is_contra_account = models.BooleanField(
        default=False,
        help_text="Contra accounts have opposite normal balance (e.g., Accumulated Depreciation)"
    )
    
    # Cash Flow Statement - IFRS compliant
    # Mark Bank & Cash accounts for Cash Flow calculation
    is_cash_account = models.BooleanField(
        default=False,
        help_text="Mark as True for Bank and Cash accounts only. Used for Cash Flow Statement."
    )
    
    # Overdraft allowed flag - for bank accounts that can have credit (negative) balances
    overdraft_allowed = models.BooleanField(
        default=False,
        help_text="Allow credit (negative) balance for this account. Only applicable to bank accounts."
    )
    
    # Fixed Deposit flag - IFRS Cash Flow compliance
    # Fixed Deposits are NOT cash equivalents unless maturity <= 3 months
    is_fixed_deposit = models.BooleanField(
        default=False,
        help_text="Mark as True for Fixed Deposit accounts. These are EXCLUDED from Cash Flow Statement opening/closing balance."
    )
    
    # Balance tracking
    opening_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Opening balance locked after first posting
    opening_balance_locked = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['code']
    
    def __str__(self):
        return f"{self.code} - {self.name}"
    
    @property
    def is_leaf(self):
        """Returns True if this is a leaf account (no children)."""
        return not self.children.filter(is_active=True).exists()
    
    @property
    def debit_increases(self):
        """Returns True if debits increase this account type."""
        return self.account_type in [AccountType.ASSET, AccountType.EXPENSE]
    
    @property
    def has_abnormal_balance(self):
        """
        Check if balance is abnormal for account type.
        - Assets/Expenses should have debit (positive) balance
        - Liabilities/Equity/Income should have credit (negative) balance
        """
        if self.debit_increases:
            return self.balance < 0
        return self.balance > 0
    
    @property
    def current_balance(self):
        """Get the current balance (opening + transactions)."""
        return self.opening_balance + self.balance
    
    def clean(self):
        """Validate account before saving."""
        if self.opening_balance_locked and self.pk:
            original = Account.objects.get(pk=self.pk)
            if original.opening_balance != self.opening_balance:
                raise ValidationError("Opening balance cannot be changed after posting.")
        
        # CRITICAL ACCOUNTING RULE:
        # Income and Expense accounts must start at ZERO
        # Only Assets, Liabilities, and Equity can have opening balances
        if self.opening_balance != Decimal('0.00'):
            if self.account_type in [AccountType.INCOME, AccountType.EXPENSE]:
                raise ValidationError(
                    f"Opening balance not allowed for {self.get_account_type_display()} accounts. "
                    f"Income and Expense accounts must start at zero."
                )


class FiscalYear(BaseModel):
    """
    Fiscal year for accounting periods.
    """
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)
    closed_date = models.DateField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_fiscal_years'
    )
    
    class Meta:
        ordering = ['-start_date']
    
    def __str__(self):
        return self.name
    
    def close(self, user):
        """Close the fiscal year."""
        self.is_closed = True
        self.closed_date = date.today()
        self.closed_by = user
        self.save()

    @classmethod
    def validate_posting_allowed(cls, entry_date):
        """
        Central guard: raise ValidationError if the fiscal year for entry_date
        is closed. Called by every module before creating a journal entry.

        This check is NOT bypassable — a closed fiscal year is a hard lock.
        Period lock bypass (for superusers) is a separate, softer control.
        """
        if not entry_date:
            return
        fy = cls.objects.filter(
            start_date__lte=entry_date,
            end_date__gte=entry_date,
            is_active=True,
        ).first()
        if fy and fy.is_closed:
            raise ValidationError(
                f"Fiscal year {fy.name} ({fy.start_date} – {fy.end_date}) is closed. "
                f"No transactions can be posted to date {entry_date}."
            )
        if not fy:
            raise ValidationError(
                f"No active fiscal year found for date {entry_date}. "
                f"Create or activate a fiscal year covering this date."
            )


class AccountingPeriod(BaseModel):
    """
    Monthly accounting period for period-based controls.
    """
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name='periods')
    name = models.CharField(max_length=50)  # e.g., "January 2025"
    start_date = models.DateField()
    end_date = models.DateField()
    is_locked = models.BooleanField(default=False)
    locked_date = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_periods'
    )
    
    class Meta:
        ordering = ['start_date']
        unique_together = ['fiscal_year', 'start_date']
    
    def __str__(self):
        return f"{self.name} ({self.fiscal_year.name})"


class JournalEntry(BaseModel):
    """
    Journal Entry (Double-entry accounting).
    Financial records should not be hard deleted - use reversals instead.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('reversed', 'Reversed'),
    ]
    
    ENTRY_TYPE_CHOICES = [
        ('standard', 'Standard'),
        ('opening', 'Opening Balance'),
        ('adjustment', 'Adjustment'),
        ('adjusting', 'Adjusting Entry'),
        ('reversal', 'Reversal'),
        ('closing', 'Closing Entry'),
    ]
    
    SOURCE_MODULE_CHOICES = [
        ('manual', 'Manual Entry'),
        ('sales', 'Sales Invoice'),
        ('purchase', 'Vendor Bill'),
        ('payment', 'Payment'),
        ('bank_transfer', 'Bank Transfer'),
        ('expense_claim', 'Expense Claim'),
        ('payroll', 'Payroll'),
        ('inventory', 'Inventory Movement'),
        ('fixed_asset', 'Fixed Asset'),
        ('project', 'Project Expense'),
        ('pdc', 'PDC Cheque'),
        ('property', 'Property/Rent'),
        ('vat', 'VAT Adjustment'),
        ('corporate_tax', 'Corporate Tax'),
        ('opening_balance', 'Opening Balance'),
        ('year_end', 'Year-End Closing'),
        ('reversal', 'Reversal Entry'),
        ('adjustment', 'Manual Adjustment'),
    ]
    
    entry_number = models.CharField(max_length=50, unique=True, editable=False)
    date = models.DateField()
    reference = models.CharField(max_length=200, blank=True)  # Invoice/Bill number
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES, default='standard')
    source_module = models.CharField(
        max_length=50, 
        choices=SOURCE_MODULE_CHOICES, 
        default='manual',
        help_text="Module that created this journal entry"
    )
    
    # Source document reference (for system-generated journals)
    source_id = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="ID of the source document that created this journal"
    )
    
    # System-generated vs Manual distinction
    is_system_generated = models.BooleanField(
        default=False,
        help_text="True if auto-generated by system (invoice, bill, payroll, etc.)"
    )
    
    # Lock status for immutability
    is_locked = models.BooleanField(
        default=False,
        help_text="Locked journals cannot be edited or deleted"
    )
    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='journal_entries'
    )
    period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='journal_entries'
    )
    
    # Totals
    total_debit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # For reversals
    reversal_of = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_by'
    )
    reversal_reason = models.TextField(blank=True)
    
    # Audit
    posted_date = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_journals'
    )
    
    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name_plural = 'Journal Entries'
    
    def __str__(self):
        return f"{self.entry_number} - {self.date}"
    
    def save(self, *args, **kwargs):
        # Auto-set fiscal_year from date when missing (for system-generated journals)
        if self.date and not self.fiscal_year:
            fy = FiscalYear.objects.filter(
                start_date__lte=self.date,
                end_date__gte=self.date,
                is_active=True
            ).first()
            if fy:
                self.fiscal_year = fy

        if not self.entry_number:
            # Fiscal integrity: Use entry date year so DOC-2024-xxx for 2024 entries
            year = None
            if self.date:
                year = self.date.year
            elif self.fiscal_year:
                year = self.fiscal_year.start_date.year
            self.entry_number = generate_number('JOURNAL', JournalEntry, 'entry_number', year=year)

        # Set is_system_generated based on source_module
        if self.source_module != 'manual':
            self.is_system_generated = True
        
        super().save(*args, **kwargs)
    
    @property
    def is_editable(self):
        """
        Check if journal can be edited.
        SAP/Oracle/Zoho compliant rules:
        - Draft manual journals can be edited
        - Posted journals cannot be edited
        - System-generated journals cannot be edited
        - Locked journals cannot be edited
        """
        if self.is_locked:
            return False
        if self.status == 'posted':
            return False
        if self.status == 'reversed':
            return False
        if self.is_system_generated:
            return False
        if self.period and self.period.is_locked:
            return False
        if self.fiscal_year and self.fiscal_year.is_closed:
            return False
        return True
    
    @property
    def is_deletable(self):
        """
        Check if journal can be deleted.
        SAP/Oracle/Zoho compliant rules:
        - Only draft manual journals can be deleted
        - Posted journals must be reversed, not deleted
        - System-generated journals cannot be deleted
        """
        if self.is_locked:
            return False
        if self.status != 'draft':
            return False
        if self.is_system_generated:
            return False
        if self.period and self.period.is_locked:
            return False
        if self.fiscal_year and self.fiscal_year.is_closed:
            return False
        return True
    
    @property
    def is_reversible(self):
        """
        Check if journal can be reversed.
        - Only posted journals can be reversed
        - Already reversed journals cannot be reversed again
        """
        if self.status != 'posted':
            return False
        if self.period and self.period.is_locked:
            return False
        if self.fiscal_year and self.fiscal_year.is_closed:
            return False
        return True
    
    @property
    def edit_restriction_reason(self):
        """Return the reason why this journal cannot be edited."""
        if self.is_locked:
            return "This journal is locked and cannot be modified."
        if self.status == 'posted':
            return "Posted journals cannot be edited. Create a reversal instead."
        if self.status == 'reversed':
            return "Reversed journals cannot be edited."
        if self.is_system_generated:
            return "This journal is system-generated. Edit or cancel the source document instead."
        if self.period and self.period.is_locked:
            return f"Accounting period {self.period.name} is locked."
        if self.fiscal_year and self.fiscal_year.is_closed:
            return f"Fiscal year {self.fiscal_year.name} is closed."
        return None
    
    def calculate_totals(self):
        """Calculate total debits and credits."""
        lines = self.lines.all()
        self.total_debit = sum(line.debit for line in lines)
        self.total_credit = sum(line.credit for line in lines)
        self.save(update_fields=['total_debit', 'total_credit'])
    
    @property
    def is_balanced(self):
        """Check if entry is balanced (debits = credits)."""
        return self.total_debit == self.total_credit
    
    @property
    def line_count(self):
        """Get number of journal lines."""
        return self.lines.count()
    
    def validate_for_posting(self, user=None):
        """Validate journal entry before posting."""
        errors = []
        
        # Check balance
        if not self.is_balanced:
            errors.append("Journal entry must be balanced (Total Debit = Total Credit).")
        
        # Check minimum lines
        if self.line_count < 2:
            errors.append("Journal entry must have at least 2 lines.")
        
        # FISCAL YEAR BOUNDARY: Entry date must fall within fiscal year
        if self.fiscal_year and self.date:
            fy_start = self.fiscal_year.start_date
            fy_end = self.fiscal_year.end_date
            if self.date < fy_start or self.date > fy_end:
                errors.append(
                    f"Entry date {self.date} is outside fiscal year {self.fiscal_year.name} "
                    f"({fy_start} to {fy_end}). Posting blocked."
                )
        
        # HARD LOCK: Closed fiscal year is NEVER bypassable.
        fy_closed = bool(self.fiscal_year and self.fiscal_year.is_closed)
        if fy_closed:
            errors.append(
                f"Fiscal year {self.fiscal_year.name} is closed. "
                f"This is a hard lock — no bypass allowed."
            )

        # SOFT LOCK: Period lock — superuser can bypass if setting allows.
        allow_period_bypass = False
        if user and user.is_superuser:
            try:
                allow_period_bypass = AccountingSettings.get_settings().allow_posting_to_closed_period
            except Exception:
                pass

        period_locked = bool(self.period and self.period.is_locked)
        bypass_used = allow_period_bypass and period_locked and not fy_closed

        if period_locked and not allow_period_bypass:
            errors.append(f"Accounting period {self.period.name} is locked.")
        
        # VAT PERIOD LOCK: Block posting into a filed VAT period
        if self.date and self.source_module not in ('vat', 'vat_return'):
            if VATReturn.is_date_in_locked_period(self.date):
                errors.append(
                    f"VAT period containing {self.date} is filed and locked. "
                    f"Backdated transactions are blocked for FTA compliance."
                )

        # Check all accounts are leaf accounts
        for line in self.lines.all():
            if not line.account.is_leaf:
                errors.append(f"Cannot post to parent account: {line.account.code}. Only leaf accounts allowed.")
        
        # Store bypass flag for audit (validate returns before post, so we attach to self)
        self._post_bypass_used = bypass_used
        return errors

    def post(self, user=None):
        """
        Post the journal entry and update account balances.
        After posting, the journal becomes immutable (locked).
        """
        from django.utils import timezone
        
        errors = self.validate_for_posting(user=user)
        if errors:
            raise ValidationError(errors)

        # Audit: Log when superuser bypasses closed period (enterprise control requirement)
        bypass_used = getattr(self, '_post_bypass_used', False)
        if bypass_used and user:
            from apps.core.audit import log_finance_audit
            log_finance_audit(
                user=user,
                action='post_bypass',
                entity_type='JournalEntry',
                entity_id=self.pk,
                reference_number=self.entry_number,
                amount_after=self.total_debit,
                accounting_period=str(self.period) if self.period else None,
                reason='Superuser bypass: allow_posting_to_closed_period=True',
                details={
                    'date': str(self.date),
                    'period_locked': bool(self.period and self.period.is_locked),
                    'fiscal_year_closed': bool(self.fiscal_year and self.fiscal_year.is_closed),
                    'fiscal_year': self.fiscal_year.name if self.fiscal_year else None,
                },
            )

        # Update account balances
        for line in self.lines.all():
            account = line.account
            if account.debit_increases:
                account.balance += line.debit - line.credit
            else:
                account.balance += line.credit - line.debit
            account.opening_balance_locked = True
            account.save()
        
        self.status = 'posted'
        self.posted_date = timezone.now()
        self.posted_by = user
        self.is_locked = True  # Lock journal after posting
        self.save(update_fields=['status', 'posted_date', 'posted_by', 'is_locked'])
    
    def reverse(self, user=None, reason=''):
        """
        Create a reversal entry for this journal.
        Posted entries can only be reversed, not edited or deleted.
        This is the ONLY way to correct posted transactions (SAP/Oracle compliant).
        """
        if not self.is_reversible:
            if self.status != 'posted':
                raise ValidationError("Only posted entries can be reversed.")
            if self.period and self.period.is_locked:
                raise ValidationError(f"Cannot reverse - accounting period {self.period.name} is locked.")
            if self.fiscal_year and self.fiscal_year.is_closed:
                raise ValidationError(f"Cannot reverse - fiscal year {self.fiscal_year.name} is closed.")
        
        # Determine the current period for reversal
        current_period = AccountingPeriod.objects.filter(
            start_date__lte=date.today(),
            end_date__gte=date.today(),
            is_locked=False
        ).first()
        
        # Create reversal entry
        reversal = JournalEntry.objects.create(
            date=date.today(),
            reference=f"REV-{self.entry_number}",
            description=f"Reversal of {self.entry_number}: {reason or self.description}",
            entry_type='reversal',
            source_module='reversal',
            source_id=self.pk,
            is_system_generated=True,
            reversal_of=self,
            reversal_reason=reason,
            fiscal_year=current_period.fiscal_year if current_period else self.fiscal_year,
            period=current_period or self.period,
            created_by=user,
        )
        
        # Create reversed lines (swap debit and credit)
        for line in self.lines.all():
            JournalEntryLine.objects.create(
                journal_entry=reversal,
                account=line.account,
                description=f"Reversal: {line.description}",
                debit=line.credit,
                credit=line.debit,
            )
        
        reversal.calculate_totals()
        reversal.post(user)
        
        # Mark original as reversed (but keep it locked for audit trail)
        self.status = 'reversed'
        self.save(update_fields=['status'])
        
        return reversal


class JournalEntryLine(models.Model):
    """
    Journal Entry line items (Double-entry).
    """
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='journal_lines'
    )
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    # Bank reconciliation audit trail
    is_bank_reconciled = models.BooleanField(default=False)
    bank_reconciliation = models.ForeignKey(
        'BankReconciliation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cleared_lines',
    )

    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.account.code} - Dr:{self.debit} Cr:{self.credit}"
    
    def clean(self):
        """Validate journal line."""
        if self.debit > 0 and self.credit > 0:
            raise ValidationError("A line cannot have both debit and credit amounts.")
        
        if self.debit == 0 and self.credit == 0:
            raise ValidationError("Either debit or credit must be greater than zero.")


class TaxCode(BaseModel):
    """
    Tax codes for UAE VAT compliance.
    VAT Types: Standard Rated (5%), Zero Rated, Exempt, Out of Scope
    """
    TAX_TYPE_CHOICES = [
        ('standard', 'Standard Rated (5%)'),
        ('zero', 'Zero Rated'),
        ('exempt', 'Exempt'),
        ('out_of_scope', 'Out of Scope'),
    ]
    
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    tax_type = models.CharField(max_length=20, choices=TAX_TYPE_CHOICES, default='standard')
    rate = models.DecimalField(max_digits=5, decimal_places=2)  # 5% standard VAT
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    
    # Accounts for VAT
    sales_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='sales_tax_codes',
        null=True,
        blank=True,
        help_text="VAT Payable account for sales"
    )
    purchase_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='purchase_tax_codes',
        null=True,
        blank=True,
        help_text="VAT Recoverable account for purchases"
    )
    
    class Meta:
        ordering = ['code']
    
    def __str__(self):
        return f"{self.code} - {self.name} ({self.rate}%)"


class BankAccount(BaseModel):
    """
    Bank Account for bank reconciliation.
    current_balance is system-calculated only.
    """
    name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    bank_name = models.CharField(max_length=200)
    branch = models.CharField(max_length=200, blank=True)
    swift_code = models.CharField(max_length=20, blank=True)
    iban = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=10, default='AED')
    
    # Link to GL Account
    gl_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='bank_accounts'
    )
    
    # Balance (calculated from GL)
    current_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    bank_statement_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    last_reconciled_date = models.DateField(null=True, blank=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} - {self.bank_name}"
    
    def update_balance(self):
        """Update current balance from GL account."""
        self.current_balance = self.gl_account.balance
        self.save(update_fields=['current_balance'])


class PettyCash(BaseModel):
    """
    Petty Cash fund management.
    Each petty cash fund links to a GL account for tracking.
    """
    name = models.CharField(max_length=200)
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='petty_cash_funds'
    )
    float_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Initial/replenishment amount")
    current_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Link to GL Account
    gl_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='petty_cash_funds'
    )
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Petty Cash Funds'
    
    def __str__(self):
        return f"{self.name} ({self.custodian.get_full_name() or self.custodian.username})"
    
    def update_balance(self):
        """Update current balance from GL account."""
        self.current_balance = self.gl_account.balance
        self.save(update_fields=['current_balance'])


class PettyCashExpense(BaseModel):
    """
    Individual petty cash expenses.
    Accounting: Dr Expense, Cr Petty Cash
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ]
    
    expense_number = models.CharField(max_length=50, unique=True, editable=False)
    petty_cash = models.ForeignKey(
        PettyCash,
        on_delete=models.PROTECT,
        related_name='expenses'
    )
    expense_date = models.DateField()
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Expense category
    expense_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='petty_cash_expenses'
    )
    
    receipt_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Journal entry link
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='petty_cash_expenses'
    )
    
    class Meta:
        ordering = ['-expense_date', '-created_at']
    
    def __str__(self):
        return f"{self.expense_number} - {self.description}"
    
    def save(self, *args, **kwargs):
        if not self.expense_number:
            self.expense_number = generate_number('PC-EXP', PettyCashExpense, 'expense_number')
        self.total_amount = self.amount + self.vat_amount
        super().save(*args, **kwargs)
    
    def post_to_accounting(self, user=None):
        """
        Post petty cash expense to accounting.
        Dr Expense Account
        Dr VAT Recoverable (if applicable)
        Cr Petty Cash
        """
        if self.status != 'draft':
            raise ValidationError("Only draft expenses can be posted.")
        
        if self.total_amount <= 0:
            raise ValidationError("Expense amount must be greater than zero.")
        
        # Check petty cash balance
        if self.total_amount > self.petty_cash.current_balance:
            raise ValidationError(
                f"Insufficient petty cash balance. Available: {self.petty_cash.current_balance}"
            )
        
        # Get VAT account
        vat_account = AccountMapping.get_account_or_default('vendor_bill_vat', '1300')
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.expense_date,
            reference=self.expense_number,
            description=f"Petty Cash Expense: {self.description}",
            entry_type='standard',
            source_module='petty_cash',
        )
        
        # Debit Expense Account
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.expense_account,
            description=f"Expense - {self.description}",
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        
        # Debit VAT Recoverable (if applicable)
        if self.vat_amount > 0 and vat_account:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_account,
                description=f"Input VAT - {self.expense_number}",
                debit=self.vat_amount,
                credit=Decimal('0.00'),
            )
        
        # Credit Petty Cash
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.petty_cash.gl_account,
            description=f"Petty Cash - {self.petty_cash.name}",
            debit=Decimal('0.00'),
            credit=self.total_amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update petty cash expense
        self.journal_entry = journal
        self.status = 'posted'
        self.save()
        
        # Update petty cash balance
        self.petty_cash.update_balance()
        
        return journal


class PettyCashReplenishment(BaseModel):
    """
    Petty cash replenishment from bank.
    Accounting: Dr Petty Cash, Cr Bank
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ]
    
    replenishment_number = models.CharField(max_length=50, unique=True, editable=False)
    petty_cash = models.ForeignKey(
        PettyCash,
        on_delete=models.PROTECT,
        related_name='replenishments'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name='petty_cash_replenishments'
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Journal entry link
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='petty_cash_replenishments'
    )
    
    class Meta:
        ordering = ['-date', '-created_at']
    
    def __str__(self):
        return f"{self.replenishment_number} - {self.petty_cash.name}"
    
    def save(self, *args, **kwargs):
        if not self.replenishment_number:
            self.replenishment_number = generate_number('PC-REP', PettyCashReplenishment, 'replenishment_number')
        super().save(*args, **kwargs)
    
    def post_to_accounting(self, user=None):
        """
        Post replenishment to accounting.
        Dr Petty Cash
        Cr Bank
        """
        if self.status != 'draft':
            raise ValidationError("Only draft replenishments can be posted.")
        
        if self.amount <= 0:
            raise ValidationError("Replenishment amount must be greater than zero.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.date,
            reference=self.replenishment_number,
            description=f"Petty Cash Replenishment: {self.petty_cash.name}",
            entry_type='standard',
            source_module='petty_cash',
        )
        
        # Debit Petty Cash
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.petty_cash.gl_account,
            description=f"Replenishment - {self.petty_cash.name}",
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        
        # Credit Bank
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.bank_account.gl_account,
            description=f"Bank - {self.bank_account.name}",
            debit=Decimal('0.00'),
            credit=self.amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update replenishment
        self.journal_entry = journal
        self.status = 'posted'
        self.save()
        
        # Update balances
        self.petty_cash.update_balance()
        self.bank_account.update_balance()
        
        return journal


class Payment(BaseModel):
    """
    Payment records (both received and made).
    Payments do not create VAT.
    """
    PAYMENT_TYPE_CHOICES = [
        ('received', 'Payment Received'),
        ('made', 'Payment Made'),
    ]
    
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('card', 'Credit/Debit Card'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('reconciled', 'Reconciled'),
        ('cancelled', 'Cancelled'),
    ]
    
    payment_number = models.CharField(max_length=50, unique=True, editable=False)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='bank')
    payment_date = models.DateField()
    
    # Party (Customer or Vendor)
    party_type = models.CharField(max_length=20)  # 'customer' or 'vendor'
    party_id = models.PositiveIntegerField()
    party_name = models.CharField(max_length=200)  # Denormalized for quick access
    
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    allocated_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    reference = models.CharField(max_length=200, blank=True)  # Invoice/Bill reference
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Bank account
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='payments'
    )
    
    # Linked journal entry
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments'
    )
    
    # Cancellation
    cancelled_date = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    reversal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_reversals'
    )
    
    class Meta:
        ordering = ['-payment_date', '-created_at']
    
    def __str__(self):
        return f"{self.payment_number} - {self.party_name}"
    
    def save(self, *args, **kwargs):
        if not self.payment_number:
            prefix = 'PR' if self.payment_type == 'received' else 'PM'
            self.payment_number = generate_number(f'PAYMENT_{prefix}', Payment, 'payment_number')
        super().save(*args, **kwargs)
    
    @property
    def unallocated_amount(self):
        """Get unallocated (advance) amount."""
        return self.amount - self.allocated_amount
    
    @property
    def is_overpayment(self):
        """Check if this is an overpayment."""
        return self.unallocated_amount > 0 and self.status == 'confirmed'


class ExpenseClaim(BaseModel):
    """
    DEPRECATED: This model is being moved to Purchase module.
    Kept for backwards compatibility with existing data.
    Use apps.purchase.models.ExpenseClaim instead.
    
    Employee expense claims.
    VAT claimable only with valid receipt.
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
        related_name='finance_expense_claims'  # Changed to avoid conflict
    )
    claim_date = models.DateField()
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Totals
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_vat = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Approval
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_approved_claims'  # Changed to avoid conflict
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # Journal entry created on approval
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_expense_claims'  # Changed to avoid conflict
    )
    
    class Meta:
        ordering = ['-claim_date', '-created_at']
        db_table = 'finance_expenseclaim'  # Keep existing table name
    
    def __str__(self):
        return f"{self.claim_number} - {self.employee.get_full_name()}"
    
    def save(self, *args, **kwargs):
        if not self.claim_number:
            self.claim_number = generate_number('EXPENSE', ExpenseClaim, 'claim_number')
        super().save(*args, **kwargs)
    
    def calculate_totals(self):
        """Calculate totals from items."""
        items = self.items.all()
        self.total_amount = sum(item.amount for item in items)
        self.total_vat = sum(item.vat_amount for item in items if item.has_receipt)
        self.save(update_fields=['total_amount', 'total_vat'])


class ExpenseItem(models.Model):
    """
    DEPRECATED: This model is being moved to Purchase module.
    Use apps.purchase.models.ExpenseClaimItem instead.
    
    Individual expense items within a claim.
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
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    has_receipt = models.BooleanField(default=False)
    receipt = models.FileField(upload_to='expense_receipts/', blank=True, null=True)
    is_non_deductible = models.BooleanField(default=False, help_text="Non-deductible for Corporate Tax")
    
    # Account to post to
    expense_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='finance_expense_items'  # Changed to avoid conflict
    )
    
    class Meta:
        ordering = ['date']
        db_table = 'finance_expenseitem'  # Keep existing table name
    
    def __str__(self):
        return f"{self.category} - {self.amount}"


class VATReturn(BaseModel):
    """
    UAE VAT Return model for quarterly/monthly filing.
    Status terminology aligned with UAE FTA standards.
    
    FTA STATUS WORKFLOW:
    1. Draft – before submission to FTA
    2. Filed – successfully submitted to FTA (journal posted, period locked)
    3. Amended – previously filed return has been corrected
    4. Locked – VAT period is closed and cannot be edited
    5. Reversed – VAT return has been reversed
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('filed', 'Filed'),
        ('amended', 'Amended'),
        ('locked', 'Locked'),
        ('reversed', 'Reversed'),
    ]
    
    PERIOD_TYPE_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
    ]
    
    return_number = models.CharField(max_length=50, unique=True, blank=True)
    period_type = models.CharField(max_length=20, choices=PERIOD_TYPE_CHOICES, default='quarterly')
    period_start = models.DateField()
    period_end = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Standard Rated Supplies (Box 1)
    standard_rated_supplies = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    standard_rated_vat = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Zero Rated Supplies (Box 2)
    zero_rated_supplies = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Exempt Supplies (Box 3)
    exempt_supplies = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Total Output VAT
    output_vat = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Purchases (Box 9-10)
    standard_rated_expenses = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    input_vat = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Net VAT
    net_vat = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Adjustments
    adjustments = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    adjustment_reason = models.TextField(blank=True)
    
    # Total Sales/Purchases
    total_sales = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_purchases = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # ========================================
    # POSTING / JOURNAL ENTRY FIELDS (NEW)
    # ========================================
    journal_entry = models.ForeignKey(
        'JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vat_returns'
    )
    posted_date = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_vat_returns'
    )
    reversal_journal_entry = models.ForeignKey(
        'JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vat_return_reversals'
    )
    is_period_locked = models.BooleanField(default=False)
    
    # Filing info
    filed_date = models.DateTimeField(null=True, blank=True)
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='filed_vat_returns'
    )
    fta_reference = models.CharField(max_length=100, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-period_start']
    
    def __str__(self):
        return f"VAT Return: {self.period_start} to {self.period_end}"
    
    def save(self, *args, **kwargs):
        if not self.return_number:
            self.return_number = generate_number('VAT', VATReturn, 'return_number')
        super().save(*args, **kwargs)
    
    def calculate(self):
        """Calculate VAT return amounts."""
        self.total_sales = self.standard_rated_supplies + self.zero_rated_supplies + self.exempt_supplies
        self.output_vat = self.standard_rated_vat
        self.net_vat = self.output_vat - self.input_vat + self.adjustments
        self.save(update_fields=['total_sales', 'output_vat', 'net_vat'])
    
    @property
    def is_refund(self):
        """Check if this return results in a refund."""
        return self.net_vat < 0
    
    @property
    def can_post(self):
        """Check if VAT Return can be posted."""
        return self.status == 'draft' and self.output_vat >= 0 and self.input_vat >= 0
    
    @property
    def can_reverse(self):
        """Check if VAT Return can be reversed (only if Filed, not yet Amended/Locked)."""
        return self.status == 'filed' and self.journal_entry is not None
    
    def get_vat_accounts(self):
        """
        Get VAT control accounts for posting.
        Returns dict with output_vat_account, input_vat_account, vat_payable_account.
        
        Uses AccountMapping with transaction_type:
        - vat_output → Output VAT Account (Liability)
        - vat_input → Input VAT Account (Asset)
        - vat_payable → VAT Payable to FTA Account (Liability)
        """
        from .models import Account, AccountType, AccountMapping
        
        # Try to get from AccountMapping first (using transaction_type, not mapping_type)
        output_vat_mapping = AccountMapping.objects.filter(transaction_type='vat_output').first()
        input_vat_mapping = AccountMapping.objects.filter(transaction_type='vat_input').first()
        vat_payable_mapping = AccountMapping.objects.filter(transaction_type='vat_payable').first()
        
        # Output VAT Account (Liability - VAT collected on sales)
        output_vat_account = None
        if output_vat_mapping and output_vat_mapping.account:
            output_vat_account = output_vat_mapping.account
        else:
            # Fallback: search by account name/code
            output_vat_account = Account.objects.filter(
                is_active=True,
                account_type=AccountType.LIABILITY
            ).filter(
                models.Q(name__icontains='output vat') |
                models.Q(name__icontains='vat payable') |
                models.Q(code='2200')
            ).first()
        
        # Input VAT Account (Asset - VAT paid on purchases)
        input_vat_account = None
        if input_vat_mapping and input_vat_mapping.account:
            input_vat_account = input_vat_mapping.account
        else:
            # Fallback: search by account name/code
            input_vat_account = Account.objects.filter(
                is_active=True,
                account_type=AccountType.ASSET
            ).filter(
                models.Q(name__icontains='input vat') |
                models.Q(name__icontains='vat recoverable') |
                models.Q(code='1200') | models.Q(code='1300')
            ).first()
        
        # VAT Payable to FTA Account (Liability - Net amount owed to FTA)
        vat_payable_account = None
        if vat_payable_mapping and vat_payable_mapping.account:
            vat_payable_account = vat_payable_mapping.account
        else:
            # Fallback: search by account name/code
            vat_payable_account = Account.objects.filter(
                is_active=True,
                account_type=AccountType.LIABILITY
            ).filter(
                models.Q(name__icontains='vat payable') |
                models.Q(name__icontains='fta') |
                models.Q(code='2210')
            ).exclude(
                name__icontains='output'
            ).first()
            
            # If no separate FTA account, use output VAT account
            if not vat_payable_account and output_vat_account:
                vat_payable_account = output_vat_account
        
        return {
            'output_vat_account': output_vat_account,
            'input_vat_account': input_vat_account,
            'vat_payable_account': vat_payable_account,
        }
    
    def post(self, user):
        """
        Post VAT Return - Creates journal entry to clear VAT control accounts.
        
        Journal Entry Logic (UAE FTA Compliant):
        Dr Output VAT Control (clears liability)     = Output VAT Amount
        Cr Input VAT Control (clears asset)          = Input VAT Amount
        Cr/Dr VAT Payable to FTA                     = Net VAT (difference)
        
        This clears the VAT control accounts and transfers net balance to FTA payable.
        
        IMPORTANT: This does NOT affect P&L or Corporate Tax calculations.
        """
        from django.utils import timezone
        from django.core.exceptions import ValidationError
        
        if not self.can_post:
            raise ValidationError("VAT Return cannot be posted. Status must be 'draft'.")
        
        # Get VAT accounts
        vat_accounts = self.get_vat_accounts()
        output_vat_account = vat_accounts['output_vat_account']
        input_vat_account = vat_accounts['input_vat_account']
        vat_payable_account = vat_accounts['vat_payable_account']
        
        if not output_vat_account:
            raise ValidationError("Output VAT account not found. Please configure VAT accounts.")
        if not input_vat_account:
            raise ValidationError("Input VAT account not found. Please configure VAT accounts.")
        if not vat_payable_account:
            raise ValidationError("VAT Payable to FTA account not found. Please configure VAT accounts.")
        
        # Create Journal Entry
        journal = JournalEntry.objects.create(
            date=self.period_end,
            reference=f"VAT-{self.return_number}",
            description=f"VAT Return Settlement - {self.period_start} to {self.period_end}",
            source_module='vat',
            source_id=self.pk,  # Correct field name
            entry_type='standard',
            is_system_generated=True,
            created_by=user,
        )
        
        # Add journal lines
        # Dr Output VAT Control (clear the liability - debit reduces credit balance)
        if self.output_vat > 0:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=output_vat_account,
                description=f"Clear Output VAT - {self.return_number}",
                debit=self.output_vat,
                credit=Decimal('0.00'),
            )
        
        # Cr Input VAT Control (clear the asset - credit reduces debit balance)
        if self.input_vat > 0:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=input_vat_account,
                description=f"Clear Input VAT - {self.return_number}",
                debit=Decimal('0.00'),
                credit=self.input_vat,
            )
        
        # Cr/Dr VAT Payable to FTA (net difference)
        net_vat = self.output_vat - self.input_vat + self.adjustments
        if net_vat > 0:
            # Net VAT Payable - Credit to increase liability
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_payable_account,
                description=f"VAT Payable to FTA - {self.return_number}",
                debit=Decimal('0.00'),
                credit=net_vat,
            )
        elif net_vat < 0:
            # Net VAT Refund - Debit to create receivable/reduce liability
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_payable_account,
                description=f"VAT Refund Due from FTA - {self.return_number}",
                debit=abs(net_vat),
                credit=Decimal('0.00'),
            )
        
        # Update journal totals then post through the proper engine
        # (validates balance, updates account balances, locks the entry)
        journal.total_debit = sum(line.debit for line in journal.lines.all())
        journal.total_credit = sum(line.credit for line in journal.lines.all())
        journal.save(update_fields=['total_debit', 'total_credit'])

        journal.post(user=user)
        
        # Update VAT Return
        self.journal_entry = journal
        self.posted_date = timezone.now()
        self.posted_by = user
        self.status = 'filed'
        self.is_period_locked = True
        self.save(update_fields=['journal_entry', 'posted_date', 'posted_by', 'status', 'is_period_locked'])
        
        return journal
    
    def reverse(self, user):
        """
        Reverse VAT Return - Creates reversal journal entry.
        
        This:
        1. Creates exact reversal of the posting journal
        2. Unlocks the VAT period
        3. Sets status to 'reversed'
        """
        from django.utils import timezone
        from django.core.exceptions import ValidationError
        
        if not self.can_reverse:
            raise ValidationError("VAT Return cannot be reversed. Status must be 'filed'.")
        
        if not self.journal_entry:
            raise ValidationError("No journal entry found to reverse.")
        
        # Create reversal journal entry
        original = self.journal_entry
        reversal = JournalEntry.objects.create(
            date=timezone.now().date(),
            reference=f"REV-{original.reference}",
            description=f"Reversal of {original.reference} - VAT Return {self.return_number}",
            source_module='vat',
            source_id=self.pk,  # Correct field name
            entry_type='reversal',
            is_system_generated=True,
            reversal_of=original,  # Correct field name
            created_by=user,
        )
        
        # Reverse each line (swap debits and credits)
        for line in original.lines.all():
            JournalEntryLine.objects.create(
                journal_entry=reversal,
                account=line.account,
                description=f"Reversal: {line.description}",
                debit=line.credit,
                credit=line.debit,
            )
        
        # Update reversal totals then post through the proper engine
        reversal.total_debit = sum(line.debit for line in reversal.lines.all())
        reversal.total_credit = sum(line.credit for line in reversal.lines.all())
        reversal.save(update_fields=['total_debit', 'total_credit'])

        reversal.post(user=user)
        
        # Update original journal
        original.reversed_by = reversal
        original.save(update_fields=['reversed_by'])
        
        # Update VAT Return
        self.reversal_journal_entry = reversal
        self.status = 'reversed'
        self.is_period_locked = False
        self.save(update_fields=['reversal_journal_entry', 'status', 'is_period_locked'])
        
        return reversal
    
    def check_period_lock(self, transaction_date):
        """
        Check if a transaction date falls within a locked VAT period.
        Used to prevent editing VAT-related transactions in locked periods.
        """
        if not self.is_period_locked:
            return False
        return self.period_start <= transaction_date <= self.period_end
    
    @classmethod
    def is_date_in_locked_period(cls, transaction_date):
        """
        Class method to check if any locked VAT period contains the given date.
        """
        locked_periods = cls.objects.filter(
            is_period_locked=True,
            is_active=True,
            period_start__lte=transaction_date,
            period_end__gte=transaction_date
        )
        return locked_periods.exists()


class CorporateTaxComputation(BaseModel):
    """
    UAE Corporate Tax Computation - Federal Decree-Law No. 47 of 2022
    
    Tax Rate: 9% on profit exceeding AED 375,000
    
    Calculation Flow:
    1. Accounting Profit = Revenue - Expenses
    2. + Add-backs (Non-deductible expenses: fines, penalties, non-business)
    3. - Exempt Income (dividends, qualifying income)
    4. = Taxable Income
    5. Apply threshold (AED 375,000)
    6. Apply tax rate (9%)
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('final', 'Final'),
        ('filed', 'Filed'),
        ('paid', 'Paid'),
    ]
    
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name='tax_computations')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Step 1: Accounting Profit (from General Ledger)
    revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    expenses = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    accounting_profit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Step 2: Tax Adjustments (Add-backs and Exclusions)
    # Non-deductible expenses (add back to profit)
    non_deductible_expenses = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        help_text="Fines, penalties, non-business expenses, entertainment"
    )
    # Exempt income (deduct from profit)
    exempt_income = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        help_text="Qualifying dividends, capital gains on qualifying shareholdings"
    )
    # Other adjustments (+ve or -ve)
    other_adjustments = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        help_text="Depreciation adjustments, provisions, etc."
    )
    
    # Detailed adjustment breakdown (JSON field for flexibility)
    adjustment_details = models.JSONField(
        default=dict, blank=True,
        help_text="Detailed breakdown of adjustments for audit"
    )
    
    # Step 3: Taxable Income
    taxable_income = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Step 4: Tax Calculation (UAE Corporate Tax Law)
    tax_threshold = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('375000.00'),
        help_text="Small business relief threshold (AED 375,000)"
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('9.00'),
        help_text="UAE Corporate Tax rate (%)"
    )
    taxable_amount_above_threshold = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    tax_payable = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Tax Provision Journal (Dr Corporate Tax Expense, Cr Corporate Tax Payable)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tax_computations'
    )
    provision_posted = models.BooleanField(default=False)
    provision_date = models.DateField(null=True, blank=True)
    
    # Tax Payment Journal (Dr Corporate Tax Payable, Cr Bank)
    payment_journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tax_payments'
    )
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    payment_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-fiscal_year__start_date']
    
    def __str__(self):
        return f"Corporate Tax - {self.fiscal_year.name}"
    
    @property
    def balance_due(self):
        """Outstanding tax balance."""
        return self.tax_payable - self.paid_amount
    
    def calculate(self):
        """
        Calculate corporate tax based on UAE Corporate Tax Law.
        
        Formula:
        Accounting Profit = Revenue - Expenses
        Taxable Income = Accounting Profit + Non-deductible - Exempt + Other
        Tax = (Taxable Income - Threshold) × Rate (if > threshold)
        """
        # Calculate accounting profit
        self.accounting_profit = self.revenue - self.expenses
        
        # Calculate taxable income with adjustments
        self.taxable_income = (
            self.accounting_profit 
            + self.non_deductible_expenses  # Add back non-deductible
            - self.exempt_income            # Exclude exempt income
            + self.other_adjustments        # Other adjustments (+/-)
        )
        
        # Calculate tax (9% on amount exceeding AED 375,000)
        if self.taxable_income <= self.tax_threshold:
            self.taxable_amount_above_threshold = Decimal('0.00')
            self.tax_payable = Decimal('0.00')
        else:
            self.taxable_amount_above_threshold = self.taxable_income - self.tax_threshold
            self.tax_payable = (self.taxable_amount_above_threshold * self.tax_rate / 100).quantize(Decimal('0.01'))
        
        self.save()
    
    def post_provision(self, user=None):
        """
        Post tax provision journal entry.
        SAP/Oracle Standard: Auto-post when tax computation is finalized.
        
        Dr Corporate Tax Expense (P&L)
        Cr Corporate Tax Payable (Liability)
        """
        from django.core.exceptions import ValidationError
        
        if self.provision_posted:
            raise ValidationError("Tax provision already posted.")
        
        if self.tax_payable <= 0:
            raise ValidationError("No tax payable. No provision needed.")
        
        # Get accounts using Account Mapping
        tax_expense = AccountMapping.get_account_or_default('corporate_tax_expense', '5900')
        if not tax_expense:
            tax_expense = Account.objects.filter(
                account_type=AccountType.EXPENSE, is_active=True, name__icontains='tax'
            ).first()
        if not tax_expense:
            raise ValidationError(
                "Corporate Tax Expense account not configured. "
                "Please set up Account Mapping in Finance → Account Mapping."
            )
        
        tax_payable_account = AccountMapping.get_account_or_default('corporate_tax_payable', '2400')
        if not tax_payable_account:
            tax_payable_account = Account.objects.filter(
                account_type=AccountType.LIABILITY, is_active=True, name__icontains='tax'
            ).first()
        if not tax_payable_account:
            raise ValidationError(
                "Corporate Tax Payable account not configured. "
                "Please set up Account Mapping in Finance → Account Mapping."
            )
        
        # Create provision journal
        from datetime import date
        provision_date = self.fiscal_year.end_date or date.today()
        
        journal = JournalEntry.objects.create(
            date=provision_date,
            reference=f"TAX-{self.fiscal_year.name}",
            description=f"Corporate Tax Provision - {self.fiscal_year.name}",
            entry_type='adjusting',
            source_module='corporate_tax',
            fiscal_year=self.fiscal_year,
        )
        
        # Debit Corporate Tax Expense
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=tax_expense,
            description=f"Corporate Tax Expense - FY {self.fiscal_year.name}",
            debit=self.tax_payable,
            credit=Decimal('0.00'),
        )
        
        # Credit Corporate Tax Payable
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=tax_payable_account,
            description=f"Corporate Tax Payable - FY {self.fiscal_year.name}",
            debit=Decimal('0.00'),
            credit=self.tax_payable,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.journal_entry = journal
        self.provision_posted = True
        self.provision_date = provision_date
        self.status = 'final'
        self.save()
        
        return journal
    
    def post_payment(self, bank_account, payment_date, reference='', user=None):
        """
        Post tax payment journal entry.
        
        Dr Corporate Tax Payable (clears liability)
        Cr Bank
        """
        from django.core.exceptions import ValidationError
        
        if self.balance_due <= 0:
            raise ValidationError("No outstanding tax balance.")
        
        if not self.provision_posted:
            raise ValidationError("Please post tax provision first.")
        
        # Get Corporate Tax Payable account
        tax_payable_account = AccountMapping.get_account_or_default('corporate_tax_payable', '2400')
        if not tax_payable_account:
            tax_payable_account = Account.objects.filter(
                account_type=AccountType.LIABILITY, is_active=True, name__icontains='tax'
            ).first()
        
        if not bank_account.gl_account:
            raise ValidationError("Bank account has no linked GL account.")
        
        payment_amount = self.balance_due
        
        # Create payment journal
        journal = JournalEntry.objects.create(
            date=payment_date,
            reference=reference or f"TAX-PAY-{self.fiscal_year.name}",
            description=f"Corporate Tax Payment - {self.fiscal_year.name}",
            entry_type='standard',
            source_module='payment',
            fiscal_year=self.fiscal_year,
        )
        
        # Debit Corporate Tax Payable (clear liability)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=tax_payable_account,
            description=f"Corporate Tax Payment - FY {self.fiscal_year.name}",
            debit=payment_amount,
            credit=Decimal('0.00'),
        )
        
        # Credit Bank
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account.gl_account,
            description=f"Corporate Tax Payment to FTA",
            debit=Decimal('0.00'),
            credit=payment_amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.payment_journal_entry = journal
        self.paid_amount = payment_amount
        self.payment_date = payment_date
        self.payment_reference = reference
        self.status = 'paid'
        self.save()
        
        return journal


class Budget(BaseModel):
    """
    Budget for annual/monthly financial planning.
    Supports department-wise budgets.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ]
    
    PERIOD_TYPE_CHOICES = [
        ('annual', 'Annual'),
        ('quarterly', 'Quarterly'),
        ('monthly', 'Monthly'),
    ]
    
    name = models.CharField(max_length=200)
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name='budgets')
    period_type = models.CharField(max_length=20, choices=PERIOD_TYPE_CHOICES, default='annual')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Optional department link
    department = models.CharField(max_length=200, blank=True)
    
    # Approval
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_budgets'
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-fiscal_year__start_date', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.fiscal_year.name}"
    
    def get_total_income(self):
        """Get total budgeted income."""
        return self.lines.filter(account__account_type=AccountType.INCOME).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
    
    def get_total_expense(self):
        """Get total budgeted expense."""
        return self.lines.filter(account__account_type=AccountType.EXPENSE).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')


class BudgetLine(models.Model):
    """
    Individual budget line items.
    """
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='lines')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='budget_lines')
    
    # Monthly amounts (for detailed planning)
    jan = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    feb = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    mar = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    apr = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    may = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    jun = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    jul = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    aug = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    sep = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    oct = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    nov = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    dec = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Total (calculated)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    notes = models.CharField(max_length=500, blank=True)
    
    class Meta:
        unique_together = ['budget', 'account']
        ordering = ['account__code']
    
    def __str__(self):
        return f"{self.budget.name} - {self.account.code}"
    
    def calculate_total(self):
        """Calculate total from monthly amounts."""
        self.amount = (
            self.jan + self.feb + self.mar + self.apr + self.may + self.jun +
            self.jul + self.aug + self.sep + self.oct + self.nov + self.dec
        )
        return self.amount
    
    def save(self, *args, **kwargs):
        self.calculate_total()
        super().save(*args, **kwargs)


class BankTransfer(BaseModel):
    """
    Bank-to-Bank transfers.
    No VAT impact, no income/expense impact.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ]
    
    transfer_number = models.CharField(max_length=50, unique=True, editable=False)
    transfer_date = models.DateField()
    
    # Source bank
    from_bank = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name='transfers_out'
    )
    
    # Destination bank
    to_bank = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name='transfers_in'
    )
    
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reference = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Journal entry
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_transfers'
    )
    
    class Meta:
        ordering = ['-transfer_date', '-created_at']
    
    def __str__(self):
        return f"{self.transfer_number} - {self.from_bank.name} → {self.to_bank.name}"
    
    def save(self, *args, **kwargs):
        if not self.transfer_number:
            self.transfer_number = generate_number('TRANSFER', BankTransfer, 'transfer_number')
        super().save(*args, **kwargs)
    
    def clean(self):
        if self.from_bank == self.to_bank:
            raise ValidationError("Source and destination bank cannot be the same.")
    
    def confirm(self, user):
        """Confirm the transfer and create journal entry."""
        if self.status != 'draft':
            raise ValidationError("Only draft transfers can be confirmed.")
        
        # Create journal entry: Debit To Bank, Credit From Bank
        journal = JournalEntry.objects.create(
            date=self.transfer_date,
            reference=self.transfer_number,
            description=f"Bank Transfer: {self.from_bank.name} → {self.to_bank.name}",
        )
        
        # Debit destination bank
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.to_bank.gl_account,
            description=f"Transfer from {self.from_bank.name}",
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        
        # Credit source bank
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.from_bank.gl_account,
            description=f"Transfer to {self.to_bank.name}",
            debit=Decimal('0.00'),
            credit=self.amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.journal_entry = journal
        self.status = 'confirmed'
        self.save()
        
        return journal


class BankStatement(BaseModel):
    """
    Bank Statement for reconciliation.
    Imported via CSV or manual entry.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('matched', 'Fully Matched'),
        ('reconciled', 'Reconciled'),
        ('locked', 'Locked'),
    ]
    
    statement_number = models.CharField(max_length=50, unique=True, editable=False)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name='statements')
    statement_start_date = models.DateField()
    statement_end_date = models.DateField()
    
    # Statement balances (from bank)
    opening_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    closing_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Calculated totals
    total_debits = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_credits = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Reconciliation completion
    reconciled_date = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciled_statements'
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-statement_end_date']
        unique_together = ['bank_account', 'statement_start_date', 'statement_end_date']
    
    def __str__(self):
        return f"{self.bank_account.name}: {self.statement_start_date} to {self.statement_end_date}"
    
    def save(self, *args, **kwargs):
        if not self.statement_number:
            self.statement_number = generate_number('STMT', BankStatement, 'statement_number')
        super().save(*args, **kwargs)
    
    def calculate_totals(self):
        """Calculate totals from statement lines."""
        lines = self.lines.all()
        self.total_debits = sum(line.debit for line in lines)
        self.total_credits = sum(line.credit for line in lines)
        self.save(update_fields=['total_debits', 'total_credits'])
    
    def validate_balance(self):
        """
        Validate: Opening + Credits - Debits = Closing
        """
        calculated_closing = self.opening_balance + self.total_credits - self.total_debits
        return abs(calculated_closing - self.closing_balance) < Decimal('0.01')
    
    @property
    def matched_count(self):
        """Count of matched lines."""
        return self.lines.filter(reconciliation_status='matched').count()
    
    @property
    def unmatched_count(self):
        """Count of unmatched lines."""
        return self.lines.filter(reconciliation_status='unmatched').count()
    
    @property
    def total_lines(self):
        """Total number of lines."""
        return self.lines.count()
    
    @property
    def match_percentage(self):
        """Percentage of matched lines."""
        total = self.total_lines
        if total == 0:
            return Decimal('0.00')
        return (Decimal(self.matched_count) / Decimal(total) * 100).quantize(Decimal('0.01'))
    
    def auto_match(self, date_tolerance=3):
        """
        Auto-match statement lines with GL journal lines (primary) and payments.

        Confidence scoring:
          100% — exactly one candidate matches amount + date window
           70% — multiple candidates; best one picked but flagged for review
            0% — no match found
        """
        from datetime import timedelta

        already_matched_payment_ids = set(
            BankStatementLine.objects.filter(
                matched_payment__isnull=False
            ).values_list('matched_payment_id', flat=True)
        )
        already_matched_jel_ids = set(
            BankStatementLine.objects.filter(
                matched_journal_line__isnull=False
            ).values_list('matched_journal_line_id', flat=True)
        )

        unmatched_lines = self.lines.filter(reconciliation_status='unmatched')
        matched_count = 0

        for line in unmatched_lines:
            date_from = line.transaction_date - timedelta(days=date_tolerance)
            date_to = line.transaction_date + timedelta(days=date_tolerance)

            # --- 1) Try GL Journal Entry Lines first ---
            je_qs = JournalEntryLine.objects.filter(
                account=self.bank_account.gl_account,
                journal_entry__status='posted',
                journal_entry__date__gte=date_from,
                journal_entry__date__lte=date_to,
                is_bank_reconciled=False,
            ).exclude(id__in=already_matched_jel_ids)

            if line.credit > 0:
                je_candidates = list(je_qs.filter(debit=line.credit))
            else:
                je_candidates = list(je_qs.filter(credit=line.debit))

            if len(je_candidates) == 1:
                jel = je_candidates[0]
                line.matched_journal_line = jel
                line.matched_record_type = 'journal'
                line.reconciliation_status = 'matched'
                line.match_method = 'auto'
                line.match_confidence = Decimal('100.00')
                line.save()
                already_matched_jel_ids.add(jel.id)
                matched_count += 1
                continue
            elif len(je_candidates) > 1:
                jel = je_candidates[0]
                line.matched_journal_line = jel
                line.matched_record_type = 'journal'
                line.reconciliation_status = 'matched'
                line.match_method = 'auto'
                line.match_confidence = Decimal('70.00')
                line.save()
                already_matched_jel_ids.add(jel.id)
                matched_count += 1
                continue

            # --- 2) Try Payments ---
            if line.credit > 0:
                pay_qs = Payment.objects.filter(
                    bank_account=self.bank_account,
                    payment_type='received',
                    status='confirmed',
                    amount=line.credit,
                    payment_date__gte=date_from,
                    payment_date__lte=date_to,
                ).exclude(id__in=already_matched_payment_ids)
            elif line.debit > 0:
                pay_qs = Payment.objects.filter(
                    bank_account=self.bank_account,
                    payment_type='made',
                    status='confirmed',
                    amount=line.debit,
                    payment_date__gte=date_from,
                    payment_date__lte=date_to,
                ).exclude(id__in=already_matched_payment_ids)
            else:
                continue

            pay_candidates = list(pay_qs[:5])

            if len(pay_candidates) == 1:
                pay = pay_candidates[0]
                line.matched_payment = pay
                line.matched_record_type = 'payment'
                line.reconciliation_status = 'matched'
                line.match_method = 'auto'
                line.match_confidence = Decimal('100.00')
                line.save()
                already_matched_payment_ids.add(pay.id)
                matched_count += 1
            elif len(pay_candidates) > 1:
                pay = pay_candidates[0]
                line.matched_payment = pay
                line.matched_record_type = 'payment'
                line.reconciliation_status = 'matched'
                line.match_method = 'auto'
                line.match_confidence = Decimal('70.00')
                line.save()
                already_matched_payment_ids.add(pay.id)
                matched_count += 1

        if self.unmatched_count == 0 and self.total_lines > 0:
            self.status = 'matched'
            self.save(update_fields=['status'])

        return matched_count
    
    def finalize(self, user):
        """
        Finalize the statement.
        Validates all lines are matched and balance is correct.
        """
        from django.utils import timezone
        
        if self.unmatched_count > 0:
            raise ValidationError(f"{self.unmatched_count} lines are still unmatched.")
        
        if not self.validate_balance():
            raise ValidationError("Statement balance does not match calculated balance.")
        
        for line in self.lines.filter(reconciliation_status='matched'):
            if line.matched_payment:
                line.matched_payment.status = 'reconciled'
                line.matched_payment.save()
        
        self.status = 'reconciled'
        self.reconciled_date = timezone.now()
        self.reconciled_by = user
        self.save()
    
    def lock(self, user):
        """Lock a fully matched/reconciled statement — no further changes allowed."""
        from django.utils import timezone
        if self.status not in ('matched', 'reconciled'):
            raise ValidationError("Only matched or reconciled statements can be locked.")
        self.status = 'locked'
        if not self.reconciled_date:
            self.reconciled_date = timezone.now()
            self.reconciled_by = user
        self.save()


class BankStatementLine(models.Model):
    """
    Individual line in a bank statement.
    Tracks matching status with accounting records.
    """
    RECONCILIATION_STATUS_CHOICES = [
        ('unmatched', 'Unmatched'),
        ('matched', 'Matched'),
        ('adjusted', 'Adjusted'),
    ]
    
    MATCH_METHOD_CHOICES = [
        ('auto', 'Auto'),
        ('manual', 'Manual'),
    ]
    
    MATCHED_RECORD_TYPE_CHOICES = [
        ('payment', 'Payment'),
        ('journal', 'Journal Entry'),
        ('adjustment', 'Adjustment'),
    ]
    
    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name='lines')
    line_number = models.PositiveIntegerField(default=0)
    transaction_date = models.DateField()
    value_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=500)
    reference = models.CharField(max_length=200, blank=True)
    
    # Amounts (bank perspective: debit = out, credit = in)
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Matching status
    reconciliation_status = models.CharField(
        max_length=20, 
        choices=RECONCILIATION_STATUS_CHOICES, 
        default='unmatched'
    )
    match_method = models.CharField(
        max_length=20,
        choices=MATCH_METHOD_CHOICES,
        blank=True
    )
    matched_record_type = models.CharField(
        max_length=20,
        choices=MATCHED_RECORD_TYPE_CHOICES,
        blank=True
    )
    
    # Links to matched records
    matched_payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='statement_lines'
    )
    matched_journal_line = models.ForeignKey(
        JournalEntryLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='statement_lines'
    )
    
    # For adjustments
    adjustment_journal = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='adjustment_statement_lines'
    )
    
    match_confidence = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Auto-match confidence: 100 = exact single, 70 = multiple candidates"
    )

    # Audit
    matched_date = models.DateTimeField(null=True, blank=True)
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='matched_statement_lines'
    )
    
    class Meta:
        ordering = ['line_number', 'transaction_date']
        unique_together = ['statement', 'line_number']
        constraints = [
            models.UniqueConstraint(
                fields=['statement', 'transaction_date', 'description', 'debit', 'credit'],
                name='unique_statement_line_content',
            ),
        ]
    
    def __str__(self):
        return f"{self.transaction_date}: {self.description} ({self.debit or self.credit})"
    
    @property
    def amount(self):
        """Net amount (positive for credit, negative for debit)."""
        return self.credit - self.debit
    
    def match_with_payment(self, payment, user):
        """Manually match this line with a payment."""
        from django.utils import timezone
        
        if self.reconciliation_status == 'matched':
            raise ValidationError("This line is already matched.")

        existing = BankStatementLine.objects.filter(
            matched_payment=payment
        ).exclude(pk=self.pk).exists()
        if existing:
            raise ValidationError(
                f"Payment {payment.payment_number} is already matched to another statement line."
            )
        
        self.matched_payment = payment
        self.matched_record_type = 'payment'
        self.reconciliation_status = 'matched'
        self.match_method = 'manual'
        self.match_confidence = Decimal('100.00')
        self.matched_date = timezone.now()
        self.matched_by = user
        self.save()
    
    def match_with_journal(self, journal_line, user):
        """Manually match this line with a journal entry line."""
        from django.utils import timezone
        
        if self.reconciliation_status == 'matched':
            raise ValidationError("This line is already matched.")

        existing = BankStatementLine.objects.filter(
            matched_journal_line=journal_line
        ).exclude(pk=self.pk).exists()
        if existing:
            raise ValidationError(
                f"Journal line {journal_line.id} is already matched to another statement line."
            )
        
        self.matched_journal_line = journal_line
        self.matched_record_type = 'journal'
        self.reconciliation_status = 'matched'
        self.match_method = 'manual'
        self.match_confidence = Decimal('100.00')
        self.matched_date = timezone.now()
        self.matched_by = user
        self.save()
    
    def create_adjustment(self, adjustment_type, expense_account, user):
        """
        Create an adjustment journal entry for unmatched bank items.
        adjustment_type: 'bank_charge', 'interest_income', 'fx_difference', 'other'
        """
        from django.utils import timezone
        
        if self.reconciliation_status == 'matched':
            raise ValidationError("This line is already matched.")
        
        # Create adjustment journal
        journal = JournalEntry.objects.create(
            date=self.transaction_date,
            reference=f"ADJ-{self.statement.statement_number}-{self.line_number}",
            description=f"Reconciliation Adjustment: {adjustment_type} - {self.description}",
        )
        
        bank_gl_account = self.statement.bank_account.gl_account
        
        if self.debit > 0:
            # Money out - Debit Expense, Credit Bank
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=expense_account,
                description=f"Bank {adjustment_type}: {self.description}",
                debit=self.debit,
            )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=bank_gl_account,
                description=f"Bank {adjustment_type}: {self.description}",
                credit=self.debit,
            )
        else:
            # Money in - Debit Bank, Credit Income
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=bank_gl_account,
                description=f"Bank {adjustment_type}: {self.description}",
                debit=self.credit,
            )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=expense_account,
                description=f"Bank {adjustment_type}: {self.description}",
                credit=self.credit,
            )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update this line
        self.adjustment_journal = journal
        self.matched_record_type = 'adjustment'
        self.reconciliation_status = 'adjusted'
        self.match_method = 'manual'
        self.matched_date = timezone.now()
        self.matched_by = user
        self.save()
        
        return journal
    
    def unmatch(self):
        """Remove matching from this line."""
        if self.statement.status in ['reconciled', 'locked']:
            raise ValidationError("Cannot unmatch lines in reconciled/locked statements.")
        
        self.matched_payment = None
        self.matched_journal_line = None
        self.adjustment_journal = None
        self.matched_record_type = ''
        self.reconciliation_status = 'unmatched'
        self.match_method = ''
        self.match_confidence = Decimal('0.00')
        self.matched_date = None
        self.matched_by = None
        self.save()


class BankReconciliation(BaseModel):
    """
    Bank Reconciliation Summary - links statement to GL.
    Used for reconciliation reports.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('approved', 'Approved'),
    ]
    
    reconciliation_number = models.CharField(max_length=50, unique=True, editable=False)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name='reconciliations')
    bank_statement = models.ForeignKey(
        BankStatement, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='reconciliation_summary'
    )
    reconciliation_date = models.DateField()
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Statement balances (from bank)
    statement_opening_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    statement_closing_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # GL balances (from accounting)
    gl_opening_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    gl_closing_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Reconciliation items
    outstanding_deposits = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    outstanding_checks = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    adjustments = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Calculated
    reconciled_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    difference = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Approval
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='completed_reconciliations'
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_reconciliations'
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-reconciliation_date']
    
    def __str__(self):
        return f"Reconciliation: {self.bank_account.name} - {self.reconciliation_date}"
    
    def save(self, *args, **kwargs):
        if not self.reconciliation_number:
            self.reconciliation_number = generate_number('RECON', BankReconciliation, 'reconciliation_number')
        super().save(*args, **kwargs)
    
    def compute_gl_closing_balance(self):
        """GL Closing Balance = sum(debits) - sum(credits) for all posted lines up to period_end."""
        gl_account = self.bank_account.gl_account
        agg = JournalEntryLine.objects.filter(
            account=gl_account,
            journal_entry__status='posted',
            journal_entry__date__lte=self.period_end,
        ).aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )
        dr = agg['total_debit'] or Decimal('0.00')
        cr = agg['total_credit'] or Decimal('0.00')
        return dr - cr

    def get_gl_lines(self):
        """All posted journal lines hitting this bank GL account within the period."""
        gl_account = self.bank_account.gl_account
        return JournalEntryLine.objects.filter(
            account=gl_account,
            journal_entry__status='posted',
            journal_entry__date__gte=self.period_start,
            journal_entry__date__lte=self.period_end,
        ).select_related('journal_entry').order_by('journal_entry__date', 'id')

    def calculate(self):
        """
        Reconciliation formula (audit-standard):
        Statement Closing
          + Outstanding Deposits  (uncleared debits in GL = money coming in)
          - Outstanding Payments  (uncleared credits in GL = money going out)
          = Adjusted Bank Balance
        Difference = GL Closing - Adjusted Bank Balance (must be 0 to approve)
        """
        self.gl_closing_balance = self.compute_gl_closing_balance()

        gl_lines = self.get_gl_lines()
        cleared_ids = set(
            self.cleared_lines.values_list('id', flat=True)
        )

        outstanding_debits = Decimal('0.00')
        outstanding_credits = Decimal('0.00')
        for line in gl_lines:
            if line.id not in cleared_ids:
                outstanding_debits += line.debit
                outstanding_credits += line.credit

        self.outstanding_deposits = outstanding_debits
        self.outstanding_checks = outstanding_credits

        self.reconciled_balance = (
            self.statement_closing_balance
            + self.outstanding_deposits
            - self.outstanding_checks
            + self.adjustments
        )
        self.difference = self.gl_closing_balance - self.reconciled_balance
        self.save(update_fields=[
            'gl_closing_balance', 'outstanding_deposits', 'outstanding_checks',
            'reconciled_balance', 'difference',
        ])

    def calculate_from_statement(self):
        """Calculate values from linked bank statement."""
        if not self.bank_statement:
            return

        self.statement_opening_balance = self.bank_statement.opening_balance
        self.statement_closing_balance = self.bank_statement.closing_balance
        self.calculate()

    @property
    def is_reconciled(self):
        return abs(self.difference) < Decimal('0.01')

    def clear_line(self, journal_line, cleared_date=None):
        """Mark a single GL journal line as cleared in this reconciliation."""
        if journal_line.is_bank_reconciled:
            raise ValidationError(
                f"Journal line {journal_line.id} is already reconciled "
                f"(Reconciliation #{journal_line.bank_reconciliation_id})."
            )
        if self.status not in ('draft', 'in_progress'):
            raise ValidationError("Cannot modify a completed/approved reconciliation.")

        journal_line.is_bank_reconciled = True
        journal_line.bank_reconciliation = self
        journal_line.save(update_fields=['is_bank_reconciled', 'bank_reconciliation'])

    def unclear_line(self, journal_line):
        """Un-clear a journal line (only if this reconciliation owns it)."""
        if self.status not in ('draft', 'in_progress'):
            raise ValidationError("Cannot modify a completed/approved reconciliation.")
        if journal_line.bank_reconciliation_id != self.pk:
            raise ValidationError("This line is not cleared in this reconciliation.")

        journal_line.is_bank_reconciled = False
        journal_line.bank_reconciliation = None
        journal_line.save(update_fields=['is_bank_reconciled', 'bank_reconciliation'])

    def complete(self, user):
        """Mark reconciliation as complete. Difference must be zero."""
        from django.utils import timezone

        self.calculate()
        if not self.is_reconciled:
            raise ValidationError(
                f"Cannot complete: difference is AED {self.difference:.2f}. Must be zero."
            )

        if self.bank_statement:
            unmatched = self.bank_statement.unmatched_count
            if unmatched > 0:
                raise ValidationError(
                    f"Cannot complete: linked statement has {unmatched} unmatched line(s). "
                    f"All statement lines must be matched before reconciliation."
                )

        self.status = 'completed'
        self.completed_by = user
        self.completed_date = timezone.now()
        self.save()

    def approve(self, user):
        """Approve a completed reconciliation. Locks cleared lines permanently."""
        from django.utils import timezone

        if self.status != 'completed':
            raise ValidationError("Only completed reconciliations can be approved.")

        self.status = 'approved'
        self.approved_by = user
        self.approved_date = timezone.now()
        self.save()

        self.bank_account.last_reconciled_date = self.reconciliation_date
        self.bank_account.save(update_fields=['last_reconciled_date'])

        if self.bank_statement:
            for sl in self.bank_statement.lines.filter(
                reconciliation_status='matched',
                matched_journal_line__isnull=False,
            ):
                jel = sl.matched_journal_line
                if not jel.is_bank_reconciled:
                    jel.is_bank_reconciled = True
                    jel.bank_reconciliation = self
                    jel.save(update_fields=['is_bank_reconciled', 'bank_reconciliation'])
            self.bank_statement.lock(user)


class ReconciliationItem(models.Model):
    """
    Individual outstanding items in a bank reconciliation.
    Used for tracking items that haven't cleared the bank.
    """
    ITEM_TYPE_CHOICES = [
        ('outstanding_deposit', 'Outstanding Deposit'),
        ('outstanding_check', 'Outstanding Check'),
        ('bank_charge', 'Bank Charge'),
        ('bank_interest', 'Bank Interest'),
        ('fx_difference', 'FX Difference'),
        ('other', 'Other'),
    ]
    
    reconciliation = models.ForeignKey(BankReconciliation, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=30, choices=ITEM_TYPE_CHOICES)
    date = models.DateField()
    reference = models.CharField(max_length=200)
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    is_cleared = models.BooleanField(default=False)
    cleared_date = models.DateField(null=True, blank=True)
    
    # Source record links
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciliation_items'
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciliation_items'
    )
    
    class Meta:
        ordering = ['date', 'id']
    
    def __str__(self):
        return f"{self.get_item_type_display()} - {self.reference}: {self.amount}"


class OpeningBalanceEntry(BaseModel):
    """
    Opening Balance Entry - Used for company onboarding and migration.
    Creates journal entries for opening balances (GL, Bank, AR, AP).
    """
    ENTRY_TYPE_CHOICES = [
        ('gl', 'General Ledger'),
        ('bank', 'Bank Account'),
        ('ar', 'Accounts Receivable'),
        ('ap', 'Accounts Payable'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('reversed', 'Reversed'),
    ]
    
    entry_number = models.CharField(max_length=50, unique=True, editable=False)
    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPE_CHOICES)
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name='opening_balances')
    entry_date = models.DateField()
    description = models.TextField(blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Journal entry created from this opening balance
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opening_balance_entry'
    )
    
    # Totals
    total_debit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Audit
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_opening_balances'
    )
    posted_date = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-entry_date', '-created_at']
        verbose_name = 'Opening Balance Entry'
        verbose_name_plural = 'Opening Balance Entries'
    
    def __str__(self):
        return f"{self.entry_number} - {self.get_entry_type_display()}"
    
    def save(self, *args, **kwargs):
        if not self.entry_number:
            prefix = f"OB-{self.entry_type.upper()}"
            self.entry_number = generate_number(prefix, OpeningBalanceEntry, 'entry_number')
        super().save(*args, **kwargs)
    
    def calculate_totals(self):
        """Calculate totals from lines."""
        lines = self.lines.all()
        self.total_debit = sum(line.debit for line in lines)
        self.total_credit = sum(line.credit for line in lines)
        self.save(update_fields=['total_debit', 'total_credit'])
    
    @property
    def is_balanced(self):
        """Check if debits equal credits."""
        return abs(self.total_debit - self.total_credit) < Decimal('0.01')
    
    def post(self, user):
        """Post opening balance entry - creates journal entry."""
        from django.utils import timezone
        
        if self.status != 'draft':
            raise ValidationError("Only draft entries can be posted.")
        
        if not self.is_balanced:
            raise ValidationError(
                f"Entry is not balanced. Debit: {self.total_debit}, Credit: {self.total_credit}"
            )
        
        if not self.lines.exists():
            raise ValidationError("Cannot post entry without lines.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.entry_date,
            reference=self.entry_number,
            description=f"Opening Balance: {self.get_entry_type_display()} - {self.description}",
            fiscal_year=self.fiscal_year,
            entry_type='opening',
        )
        
        # Create journal lines
        for line in self.lines.all():
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=line.account,
                description=line.description,
                debit=line.debit,
                credit=line.credit,
            )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update this entry
        self.journal_entry = journal
        self.status = 'posted'
        self.posted_by = user
        self.posted_date = timezone.now()
        self.save()
        
        # Lock opening balances on accounts
        for line in self.lines.all():
            line.account.opening_balance_locked = True
            line.account.save(update_fields=['opening_balance_locked'])
        
        return journal
    
    def reverse(self, user):
        """Reverse a posted opening balance entry."""
        if self.status != 'posted':
            raise ValidationError("Only posted entries can be reversed.")
        
        if self.journal_entry:
            self.journal_entry.reverse(user, "Opening Balance Reversal")
        
        self.status = 'reversed'
        self.save(update_fields=['status'])


class OpeningBalanceLine(models.Model):
    """
    Line item for opening balance entry.
    """
    opening_balance_entry = models.ForeignKey(
        OpeningBalanceEntry,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    description = models.CharField(max_length=500, blank=True)
    
    # For AR/AP opening balances
    customer = models.ForeignKey(
        'crm.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opening_balance_lines'
    )
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opening_balance_lines'
    )
    
    # For Bank opening balances
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opening_balance_lines'
    )
    
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Reference for AR/AP
    reference_number = models.CharField(max_length=100, blank=True)
    reference_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.account.code}: D{self.debit} / C{self.credit}"
    
    def clean(self):
        if self.debit > 0 and self.credit > 0:
            raise ValidationError("A line cannot have both debit and credit amounts.")
        if self.debit == 0 and self.credit == 0:
            raise ValidationError("Either debit or credit must be greater than zero.")


class WriteOff(BaseModel):
    """
    Write-Off / Adjustment Entry.
    Used for bad debt write-offs, rounding differences, short/excess payment adjustments.
    """
    WRITEOFF_TYPE_CHOICES = [
        ('bad_debt', 'Bad Debt Write-Off'),
        ('rounding', 'Rounding Difference'),
        ('short_payment', 'Short Payment'),
        ('excess_payment', 'Excess Payment'),
        ('discount', 'Discount Given'),
        ('fx_adjustment', 'FX Adjustment'),
        ('other', 'Other Adjustment'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('posted', 'Posted'),
        ('reversed', 'Reversed'),
    ]
    
    writeoff_number = models.CharField(max_length=50, unique=True, editable=False)
    writeoff_type = models.CharField(max_length=20, choices=WRITEOFF_TYPE_CHOICES)
    writeoff_date = models.DateField()
    description = models.TextField()
    
    # Amount
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Accounts
    source_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='writeoff_source',
        help_text="Account to write off from (e.g., AR for bad debt)"
    )
    expense_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='writeoff_expense',
        help_text="Expense account to charge (e.g., Bad Debt Expense)"
    )
    
    # Optional: Link to customer/vendor
    customer = models.ForeignKey(
        'crm.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='writeoffs'
    )
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='writeoffs'
    )
    
    # Reference to original document
    reference_type = models.CharField(max_length=50, blank=True)  # invoice, bill, payment
    reference_number = models.CharField(max_length=100, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Journal entry created
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='writeoff_entry'
    )
    
    # Approval
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_writeoffs'
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    
    # Posting
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_writeoffs'
    )
    posted_date = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-writeoff_date', '-created_at']
    
    def __str__(self):
        return f"{self.writeoff_number} - {self.get_writeoff_type_display()}: {self.amount}"
    
    def save(self, *args, **kwargs):
        if not self.writeoff_number:
            self.writeoff_number = generate_number('WO', WriteOff, 'writeoff_number')
        super().save(*args, **kwargs)
    
    def approve(self, user):
        """Approve write-off."""
        from django.utils import timezone
        
        if self.status != 'draft':
            raise ValidationError("Only draft write-offs can be approved.")
        
        self.status = 'approved'
        self.approved_by = user
        self.approved_date = timezone.now()
        self.save()
    
    def post(self, user):
        """Post write-off - creates journal entry."""
        from django.utils import timezone
        
        if self.status not in ['draft', 'approved']:
            raise ValidationError("Only draft or approved write-offs can be posted.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.writeoff_date,
            reference=self.writeoff_number,
            description=f"Write-Off: {self.get_writeoff_type_display()} - {self.description}",
            entry_type='adjustment',
        )
        
        # Create journal lines (Debit Expense, Credit Source)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.expense_account,
            description=f"{self.get_writeoff_type_display()}: {self.description}",
            debit=self.amount,
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.source_account,
            description=f"{self.get_writeoff_type_display()}: {self.description}",
            credit=self.amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update this entry
        self.journal_entry = journal
        self.status = 'posted'
        self.posted_by = user
        self.posted_date = timezone.now()
        self.save()
        
        return journal
    
    def reverse(self, user):
        """Reverse a posted write-off."""
        if self.status != 'posted':
            raise ValidationError("Only posted write-offs can be reversed.")
        
        if self.journal_entry:
            self.journal_entry.reverse(user, "Write-Off Reversal")
        
        self.status = 'reversed'
        self.save(update_fields=['status'])


class ExchangeRate(BaseModel):
    """
    Exchange Rate for multi-currency support.
    Stores daily exchange rates for FX revaluation.
    """
    currency_code = models.CharField(max_length=3, help_text="ISO 4217 currency code (e.g., USD, EUR)")
    rate_date = models.DateField()
    rate = models.DecimalField(
        max_digits=12, 
        decimal_places=6, 
        help_text="Rate to convert to base currency (AED)"
    )
    source = models.CharField(max_length=100, blank=True, help_text="Rate source (e.g., UAE Central Bank)")
    
    class Meta:
        ordering = ['-rate_date', 'currency_code']
        unique_together = ['currency_code', 'rate_date']
    
    def __str__(self):
        return f"{self.currency_code}: {self.rate} ({self.rate_date})"
    
    @classmethod
    def get_rate(cls, currency_code, as_of_date=None):
        """Get exchange rate for a currency as of a date."""
        if as_of_date is None:
            as_of_date = date.today()
        
        rate = cls.objects.filter(
            currency_code=currency_code,
            rate_date__lte=as_of_date,
            is_active=True
        ).order_by('-rate_date').first()
        
        if rate:
            return rate.rate
        return Decimal('1.00')  # Default if no rate found


class FXRevaluation(BaseModel):
    """
    Foreign Exchange Revaluation at period end.
    Records unrealized FX gains/losses.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('reversed', 'Reversed'),
    ]
    
    revaluation_number = models.CharField(max_length=50, unique=True, editable=False)
    revaluation_date = models.DateField()
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT)
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT, null=True, blank=True)
    
    # FX Accounts
    fx_gain_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='fx_gain_revaluations',
        help_text="FX Gain account (Income)"
    )
    fx_loss_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='fx_loss_revaluations',
        help_text="FX Loss account (Expense)"
    )
    
    # Totals
    total_gain = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_loss = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    net_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Journal entry created
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fx_revaluation'
    )
    
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_fx_revaluations'
    )
    posted_date = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-revaluation_date']
    
    def __str__(self):
        return f"{self.revaluation_number} - {self.revaluation_date}"
    
    def save(self, *args, **kwargs):
        if not self.revaluation_number:
            self.revaluation_number = generate_number('FXR', FXRevaluation, 'revaluation_number')
        super().save(*args, **kwargs)
    
    def calculate_net(self):
        """Calculate net FX gain/loss."""
        self.net_amount = self.total_gain - self.total_loss
        self.save(update_fields=['net_amount'])
    
    def post(self, user):
        """Post FX revaluation - creates journal entry."""
        from django.utils import timezone
        
        if self.status != 'draft':
            raise ValidationError("Only draft revaluations can be posted.")
        
        if self.net_amount == 0:
            raise ValidationError("Net FX amount is zero. Nothing to post.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.revaluation_date,
            reference=self.revaluation_number,
            description=f"FX Revaluation - {self.revaluation_date}",
            fiscal_year=self.fiscal_year,
            period=self.period,
            entry_type='adjustment',
        )
        
        # Create lines based on net gain/loss
        if self.net_amount > 0:
            # Net gain: Debit account, Credit FX Gain
            for line in self.lines.all():
                if line.fx_amount > 0:
                    JournalEntryLine.objects.create(
                        journal_entry=journal,
                        account=line.account,
                        description=f"FX Revaluation: {line.account.name}",
                        debit=line.fx_amount,
                    )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=self.fx_gain_account,
                description="FX Revaluation Gain",
                credit=self.net_amount,
            )
        else:
            # Net loss: Debit FX Loss, Credit account
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=self.fx_loss_account,
                description="FX Revaluation Loss",
                debit=abs(self.net_amount),
            )
            for line in self.lines.all():
                if line.fx_amount < 0:
                    JournalEntryLine.objects.create(
                        journal_entry=journal,
                        account=line.account,
                        description=f"FX Revaluation: {line.account.name}",
                        credit=abs(line.fx_amount),
                    )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.journal_entry = journal
        self.status = 'posted'
        self.posted_by = user
        self.posted_date = timezone.now()
        self.save()
        
        return journal


class FXRevaluationLine(models.Model):
    """
    Line item for FX revaluation.
    """
    revaluation = models.ForeignKey(FXRevaluation, on_delete=models.CASCADE, related_name='lines')
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    currency_code = models.CharField(max_length=3)
    
    # Original values
    original_amount_fc = models.DecimalField(max_digits=15, decimal_places=2)  # Foreign currency
    original_rate = models.DecimalField(max_digits=12, decimal_places=6)
    original_amount_bc = models.DecimalField(max_digits=15, decimal_places=2)  # Base currency
    
    # Revalued values
    new_rate = models.DecimalField(max_digits=12, decimal_places=6)
    new_amount_bc = models.DecimalField(max_digits=15, decimal_places=2)
    
    # FX difference
    fx_amount = models.DecimalField(max_digits=15, decimal_places=2)  # Positive = gain, Negative = loss
    
    class Meta:
        ordering = ['account__code']
    
    def __str__(self):
        return f"{self.account.code}: {self.fx_amount}"
    
    def calculate_fx(self):
        """Calculate FX gain/loss."""
        self.new_amount_bc = self.original_amount_fc * self.new_rate
        self.fx_amount = self.new_amount_bc - self.original_amount_bc
        self.save(update_fields=['new_amount_bc', 'fx_amount'])


# ============ ACCOUNT MAPPING / ACCOUNT DETERMINATION ============
# SAP/Oracle-style centralized account configuration
# One-time setup - transactions use mapped accounts automatically

class AccountMapping(models.Model):
    """
    Account Mapping / Account Determination - SAP/Oracle Standard
    
    This is the central configuration for which accounts are used for different
    transaction types. Users configure this ONCE, and all transactions automatically
    use these mapped accounts.
    
    Transactions should NOT allow users to select accounts every time.
    """
    
    # Module Categories
    MODULE_CHOICES = [
        ('sales', 'Sales'),
        ('purchase', 'Purchase'),
        ('expense_claim', 'Expense Claims'),
        ('payroll', 'Payroll'),
        ('banking', 'Banking'),
        ('inventory', 'Inventory'),
        ('property', 'Property Management'),
        ('general', 'General'),
    ]
    
    # Transaction Types
    TRANSACTION_TYPE_CHOICES = [
        # Sales
        ('sales_invoice_receivable', 'Sales Invoice - Accounts Receivable'),
        ('sales_invoice_revenue', 'Sales Invoice - Sales Revenue'),
        ('sales_invoice_vat', 'Sales Invoice - VAT Payable'),
        ('sales_invoice_discount', 'Sales Invoice - Sales Discount'),
        ('customer_receipt', 'Customer Receipt - Bank'),
        ('customer_receipt_ar_clear', 'Customer Receipt - AR Clearing'),
        
        # Purchase
        ('vendor_bill_payable', 'Vendor Bill - Accounts Payable'),
        ('vendor_bill_expense', 'Vendor Bill - Default Expense'),
        ('vendor_bill_vat', 'Vendor Bill - VAT Recoverable'),
        ('vendor_payment', 'Vendor Payment - Bank'),
        ('vendor_payment_ap_clear', 'Vendor Payment - AP Clearing'),
        
        # Expense Claims
        ('expense_claim_expense', 'Expense Claim - Default Expense'),
        ('expense_claim_vat', 'Expense Claim - VAT Recoverable'),
        ('expense_claim_payable', 'Expense Claim - Employee Payable'),
        ('expense_claim_payment', 'Expense Claim Payment - Bank'),
        ('expense_claim_clear', 'Expense Claim Payment - Clear Payable'),
        
        # Payroll
        ('payroll_salary_expense', 'Payroll - Salary Expense'),
        ('payroll_salary_payable', 'Payroll - Salary Payable'),
        ('payroll_gratuity_expense', 'Payroll - Gratuity Expense'),
        ('payroll_gratuity_payable', 'Payroll - Gratuity Payable'),
        ('payroll_pension_expense', 'Payroll - Pension Expense'),
        ('payroll_pension_payable', 'Payroll - Pension Payable'),
        ('payroll_wps_deduction', 'Payroll - WPS Deduction'),
        ('payroll_payment', 'Payroll Payment - Bank'),
        ('payroll_payment_clear', 'Payroll Payment - Clear Payable'),
        
        # Banking
        ('bank_charges', 'Bank Charges Expense'),
        ('bank_interest_income', 'Bank Interest Income'),
        ('bank_interest_expense', 'Bank Interest Expense'),
        ('bank_transfer', 'Bank Transfer - Inter-bank'),
        
        # Corporate Tax (UAE)
        ('corporate_tax_expense', 'Corporate Tax - Tax Expense'),
        ('corporate_tax_payable', 'Corporate Tax - Tax Payable'),
        
        # VAT (UAE)
        ('vat_output', 'VAT - Output Tax Payable'),
        ('vat_input', 'VAT - Input Tax Recoverable'),
        ('vat_payable', 'VAT - Net Payable Account'),
        
        # Inventory
        ('inventory_asset', 'Inventory - Asset Account'),
        ('inventory_cogs', 'Inventory - Cost of Goods Sold'),
        ('inventory_grn_clearing', 'Inventory - GRN Clearing'),
        ('inventory_variance', 'Inventory - Stock Variance / Shrinkage'),
        ('inventory_damage_expense', 'Inventory - Damage Write-Off Expense'),
        ('inventory_revaluation', 'Inventory - Revaluation Gain/Loss'),
        
        # Fixed Assets
        ('fixed_asset', 'Fixed Asset - Asset Account'),
        ('fixed_asset_clearing', 'Fixed Asset - Clearing/AP'),
        ('depreciation_expense', 'Fixed Asset - Depreciation Expense'),
        ('accumulated_depreciation', 'Fixed Asset - Accumulated Depreciation'),
        ('gain_on_disposal', 'Fixed Asset - Gain on Disposal'),
        ('loss_on_disposal', 'Fixed Asset - Loss on Disposal'),
        ('disposal_proceeds', 'Fixed Asset - Disposal Proceeds'),
        
        # Projects / Cost Centers
        ('project_expense', 'Project - Default Expense'),
        ('project_revenue', 'Project - Default Revenue'),
        ('project_expense_clearing', 'Project - Expense Clearing'),
        ('project_wip', 'Project - Work in Progress'),
        
        # General
        ('fx_gain', 'Foreign Exchange Gain'),
        ('fx_loss', 'Foreign Exchange Loss'),
        ('retained_earnings', 'Retained Earnings'),
        ('opening_balance_equity', 'Opening Balance Equity'),
        ('suspense', 'Suspense Account'),
        ('rounding', 'Rounding Difference'),
        
        # PDC (Post-Dated Cheques) - Property Management
        ('pdc_control', 'PDC - Control Account (Asset)'),
        ('cheques_in_hand', 'PDC - Cheques in Hand (Asset)'),
        ('pdc_bounce_charges', 'PDC - Bounce Charges Expense'),
        ('pdc_bounce_income', 'PDC - Bounce Charges Income'),
        ('trade_debtors_property', 'Property - Trade Debtors'),
        
        # Property Management - Rental
        ('rental_income', 'Property - Rental Income'),
        ('rental_income_commercial', 'Property - Rental Income (Commercial)'),
        ('security_deposit_liability', 'Property - Security Deposit Liability'),
        ('security_deposit_forfeit', 'Property - Security Deposit Forfeit Income'),
        ('maintenance_income', 'Property - Maintenance Income'),
        ('service_charge_income', 'Property - Service Charge Income'),
    ]
    
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    transaction_type = models.CharField(max_length=50, choices=TRANSACTION_TYPE_CHOICES, unique=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='account_mappings'
    )
    description = models.CharField(max_length=200, blank=True)
    is_mandatory = models.BooleanField(default=True, help_text="If true, transaction will fail without this mapping")
    
    class Meta:
        ordering = ['module', 'transaction_type']
        verbose_name = 'Account Mapping'
        verbose_name_plural = 'Account Mappings'
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} → {self.account.code}"
    
    @classmethod
    def get_account(cls, transaction_type, raise_error=True):
        """
        Get the mapped account for a transaction type.
        
        Usage:
            ar_account = AccountMapping.get_account('sales_invoice_receivable')
        """
        try:
            mapping = cls.objects.select_related('account').get(transaction_type=transaction_type)
            return mapping.account
        except cls.DoesNotExist:
            if raise_error:
                raise ValidationError(
                    f"Account mapping not configured for '{transaction_type}'. "
                    f"Please configure in Finance → Account Mapping."
                )
            return None
    
    @classmethod
    def get_account_or_default(cls, transaction_type, default_code=None):
        """
        Get mapped account, or fallback to default account code.
        """
        account = cls.get_account(transaction_type, raise_error=False)
        if account:
            return account
        
        if default_code:
            try:
                return Account.objects.get(code=default_code, is_active=True)
            except Account.DoesNotExist:
                pass
        
        return None
    
    @classmethod
    def get_module_mappings(cls, module):
        """Get all mappings for a module."""
        return cls.objects.filter(module=module).select_related('account')
    
    @classmethod
    def is_fully_configured(cls, module):
        """Check if all mandatory mappings for a module are configured."""
        required_mappings = {
            'sales': [
                'sales_invoice_receivable', 'sales_invoice_revenue', 
                'sales_invoice_vat', 'customer_receipt'
            ],
            'purchase': [
                'vendor_bill_payable', 'vendor_bill_expense',
                'vendor_bill_vat', 'vendor_payment'
            ],
            'expense_claim': [
                'expense_claim_expense', 'expense_claim_payable',
                'expense_claim_vat', 'expense_claim_payment'
            ],
            'payroll': [
                'payroll_salary_expense', 'payroll_salary_payable',
                'payroll_payment'
            ],
        }
        
        required = required_mappings.get(module, [])
        configured = cls.objects.filter(
            module=module, 
            transaction_type__in=required
        ).values_list('transaction_type', flat=True)
        
        return set(required) <= set(configured)


class AccountingSettings(models.Model):
    """
    Global accounting settings - single record (singleton).
    Controls auto-posting behavior and other module settings.
    """
    
    # Auto-post settings per module (SAP/Oracle standard: default ON)
    auto_post_sales_invoice = models.BooleanField(
        default=True,
        help_text="Auto-post journal when sales invoice is approved"
    )
    auto_post_vendor_bill = models.BooleanField(
        default=True,
        help_text="Auto-post journal when vendor bill is approved"
    )
    auto_post_expense_claim = models.BooleanField(
        default=True,
        help_text="Auto-post journal when expense claim is approved"
    )
    auto_post_payroll = models.BooleanField(
        default=True,
        help_text="Auto-post journal when payroll is processed"
    )
    auto_post_payment = models.BooleanField(
        default=True,
        help_text="Auto-post journal when payment is confirmed"
    )
    auto_post_bank_transfer = models.BooleanField(
        default=True,
        help_text="Auto-post journal when bank transfer is confirmed"
    )
    
    # Posting controls
    require_approval_before_posting = models.BooleanField(
        default=True,
        help_text="Documents must be approved before posting to ledger"
    )
    allow_posting_to_closed_period = models.BooleanField(
        default=False,
        help_text="Allow posting to closed accounting periods (not recommended)"
    )
    
    # VAT settings (UAE)
    default_vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('5.00'),
        help_text="Default VAT rate for transactions"
    )
    vat_registration_number = models.CharField(max_length=50, blank=True)
    
    # Rounding
    round_to_fils = models.BooleanField(
        default=True,
        help_text="Round amounts to 2 decimal places (fils)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Accounting Settings'
        verbose_name_plural = 'Accounting Settings'
    
    def __str__(self):
        return "Accounting Settings"
    
    def save(self, *args, **kwargs):
        # Ensure only one record exists (singleton pattern)
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
    
    @classmethod
    def should_auto_post(cls, module):
        """Check if auto-posting is enabled for a module."""
        settings = cls.get_settings()
        mapping = {
            'sales': settings.auto_post_sales_invoice,
            'purchase': settings.auto_post_vendor_bill,
            'expense_claim': settings.auto_post_expense_claim,
            'payroll': settings.auto_post_payroll,
            'payment': settings.auto_post_payment,
            'bank_transfer': settings.auto_post_bank_transfer,
        }
        return mapping.get(module, True)
