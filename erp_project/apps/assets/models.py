"""
Fixed Assets Models - Asset Register, Depreciation, Disposal
With full accounting integration:
- Asset Creation → Asset Ledger (Dr), AP/Bank (Cr)
- Depreciation → Depreciation Expense (Dr), Accumulated Depreciation (Cr)
- Disposal → Gain/Loss on Disposal, Clear Asset & Accum Depreciation
"""
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from apps.core.models import BaseModel
from apps.core.utils import generate_number


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
    
    class Meta:
        ordering = ['-acquisition_date', 'name']
    
    def __str__(self):
        return f"{self.asset_number} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.asset_number:
            self.asset_number = generate_number('FA', FixedAsset, 'asset_number')
        
        # Set depreciation settings from category if not specified
        if not self.depreciation_start_date:
            self.depreciation_start_date = self.acquisition_date
        
        # Calculate useful life in months
        self.useful_life_months = self.useful_life_years * 12
        
        # Calculate book value
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
    
    def run_depreciation(self, depreciation_date, user=None):
        """
        Run monthly depreciation.
        Dr Depreciation Expense
        Cr Accumulated Depreciation
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.status not in ['active']:
            raise ValidationError("Only active assets can be depreciated.")

        FiscalYear.validate_posting_allowed(depreciation_date)

        if self.book_value <= self.salvage_value:
            self.status = 'fully_depreciated'
            self.save(update_fields=['status'])
            raise ValidationError("Asset is fully depreciated.")
        
        # Calculate depreciation
        depreciation_amount = self.monthly_depreciation
        
        # Don't depreciate below salvage value
        if self.book_value - depreciation_amount < self.salvage_value:
            depreciation_amount = self.book_value - self.salvage_value
        
        if depreciation_amount <= 0:
            raise ValidationError("No depreciation to record.")
        
        # Get accounts
        depreciation_expense = self.category.depreciation_expense_account or \
                              AccountMapping.get_account_or_default('depreciation_expense', '5300')
        accum_depreciation = self.category.accumulated_depreciation_account or \
                            AccountMapping.get_account_or_default('accumulated_depreciation', '1401')
        
        if not depreciation_expense or not accum_depreciation:
            raise ValidationError("Depreciation accounts not configured.")
        
        # Create depreciation journal
        journal = JournalEntry.objects.create(
            date=depreciation_date,
            reference=f"DEP-{self.asset_number}-{depreciation_date.strftime('%Y%m')}",
            description=f"Depreciation: {self.asset_number} - {self.name} ({depreciation_date.strftime('%B %Y')})",
            entry_type='standard',
            source_module='fixed_asset',
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
        
        # Update asset
        self.accumulated_depreciation += depreciation_amount
        self.book_value = self.acquisition_cost - self.accumulated_depreciation
        self.last_depreciation_date = depreciation_date
        
        if self.book_value <= self.salvage_value:
            self.status = 'fully_depreciated'
        
        self.save()
        
        # Create depreciation record
        AssetDepreciation.objects.create(
            asset=self,
            depreciation_date=depreciation_date,
            depreciation_amount=depreciation_amount,
            accumulated_depreciation=self.accumulated_depreciation,
            book_value_after=self.book_value,
            journal_entry=journal,
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


class AssetDepreciation(models.Model):
    """
    Depreciation history for each asset.
    """
    asset = models.ForeignKey(
        FixedAsset,
        on_delete=models.CASCADE,
        related_name='depreciation_records'
    )
    depreciation_date = models.DateField()
    depreciation_amount = models.DecimalField(max_digits=15, decimal_places=2)
    accumulated_depreciation = models.DecimalField(max_digits=15, decimal_places=2)
    book_value_after = models.DecimalField(max_digits=15, decimal_places=2)
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-depreciation_date']
        unique_together = ['asset', 'depreciation_date']
    
    def __str__(self):
        return f"{self.asset.asset_number} - {self.depreciation_date}: {self.depreciation_amount}"
