"""
Fixed Assets Models - Asset Register, Depreciation, Disposal
With full accounting integration:
- Asset Creation → Asset Ledger (Dr), AP/Bank (Cr)
- Depreciation → Depreciation Expense (Dr), Accumulated Depreciation (Cr)
- Disposal → Gain/Loss on Disposal, Clear Asset & Accum Depreciation
"""
import calendar
import logging
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.core.models import BaseModel
from apps.core.utils import generate_number

logger = logging.getLogger(__name__)


class AssetCategory(BaseModel):
    """
    Asset Category for grouping fixed assets.
    Defines default depreciation method and useful life.
    """
    DEPRECIATION_METHOD_CHOICES = [
        ('straight_line', 'Straight Line'),
        ('declining_balance', 'Declining Balance'),
        ('units_of_production', 'Units of Production'),
    ]
    PARTIAL_MONTH_CHOICES = [
        ('full_month', 'Full Month Depreciation'),
        ('pro_rata', 'Pro-Rata (Days-Based)'),
        ('mid_month', 'Mid-Month Convention'),
    ]
    DEPRECIATION_START_CHOICES = [
        ('acquisition_date', 'From Acquisition Date'),
        ('next_month', 'First Day of Following Month'),
    ]
    
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    
    # Default depreciation settings
    depreciation_method = models.CharField(
        max_length=50,
        choices=DEPRECIATION_METHOD_CHOICES,
        default='straight_line'
    )
    useful_life_years = models.IntegerField(default=5, help_text="Default useful life in years")
    salvage_value_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Salvage value as % of cost"
    )
    partial_month_policy = models.CharField(
        max_length=20,
        choices=PARTIAL_MONTH_CHOICES,
        default='full_month',
        help_text="How to handle depreciation in the acquisition month"
    )
    depreciation_start_policy = models.CharField(
        max_length=20,
        choices=DEPRECIATION_START_CHOICES,
        default='acquisition_date',
        help_text="When depreciation should begin"
    )
    
    # Default GL Accounts (linked to Account Mapping)
    asset_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.PROTECT,
        related_name='asset_categories',
        null=True, blank=True,
        help_text="Asset GL Account"
    )
    depreciation_expense_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.PROTECT,
        related_name='depreciation_expense_categories',
        null=True, blank=True,
        help_text="Depreciation Expense GL Account"
    )
    accumulated_depreciation_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.PROTECT,
        related_name='accum_depreciation_categories',
        null=True, blank=True,
        help_text="Accumulated Depreciation GL Account"
    )
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Asset Categories'
    
    def __str__(self):
        return f"{self.code} - {self.name}"


class FixedAsset(BaseModel):
    """
    Fixed Asset Register.
    Tracks asset acquisition, depreciation, and disposal.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('fully_depreciated', 'Fully Depreciated'),
        ('disposed', 'Disposed'),
        ('written_off', 'Written Off'),
    ]
    
    asset_number = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.PROTECT,
        related_name='assets'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Asset Details
    serial_number = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_assets'
    )
    
    # Acquisition
    acquisition_date = models.DateField()
    acquisition_cost = models.DecimalField(max_digits=15, decimal_places=2)
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assets_supplied'
    )
    purchase_invoice = models.CharField(max_length=100, blank=True)
    
    # Depreciation Settings (can override category defaults)
    depreciation_method = models.CharField(
        max_length=50,
        choices=AssetCategory.DEPRECIATION_METHOD_CHOICES,
        default='straight_line'
    )
    useful_life_years = models.IntegerField(default=5)
    useful_life_months = models.IntegerField(default=60)
    salvage_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    depreciation_start_date = models.DateField(null=True, blank=True)
    
    # Current Values
    accumulated_depreciation = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    book_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    last_depreciation_date = models.DateField(null=True, blank=True)
    
    # Disposal
    disposal_date = models.DateField(null=True, blank=True)
    disposal_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    disposal_reason = models.TextField(blank=True)
    gain_loss_on_disposal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Accounting Links
    acquisition_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='asset_acquisitions'
    )
    disposal_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='asset_disposals'
    )

    # Operational / project allocation
    OPERATIONAL_STATUS_CHOICES = [
        ('available', 'Available'),
        ('allocated', 'Allocated'),
        ('maintenance', 'Under Maintenance'),
    ]
    OWNERSHIP_TYPE_CHOICES = [
        ('owned', 'Owned'),
        ('rented', 'Rented'),
    ]
    operational_status = models.CharField(
        max_length=20,
        choices=OPERATIONAL_STATUS_CHOICES,
        default='available',
        db_index=True,
    )
    current_location = models.CharField(
        max_length=200,
        blank=True,
        help_text='Current site or warehouse location',
    )
    cost_per_hour = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Internal charge-out rate per hour for project costing',
    )
    ownership_type = models.CharField(
        max_length=20,
        choices=OWNERSHIP_TYPE_CHOICES,
        default='owned',
    )
    rental_rate_per_day = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Daily rental rate when ownership is Rented',
    )
    
    class Meta:
        ordering = ['-acquisition_date', 'name']
    
    def __str__(self):
        return f"{self.asset_number} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.asset_number:
            self.asset_number = generate_number('FA', FixedAsset, 'asset_number')

        # GL integrity: an asset cannot be activated without an acquisition journal.
        # This prevents assets from existing in the register without balance sheet support.
        if self.status == 'active' and not self.acquisition_journal_id:
            skip_gl_check = kwargs.pop('skip_gl_check', False)
            if not skip_gl_check:
                raise ValidationError(
                    "Cannot activate asset without an acquisition journal entry. "
                    "Create a GL posting (Dr Fixed Asset / Cr AP or Bank) first, "
                    "then link it via acquisition_journal before setting status to 'active'."
                )
        else:
            kwargs.pop('skip_gl_check', None)

        if not self.depreciation_start_date:
            self.depreciation_start_date = self.acquisition_date

        self.useful_life_months = self.useful_life_years * 12

        self.book_value = self.acquisition_cost - self.accumulated_depreciation

        super().save(*args, **kwargs)
    
    @property
    def depreciable_amount(self):
        """Amount subject to depreciation (cost - salvage value)."""
        return self.acquisition_cost - self.salvage_value
    
    @property
    def monthly_depreciation(self):
        """Calculate monthly depreciation amount."""
        if self.useful_life_months <= 0:
            return Decimal('0.00')
        
        if self.depreciation_method == 'straight_line':
            return (self.depreciable_amount / self.useful_life_months).quantize(Decimal('0.01'))
        elif self.depreciation_method == 'declining_balance':
            # Double declining balance
            rate = Decimal('2') / self.useful_life_months
            return (self.book_value * rate).quantize(Decimal('0.01'))
        
        return Decimal('0.00')
    
    @property
    def remaining_life_months(self):
        """Calculate remaining useful life in months."""
        if not self.depreciation_start_date:
            return self.useful_life_months
        
        months_elapsed = (date.today().year - self.depreciation_start_date.year) * 12 + \
                        (date.today().month - self.depreciation_start_date.month)
        return max(0, self.useful_life_months - months_elapsed)

    @property
    def depreciation_per_day(self):
        """Owned equipment daily depreciation for project costing."""
        if self.useful_life_months <= 0:
            return Decimal('0.00')
        return (self.depreciable_amount / (self.useful_life_months * 30)).quantize(Decimal('0.01'))

    @property
    def effective_hourly_rate(self):
        """Rate used when allocating to a project."""
        if self.cost_per_hour and self.cost_per_hour > 0:
            return self.cost_per_hour
        if self.ownership_type == 'rented' and self.rental_rate_per_day > 0:
            return (self.rental_rate_per_day / Decimal('8')).quantize(Decimal('0.01'))
        daily = self.depreciation_per_day
        if daily > 0:
            return (daily / Decimal('8')).quantize(Decimal('0.01'))
        return Decimal('0.00')

    @property
    def active_allocation(self):
        return self.allocations.filter(status='active', is_active=True).first()

    def can_allocate(self):
        if self.status not in ('active', 'fully_depreciated'):
            return False
        if self.operational_status != 'available':
            return False
        if self.maintenance_logs.filter(is_active=True, blocks_allocation=True, cleared_at__isnull=True).exists():
            return False
        return True
    
    def activate(self, user=None):
        """
        Activate asset and post acquisition journal.
        Dr Fixed Asset Account
        Cr Accounts Payable / Bank
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.status != 'draft':
            raise ValidationError("Only draft assets can be activated.")

        FiscalYear.validate_posting_allowed(self.acquisition_date)

        asset_account = self.category.asset_account or \
                       AccountMapping.get_account_or_default('fixed_asset', '1400')
        ap_account = AccountMapping.get_account_or_default('fixed_asset_clearing', '2000')
        
        if not asset_account:
            raise ValidationError("Fixed Asset account not configured.")
        if not ap_account:
            raise ValidationError("Fixed Asset Clearing/AP account not configured.")
        
        # Create acquisition journal
        journal = JournalEntry.objects.create(
            date=self.acquisition_date,
            reference=self.asset_number,
            description=f"Fixed Asset Acquisition: {self.asset_number} - {self.name}",
            entry_type='standard',
            source_module='fixed_asset',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=asset_account,
            description=f"Fixed Asset - {self.name}",
            debit=self.acquisition_cost,
            credit=Decimal('0.00'),
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f"AP/Clearing - {self.name}",
            debit=Decimal('0.00'),
            credit=self.acquisition_cost,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.acquisition_journal = journal
        self.status = 'active'
        self.book_value = self.acquisition_cost
        self.save()
        
        return journal
    
    def validate_for_depreciation(self, depreciation_date):
        """
        Pre-validate asset readiness for depreciation.
        Returns a list of human-readable error strings (empty = valid).
        """
        from apps.finance.models import AccountMapping, FiscalYear

        errors = []

        if self.status != 'active':
            errors.append(f"Status is '{self.get_status_display()}', must be 'Active'.")
            return errors

        if self.acquisition_cost <= 0:
            errors.append("Acquisition cost is zero or negative.")
        if self.useful_life_years <= 0:
            errors.append("Useful life (years) is zero.")
        if self.useful_life_months <= 0:
            errors.append("Useful life (months) is zero.")
        if not self.depreciation_method:
            errors.append("Depreciation method not set.")
        if not self.depreciation_start_date:
            errors.append("Depreciation start date not set.")
        elif depreciation_date < self.depreciation_start_date:
            errors.append(
                f"Depreciation date {depreciation_date} is before "
                f"start date {self.depreciation_start_date}."
            )

        if self.book_value <= self.salvage_value:
            errors.append(
                f"Fully depreciated (Book value {self.book_value} "
                f"<= Salvage value {self.salvage_value})."
            )

        if not errors and self.monthly_depreciation <= 0:
            errors.append("Calculated monthly depreciation is zero.")

        dep_expense = self.category.depreciation_expense_account or \
            AccountMapping.get_account('depreciation_expense', raise_error=False)
        accum_dep = self.category.accumulated_depreciation_account or \
            AccountMapping.get_account('accumulated_depreciation', raise_error=False)
        if not dep_expense:
            errors.append(
                "Depreciation Expense GL account not configured "
                "(neither on category nor in Account Mapping)."
            )
        if not accum_dep:
            errors.append(
                "Accumulated Depreciation GL account not configured "
                "(neither on category nor in Account Mapping)."
            )

        period = depreciation_date.strftime('%Y-%m')
        if AssetDepreciation.objects.filter(asset=self, period=period).exists():
            errors.append(
                f"Already depreciated for {depreciation_date.strftime('%B %Y')}."
            )

        try:
            FiscalYear.validate_posting_allowed(depreciation_date)
        except ValidationError as e:
            errors.extend(e.messages if hasattr(e, 'messages') else [str(e)])

        return errors

    def _calculate_period_depreciation(self, depreciation_date):
        """
        Calculate depreciation for a specific period, handling partial-month
        logic for the first depreciation month based on category policy.
        """
        base_amount = self.monthly_depreciation
        if base_amount <= 0:
            return Decimal('0.00')

        is_first_period = not AssetDepreciation.objects.filter(asset=self).exists()
        policy = getattr(self.category, 'partial_month_policy', 'full_month')

        if is_first_period and self.depreciation_start_date and policy != 'full_month':
            start = self.depreciation_start_date
            if (start.year == depreciation_date.year
                    and start.month == depreciation_date.month):
                if policy == 'pro_rata':
                    days_in_month = calendar.monthrange(
                        depreciation_date.year, depreciation_date.month
                    )[1]
                    days_used = days_in_month - start.day + 1
                    base_amount = (
                        base_amount * Decimal(str(days_used)) / Decimal(str(days_in_month))
                    ).quantize(Decimal('0.01'))
                elif policy == 'mid_month':
                    if start.day > 15:
                        return Decimal('0.00')

        if self.book_value - base_amount < self.salvage_value:
            base_amount = self.book_value - self.salvage_value

        return max(base_amount, Decimal('0.00'))

    def run_depreciation(self, depreciation_date, user=None, batch_run=None):
        """
        Run monthly depreciation inside a single atomic transaction.
        Dr Depreciation Expense
        Cr Accumulated Depreciation
        Creates both the journal entry and the AssetDepreciation record.
        """
        from apps.finance.models import (
            AccountMapping, FiscalYear, JournalEntry, JournalEntryLine,
        )

        errors = self.validate_for_depreciation(depreciation_date)
        if errors:
            raise ValidationError(errors)

        depreciation_amount = self._calculate_period_depreciation(depreciation_date)
        if depreciation_amount <= 0:
            raise ValidationError("No depreciation to record for this period.")

        depreciation_expense = self.category.depreciation_expense_account or \
            AccountMapping.get_account_or_default('depreciation_expense', '5300')
        accum_depreciation = self.category.accumulated_depreciation_account or \
            AccountMapping.get_account_or_default('accumulated_depreciation', '1401')

        period = depreciation_date.strftime('%Y-%m')

        with transaction.atomic():
            journal = JournalEntry.objects.create(
                date=depreciation_date,
                reference=f"DEP-{self.asset_number}-{depreciation_date.strftime('%Y%m')}",
                description=(
                    f"Depreciation: {self.asset_number} - {self.name} "
                    f"({depreciation_date.strftime('%B %Y')})"
                ),
                entry_type='standard',
                source_module='fixed_asset',
                source_id=self.pk,
                is_system_generated=True,
            )

            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=depreciation_expense,
                description=f"Depreciation Expense - {self.name}",
                debit=depreciation_amount,
                credit=Decimal('0.00'),
            )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=accum_depreciation,
                description=f"Accumulated Depreciation - {self.name}",
                debit=Decimal('0.00'),
                credit=depreciation_amount,
            )

            journal.calculate_totals()
            journal.post(user)

            self.accumulated_depreciation += depreciation_amount
            self.book_value = self.acquisition_cost - self.accumulated_depreciation
            self.last_depreciation_date = depreciation_date

            if self.book_value <= self.salvage_value:
                self.status = 'fully_depreciated'

            self.save()

            AssetDepreciation.objects.create(
                asset=self,
                depreciation_date=depreciation_date,
                period=period,
                depreciation_amount=depreciation_amount,
                accumulated_depreciation=self.accumulated_depreciation,
                book_value_after=self.book_value,
                journal_entry=journal,
                batch_run=batch_run,
            )

        logger.info(
            "Depreciation posted: asset=%s period=%s amount=%s journal=%s",
            self.asset_number, period, depreciation_amount, journal.entry_number,
        )
        return journal
    
    def dispose(self, disposal_date, disposal_amount, reason='', user=None):
        """
        Dispose/sell asset.
        Clear Asset and Accumulated Depreciation, recognize Gain/Loss.
        
        Dr Accumulated Depreciation (full)
        Dr Bank/Receivable (disposal proceeds)
        Dr/Cr Gain/Loss on Disposal
        Cr Fixed Asset (original cost)
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.status not in ['active', 'fully_depreciated']:
            raise ValidationError("Only active or fully depreciated assets can be disposed.")

        FiscalYear.validate_posting_allowed(disposal_date)

        self.gain_loss_on_disposal = disposal_amount - self.book_value
        
        # Get accounts
        asset_account = self.category.asset_account or \
                       AccountMapping.get_account_or_default('fixed_asset', '1400')
        accum_depreciation = self.category.accumulated_depreciation_account or \
                            AccountMapping.get_account_or_default('accumulated_depreciation', '1401')
        disposal_proceeds = AccountMapping.get_account_or_default('disposal_proceeds', '1200')
        
        if self.gain_loss_on_disposal >= 0:
            gain_loss_account = AccountMapping.get_account_or_default('gain_on_disposal', '4500')
        else:
            gain_loss_account = AccountMapping.get_account_or_default('loss_on_disposal', '5400')
        
        if not all([asset_account, accum_depreciation, disposal_proceeds, gain_loss_account]):
            raise ValidationError("Disposal accounts not configured.")
        
        # Create disposal journal
        journal = JournalEntry.objects.create(
            date=disposal_date,
            reference=f"DISP-{self.asset_number}",
            description=f"Asset Disposal: {self.asset_number} - {self.name}",
            entry_type='standard',
            source_module='fixed_asset',
        )
        
        # Debit Accumulated Depreciation (clear contra account)
        if self.accumulated_depreciation > 0:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=accum_depreciation,
                description=f"Clear Accumulated Depreciation - {self.name}",
                debit=self.accumulated_depreciation,
                credit=Decimal('0.00'),
            )
        
        # Debit Bank/Receivable (disposal proceeds)
        if disposal_amount > 0:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=disposal_proceeds,
                description=f"Disposal Proceeds - {self.name}",
                debit=disposal_amount,
                credit=Decimal('0.00'),
            )
        
        # Gain/Loss on Disposal
        if self.gain_loss_on_disposal > 0:
            # Gain - Credit
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=gain_loss_account,
                description=f"Gain on Disposal - {self.name}",
                debit=Decimal('0.00'),
                credit=self.gain_loss_on_disposal,
            )
        elif self.gain_loss_on_disposal < 0:
            # Loss - Debit
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=gain_loss_account,
                description=f"Loss on Disposal - {self.name}",
                debit=abs(self.gain_loss_on_disposal),
                credit=Decimal('0.00'),
            )
        
        # Credit Fixed Asset (clear original cost)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=asset_account,
            description=f"Clear Fixed Asset - {self.name}",
            debit=Decimal('0.00'),
            credit=self.acquisition_cost,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        # Update asset
        self.disposal_date = disposal_date
        self.disposal_amount = disposal_amount
        self.disposal_reason = reason
        self.disposal_journal = journal
        self.status = 'disposed'
        self.save()
        
        return journal


class DepreciationBatchRun(models.Model):
    """
    Audit record for each batch depreciation run.
    Provides traceability: who ran depreciation, when, and the outcome.
    """
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('completed_with_errors', 'Completed with Errors'),
        ('failed', 'Failed'),
    ]

    batch_number = models.CharField(max_length=50, unique=True, editable=False)
    depreciation_date = models.DateField()
    period = models.CharField(max_length=7, db_index=True, help_text="YYYY-MM")
    run_date = models.DateTimeField(auto_now_add=True)
    run_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='depreciation_runs',
    )
    total_assets = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    skip_count = models.IntegerField(default=0)
    total_depreciation = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='running')
    notes = models.TextField(blank=True)
    error_details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-run_date']

    def __str__(self):
        return f"{self.batch_number} - {self.period}"

    def save(self, *args, **kwargs):
        if not self.batch_number:
            self.batch_number = generate_number(
                'DEP-BATCH', DepreciationBatchRun, 'batch_number'
            )
        if not self.period and self.depreciation_date:
            self.period = self.depreciation_date.strftime('%Y-%m')
        super().save(*args, **kwargs)


class AssetDepreciation(models.Model):
    """
    Depreciation history for each asset.
    One record per asset per accounting period.
    """
    asset = models.ForeignKey(
        FixedAsset,
        on_delete=models.CASCADE,
        related_name='depreciation_records',
    )
    depreciation_date = models.DateField()
    period = models.CharField(
        max_length=7, db_index=True, default='', help_text="YYYY-MM"
    )
    depreciation_amount = models.DecimalField(max_digits=15, decimal_places=2)
    accumulated_depreciation = models.DecimalField(max_digits=15, decimal_places=2)
    book_value_after = models.DecimalField(max_digits=15, decimal_places=2)
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    batch_run = models.ForeignKey(
        DepreciationBatchRun,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='depreciation_records',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-depreciation_date']
        unique_together = ['asset', 'period']

    def __str__(self):
        return f"{self.asset.asset_number} - {self.period}: {self.depreciation_amount}"

    def save(self, *args, **kwargs):
        if not self.period and self.depreciation_date:
            self.period = self.depreciation_date.strftime('%Y-%m')
        super().save(*args, **kwargs)


class EquipmentAllocation(BaseModel):
    """Project-wise equipment / machinery allocation."""

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('returned', 'Returned'),
        ('transferred', 'Transferred'),
    ]

    asset = models.ForeignKey(
        FixedAsset,
        on_delete=models.CASCADE,
        related_name='allocations',
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.PROTECT,
        related_name='equipment_allocations',
    )
    start_date = models.DateField()
    expected_end_date = models.DateField(null=True, blank=True)
    actual_end_date = models.DateField(null=True, blank=True)
    rate_per_hour = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    rate_per_day = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    hours_used = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Actual hours used; auto-estimated from days if blank',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_allocations_created',
    )
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_allocations_returned',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-start_date', '-pk']

    def __str__(self):
        return f'{self.asset.asset_number} → {self.project.project_code} ({self.get_status_display()})'

    @property
    def usage_days(self):
        end = self.actual_end_date or date.today()
        if end < self.start_date:
            return 0
        return (end - self.start_date).days + 1

    def effective_hours(self):
        if self.hours_used is not None and self.hours_used >= 0:
            return self.hours_used
        return (Decimal(str(self.usage_days)) * Decimal('8')).quantize(Decimal('0.01'))

    def display_cost(self):
        hours = self.effective_hours()
        if self.rate_per_hour and self.rate_per_hour > 0:
            return (hours * self.rate_per_hour).quantize(Decimal('0.01'))
        if self.rate_per_day and self.rate_per_day > 0:
            return (Decimal(str(self.usage_days)) * self.rate_per_day).quantize(Decimal('0.01'))
        return Decimal('0.00')


class EquipmentMovementLog(models.Model):
    """Transfer / allocation movement history."""

    MOVEMENT_TYPES = [
        ('allocate', 'Allocated to Project'),
        ('return', 'Returned to Warehouse'),
        ('transfer', 'Transferred Between Projects'),
        ('maintenance', 'Sent to Maintenance'),
        ('maintenance_clear', 'Maintenance Cleared'),
    ]

    asset = models.ForeignKey(
        FixedAsset,
        on_delete=models.CASCADE,
        related_name='movement_logs',
    )
    allocation = models.ForeignKey(
        EquipmentAllocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movement_logs',
    )
    from_project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_movements_from',
    )
    to_project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_movements_to',
    )
    from_location = models.CharField(max_length=200, blank=True)
    to_location = models.CharField(max_length=200, blank=True)
    movement_type = models.CharField(max_length=30, choices=MOVEMENT_TYPES)
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)
    moved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-moved_at']

    def __str__(self):
        return f'{self.asset.asset_number} — {self.get_movement_type_display()}'


class EquipmentMaintenanceLog(BaseModel):
    """Maintenance / damage flag — blocks re-allocation until cleared."""

    asset = models.ForeignKey(
        FixedAsset,
        on_delete=models.CASCADE,
        related_name='maintenance_logs',
    )
    reason = models.TextField()
    blocks_allocation = models.BooleanField(default=True)
    flagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_maintenance_flagged',
    )
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_maintenance_cleared',
    )
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.asset.asset_number} maintenance'


class RentalCostLedger(BaseModel):
    """Rental / usage cost snapshot per allocation (display & audit; not posted to project P&L)."""

    allocation = models.OneToOneField(
        EquipmentAllocation,
        on_delete=models.CASCADE,
        related_name='cost_ledger',
    )
    hours_used = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    days_used = models.IntegerField(default=0)
    rate_per_hour = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    rate_per_day = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    cost_type = models.CharField(max_length=20, default='owned')  # owned | rented

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.allocation} — AED {self.total_cost}'
