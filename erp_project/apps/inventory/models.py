"""
Inventory Models - Categories, Warehouses, Items, Stock
With full accounting integration for:
- Stock In → Inventory Asset Ledger
- Stock Out → Cost of Goods Sold (COGS) Ledger
- Stock Adjustments → Stock Variance / Expense Ledger
"""
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.core.models import BaseModel
from apps.core.utils import generate_number


class Category(BaseModel):
    """
    Item Category model.
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True, blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subcategories'
    )
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_number('CATEGORY', Category, 'code')
        super().save(*args, **kwargs)


class StorageLocation(BaseModel):
    """
    Master list of storage shelves / bins (consumables & inventory labelling).
    """
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Storage location'
        verbose_name_plural = 'Storage locations'

    def __str__(self):
        return self.name


class Warehouse(BaseModel):
    """
    Warehouse/Location model.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True, blank=True)
    address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_number('WAREHOUSE', Warehouse, 'code')
        super().save(*args, **kwargs)


class ItemGroup(models.Model):
    """
    Named group; items can belong to many groups (M2M).
    """
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Item group'
        verbose_name_plural = 'Item groups'

    def __str__(self):
        return self.name


class Item(BaseModel):
    """
    Inventory Item model.
    """
    TYPE_CHOICES = [
        ('product', 'Product'),
        ('service', 'Service'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    
    CONDITION_CHOICES = [
        ('in_store', 'In Store / Warehouse'),
        ('in_use', 'In Use'),
        ('repair', 'Under Repair'),
        ('damaged', 'Damaged'),
    ]
    
    item_code = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='items'
    )
    item_groups = models.ManyToManyField(
        ItemGroup,
        blank=True,
        related_name='items',
        verbose_name='Groups',
    )
    item_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='product')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Pricing
    purchase_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    selling_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    minimum_selling_price = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Lowest allowed selling price for this item',
    )
    maximum_selling_price = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Highest allowed selling price for this item (0 = no cap)',
    )
    
    # Stock
    unit = models.CharField(max_length=20, default='pcs')  # pcs, kg, m, etc.
    minimum_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Condition / usage tracking
    condition_status = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default='in_store',
        help_text='Current condition: In Store, In Use, Under Repair, or Damaged'
    )
    condition_notes = models.TextField(
        blank=True,
        help_text='Notes about current condition (e.g., assigned to whom, repair details)'
    )
    condition_changed_at = models.DateTimeField(null=True, blank=True)
    
    # Tax Code - source of truth for VAT (SAP/Oracle Standard)
    tax_code = models.ForeignKey(
        'finance.TaxCode',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='inventory_items',
        help_text='Tax Code determines VAT rate. No selection = Out of Scope (0%)'
    )
    # Computed VAT rate from tax_code (read-only, for display/reporting)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))

    # Shelf / storage (consumables labelling & reports)
    storage_location_master = models.ForeignKey(
        'StorageLocation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='items',
        help_text='Optional preset from the locations master list',
    )
    storage_location = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Shelf, rack, or free-text location (e.g. Shelf A3, Rack 2)',
    )
    barcode = models.CharField(
        max_length=120,
        blank=True,
        default='',
        verbose_name='Barcode / Asset Code',
    )
    qr_code = models.ImageField(upload_to='inventory/item_qr/', blank=True, null=True)

    track_by_serial = models.BooleanField(
        default=False,
        help_text='When enabled, stock is tracked by individual model numbers received via PO.',
    )

    # Warranty / batch (warranty report)
    brand = models.CharField(max_length=120, blank=True, default='')
    serial_batch_number = models.CharField(max_length=120, blank=True, default='')
    purchase_date = models.DateField(null=True, blank=True)
    warranty_expiry = models.DateField(null=True, blank=True)
    
    class Meta:
        ordering = ['name']

    def clean(self):
        super().clean()
        if self.name:
            self.name = self.name.strip()
        name = self.name or ''
        if name:
            dup = Item.objects.filter(name__iexact=name, is_active=True)
            if self.pk:
                dup = dup.exclude(pk=self.pk)
            if dup.exists():
                raise ValidationError({'name': 'An item with this name already exists. Use a unique name.'})
        min_sp = self.minimum_selling_price or Decimal('0.00')
        max_sp = self.maximum_selling_price or Decimal('0.00')
        sp = self.selling_price or Decimal('0.00')
        if min_sp > 0 and max_sp > 0 and min_sp > max_sp:
            raise ValidationError({'maximum_selling_price': 'Maximum selling price must be greater than or equal to minimum.'})
        if min_sp > 0 and sp > 0 and sp < min_sp:
            raise ValidationError({'selling_price': 'Selling price is below the minimum selling price.'})
        if max_sp > 0 and sp > 0 and sp > max_sp:
            raise ValidationError({'selling_price': 'Selling price exceeds the maximum selling price.'})
    
    def __str__(self):
        return f"{self.item_code} - {self.name}"
    
    def save(self, *args, **kwargs):
        if self.tax_code_id:
            self.vat_rate = self.tax_code.rate
        else:
            self.vat_rate = Decimal('0.00')
        if not self.item_code:
            self.item_code = generate_number('ITEM', Item, 'item_code')
        super().save(*args, **kwargs)

    def get_storage_shelf_label(self):
        """Storage location label for QR, reports, and exports."""
        if self.storage_location_master_id:
            return self.storage_location_master.name
        return self.storage_location or ''
    
    @property
    def total_stock(self):
        """Get total stock across all warehouses."""
        # Query fresh from database to avoid caching issues
        # Use related manager with .all() to ensure fresh query
        result = self.stock_records.filter(
            warehouse__is_active=True
        ).aggregate(
            total=models.Sum('quantity')
        )['total']
        return result if result is not None else Decimal('0.00')
    
    @property
    def is_low_stock(self):
        """Check if item is below minimum stock level."""
        return self.total_stock < self.minimum_stock

    def get_issue_unit_cost(self, warehouse=None):
        """
        Unit cost for stock-out when request/line cost is zero: use master
        purchase price, else the latest positive stock-in cost for this item
        (optionally scoped to a warehouse).
        """
        if self.purchase_price and self.purchase_price > 0:
            return self.purchase_price
        qs = StockMovement.objects.filter(
            item=self,
            movement_type='in',
            unit_cost__gt=0,
        )
        if warehouse is not None:
            qs = qs.filter(warehouse=warehouse)
        last = qs.order_by('-movement_date', '-created_at').first()
        if last and last.unit_cost > 0:
            return last.unit_cost
        return Decimal('0.00')

    def change_condition(self, new_status, notes='', user=None):
        """Change item condition and log the change."""
        from django.utils import timezone
        old_status = self.condition_status
        if old_status == new_status and not notes:
            return  # No change
        self.condition_status = new_status
        self.condition_notes = notes
        self.condition_changed_at = timezone.now()
        self.save(update_fields=['condition_status', 'condition_notes', 'condition_changed_at', 'updated_at'])
        
        # Log the change
        ConditionLog.objects.create(
            item=self,
            from_status=old_status,
            to_status=new_status,
            notes=notes,
            changed_by=user,
        )


class ConditionLog(models.Model):
    """
    Tracks condition status changes for inventory items.
    Provides a full audit trail of item condition history.
    """
    item = models.ForeignKey(
        'Item',
        on_delete=models.CASCADE,
        related_name='condition_logs'
    )
    from_status = models.CharField(max_length=20, choices=Item.CONDITION_CHOICES)
    to_status = models.CharField(max_length=20, choices=Item.CONDITION_CHOICES)
    notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-changed_at']
    
    def __str__(self):
        return f"{self.item.name}: {self.get_from_status_display()} → {self.get_to_status_display()}"


class ItemSerialNumber(BaseModel):
    """Individual model/serial unit for items with track_by_serial enabled."""

    STATUS_AVAILABLE = 'available'
    STATUS_ASSIGNED = 'assigned'
    STATUS_DELIVERED = 'delivered'
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, 'Available'),
        (STATUS_ASSIGNED, 'Assigned'),
        (STATUS_DELIVERED, 'Delivered'),
    ]

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='serial_numbers',
    )
    model_number = models.CharField(max_length=120)
    receipt_line = models.ForeignKey(
        'purchase.PurchaseOrderReceiptLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='serial_numbers',
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='item_serial_numbers',
    )
    date_received = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    assigned_project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_serial_numbers',
    )
    delivered_date = models.DateField(null=True, blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delivered_item_serials',
    )

    class Meta:
        ordering = ['date_received', 'pk']
        verbose_name = 'Item serial number'
        verbose_name_plural = 'Item serial numbers'
        constraints = [
            models.UniqueConstraint(
                fields=['item', 'model_number'],
                name='inventory_itemserialnumber_item_model_unique',
            ),
        ]
        indexes = [
            models.Index(fields=['item', 'status', 'date_received']),
            models.Index(fields=['assigned_project', 'status']),
        ]

    def __str__(self):
        return f'{self.model_number} ({self.item.item_code})'


class Stock(BaseModel):
    """
    Stock level per warehouse.
    """
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='stock_records'
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='stock_records'
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        unique_together = ['item', 'warehouse']
        ordering = ['warehouse', 'item']
    
    def __str__(self):
        return f"{self.item.name} @ {self.warehouse.name}: {self.quantity}"


class StockMovement(BaseModel):
    """
    Stock movement history with full accounting integration.
    
    Accounting Entries (SAP/Oracle Standard):
    - Stock In (Purchase):  Dr Inventory Asset, Cr GRN Clearing / AP
    - Stock Out (Sales):    Dr COGS, Cr Inventory Asset
    - Stock Adjustment (+): Dr Inventory Asset, Cr Stock Variance
    - Stock Adjustment (-): Dr Stock Variance, Cr Inventory Asset
    - Transfer:             Dr Inventory (To), Cr Inventory (From) - same account
    """
    MOVEMENT_TYPE_CHOICES = [
        ('in', 'Stock In'),
        ('out', 'Stock Out'),
        ('transfer', 'Transfer'),
        ('adjustment_plus', 'Adjustment (+)'),
        ('adjustment_minus', 'Adjustment (-)'),
    ]
    
    SOURCE_CHOICES = [
        ('manual', 'Manual Entry'),
        ('purchase', 'Purchase Order'),
        ('sales', 'Sales Invoice'),
        ('production', 'Production'),
        ('return', 'Return'),
        ('opening', 'Opening Balance'),
    ]

    ADJUSTMENT_REASON_CHOICES = [
        ('shrinkage', 'Shrinkage / Count Variance'),
        ('damage', 'Damage / Write-Off'),
        ('supplier_return', 'Supplier Return'),
        ('correction', 'Internal Correction'),
        ('revaluation', 'Revaluation'),
        ('other', 'Other'),
    ]

    movement_number = models.CharField(max_length=50, unique=False, editable=False, blank=True, default='')
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='movements'
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='movements'
    )
    # For transfers
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='incoming_movements'
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    reference = models.CharField(max_length=200, blank=True)  # PO, Invoice, etc.
    notes = models.TextField(blank=True)
    adjustment_reason = models.CharField(
        max_length=20, choices=ADJUSTMENT_REASON_CHOICES,
        blank=True, default='',
        help_text='Required for adjustments — determines which GL account is hit',
    )
    movement_date = models.DateField()
    
    # Accounting link
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_movements'
    )
    posted = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-movement_date', '-created_at']
    
    def __str__(self):
        return f"{self.movement_number}: {self.get_movement_type_display()} - {self.item.name} ({self.quantity})"
    
    def save(self, *args, **kwargs):
        if not self.movement_number:
            self.movement_number = generate_number('STK-MOV', StockMovement, 'movement_number')
        
        # Calculate total cost
        if self.unit_cost and self.quantity:
            self.total_cost = self.unit_cost * abs(self.quantity)
        elif self.item and self.item.purchase_price:
            self.unit_cost = self.item.purchase_price
            self.total_cost = self.unit_cost * abs(self.quantity)
        
        super().save(*args, **kwargs)

    def execute(self, user=None, allow_zero_cost=False):
        """
        Atomic execution: update stock quantity AND post to GL together.
        In perpetual inventory, quantity and GL must always be in sync.
        If GL posting fails, the quantity update is rolled back.
        """
        from django.db import transaction as db_transaction
        from apps.finance.models import FiscalYear

        FiscalYear.validate_posting_allowed(self.movement_date)

        if self.movement_type in ('out', 'adjustment_minus') and self.unit_cost <= 0 and not allow_zero_cost:
            raise ValidationError(
                f"Stock out requires a valid unit cost (got {self.unit_cost}). "
                f"Zero-cost movements distort COGS and margins. "
                f"Set a cost or pass allow_zero_cost=True for confirmed zero-value items."
            )

        if self.movement_type in ('adjustment_plus', 'adjustment_minus') and not self.adjustment_reason:
            raise ValidationError(
                "Adjustment reason is required. Choose a reason to ensure the "
                "correct GL account is used (variance, damage, supplier return, etc.)."
            )

        with db_transaction.atomic():
            self.update_stock()
            if self.total_cost > 0:
                self.post_to_accounting(user=user)

    def update_stock(self):
        """Update stock levels based on movement type."""
        # Get or create stock record
        stock, created = Stock.objects.get_or_create(
            item=self.item,
            warehouse=self.warehouse,
            defaults={'quantity': Decimal('0.00')}
        )
        
        if self.movement_type == 'in':
            stock.quantity += self.quantity
        elif self.movement_type == 'out':
            if stock.quantity < self.quantity:
                raise ValidationError(f"Insufficient stock. Available: {stock.quantity}")
            stock.quantity -= self.quantity
        elif self.movement_type == 'adjustment_plus':
            stock.quantity += self.quantity
        elif self.movement_type == 'adjustment_minus':
            if stock.quantity < self.quantity:
                raise ValidationError(f"Insufficient stock for adjustment. Available: {stock.quantity}")
            stock.quantity -= self.quantity
        elif self.movement_type == 'transfer':
            if not self.to_warehouse:
                raise ValidationError("Transfer requires destination warehouse.")
            if stock.quantity < self.quantity:
                raise ValidationError(f"Insufficient stock for transfer. Available: {stock.quantity}")
            # Decrease from source
            stock.quantity -= self.quantity
            # Increase in destination
            to_stock, _ = Stock.objects.get_or_create(
                item=self.item,
                warehouse=self.to_warehouse,
                defaults={'quantity': Decimal('0.00')}
            )
            to_stock.quantity += self.quantity
            to_stock.save()
        
        stock.save()
    
    def post_to_accounting(self, user=None):
        """
        Post stock movement to accounting.
        Uses Account Mapping for account determination.
        
        Stock In:  Dr Inventory Asset, Cr GRN Clearing
        Stock Out: Dr COGS, Cr Inventory Asset
        Adjustment (+): Dr Inventory Asset, Cr Stock Variance
        Adjustment (-): Dr Stock Variance, Cr Inventory Asset
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping
        
        if self.posted:
            raise ValidationError("Movement already posted to accounting.")
        
        if self.total_cost <= 0:
            raise ValidationError("Movement cost must be greater than zero for accounting.")
        
        inventory_account = AccountMapping.get_account_or_default('inventory_asset', '1500')
        cogs_account = AccountMapping.get_account_or_default('inventory_cogs', '5100')
        grn_clearing = AccountMapping.get_account_or_default('inventory_grn_clearing', '2010')

        if not inventory_account:
            raise ValidationError("Inventory Asset account not configured in Account Mapping.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.movement_date,
            reference=self.movement_number,
            description=f"Stock {self.get_movement_type_display()}: {self.item.name} ({self.quantity} {self.item.unit})",
            entry_type='standard',
            source_module='inventory',
        )
        
        if self.movement_type == 'in':
            # Stock In: Dr Inventory Asset, Cr GRN Clearing
            if not grn_clearing:
                raise ValidationError("GRN Clearing account not configured.")
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=inventory_account,
                description=f"Inventory - {self.item.name}",
                debit=self.total_cost,
                credit=Decimal('0.00'),
            )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=grn_clearing,
                description=f"GRN Clearing - {self.reference or self.movement_number}",
                debit=Decimal('0.00'),
                credit=self.total_cost,
            )
        
        elif self.movement_type == 'out':
            # Stock Out: Dr COGS, Cr Inventory Asset
            if not cogs_account:
                raise ValidationError("COGS account not configured.")
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=cogs_account,
                description=f"COGS - {self.item.name}",
                debit=self.total_cost,
                credit=Decimal('0.00'),
            )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=inventory_account,
                description=f"Inventory - {self.item.name}",
                debit=Decimal('0.00'),
                credit=self.total_cost,
            )
        
        elif self.movement_type in ('adjustment_plus', 'adjustment_minus'):
            contra_account = self._get_adjustment_contra_account(AccountMapping)
            if not contra_account:
                raise ValidationError(
                    "Adjustment contra account not configured. "
                    "Set up the appropriate mapping in Finance → Account Mapping."
                )

            if self.movement_type == 'adjustment_plus':
                dr_account, cr_account = inventory_account, contra_account
            else:
                dr_account, cr_account = contra_account, inventory_account

            reason_label = self.get_adjustment_reason_display() if self.adjustment_reason else 'Adjustment'
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=dr_account,
                description=f"{reason_label} - {self.item.name}",
                debit=self.total_cost,
                credit=Decimal('0.00'),
            )
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=cr_account,
                description=f"{reason_label} - {self.item.name}",
                debit=Decimal('0.00'),
                credit=self.total_cost,
            )
        
        elif self.movement_type == 'transfer':
            # Transfer: No P&L impact, just memo entry or skip
            # In most systems, internal transfers don't create GL entries
            # unless tracking by location in GL
            journal.description = f"Stock Transfer: {self.item.name} from {self.warehouse.name} to {self.to_warehouse.name}"
            # Optional: Could create location-based entries if needed
        
        journal.calculate_totals()
        journal.post(user)
        
        self.journal_entry = journal
        self.posted = True
        self.save(update_fields=['journal_entry', 'posted'])
        
        return journal

    def _get_adjustment_contra_account(self, AccountMapping):
        """
        Resolve the contra account for an inventory adjustment based on reason.

        Reason → Account Mapping key → Default code
        ─────────────────────────────────────────────
        shrinkage       → inventory_variance      → 5200  (Stock Variance / Shrinkage)
        damage          → inventory_damage_expense → 5210  (Damage Write-Off)
        supplier_return → inventory_grn_clearing   → 2010  (AP / GRN Clearing)
        correction      → inventory_variance       → 5200  (Stock Variance)
        revaluation     → inventory_revaluation    → 5220  (Revaluation Gain/Loss)
        other / blank   → inventory_variance       → 5200  (fallback)
        """
        reason_map = {
            'shrinkage':       ('inventory_variance',       '5200'),
            'damage':          ('inventory_damage_expense', '5210'),
            'supplier_return': ('inventory_grn_clearing',   '2010'),
            'correction':      ('inventory_variance',       '5200'),
            'revaluation':     ('inventory_revaluation',    '5220'),
            'other':           ('inventory_variance',       '5200'),
        }
        mapping_key, default_code = reason_map.get(
            self.adjustment_reason, ('inventory_variance', '5200')
        )
        return AccountMapping.get_account_or_default(mapping_key, default_code)


class ConsumableRequest(BaseModel):
    """
    Medical Consumables Request for Rehab/Healthcare settings.
    
    Workflow:
    - Nurse creates request (Pending)
    - Admin approves (Approved)
    - Admin dispenses and stock reduces (Dispensed)
    - Or Admin rejects (Rejected)
    
    Note: NOT linked to patients (per rehab audit standards)
    Supports multiple line items via ConsumableRequestItem.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('dispensed', 'Dispensed'),
        ('rejected', 'Rejected'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    request_number = models.CharField(max_length=50, unique=True, editable=False)
    
    # Requested by (Nurse)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='consumable_requests'
    )
    
    # Department & Priority
    department = models.ForeignKey(
        'hr.Department',
        on_delete=models.PROTECT,
        related_name='consumable_requests',
        null=True,
        blank=True
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='consumable_requests',
        help_text='Optional project this consumable request is for.',
    )
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    required_by_date = models.DateField(null=True, blank=True)
    
    # Legacy: single item (nullable for backward compat; use items for new requests)
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name='consumable_requests',
        limit_choices_to={'item_type': 'product', 'status': 'active'},
        null=True,
        blank=True
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Warehouse to dispense from (set by admin)
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='consumable_requests'
    )
    
    # Cost tracking (hidden from nurses)
    unit_cost = models.DecimalField(
        max_digits=15, decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Cost per unit (from inventory)"
    )
    total_cost = models.DecimalField(
        max_digits=15, decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Auto-calculated: unit_cost × quantity"
    )
    
    # Dates
    request_date = models.DateField(auto_now_add=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Optional remarks (from nurse)
    remarks = models.TextField(blank=True, help_text="Optional notes from requester")
    
    # Admin notes (for rejection reason or special instructions)
    admin_notes = models.TextField(blank=True, help_text="Notes from approver/admin")
    
    # Approval tracking
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_consumable_requests'
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    
    # Dispensing tracking
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dispensed_consumable_requests'
    )
    dispensed_date = models.DateTimeField(null=True, blank=True)
    
    # Link to stock movement (created on dispense) - for legacy single-item
    stock_movement = models.ForeignKey(
        StockMovement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='consumable_requests'
    )
    
    class Meta:
        ordering = ['-request_date', '-created_at']
    
    def get_items_for_dispense(self):
        """Return line items to dispense: use items if present, else legacy item/quantity."""
        if self.items.exists():
            return [(li.item, li.quantity) for li in self.items.all()]
        if self.item and self.quantity:
            return [(self.item, self.quantity)]
        return []

    def has_serial_tracked_items(self) -> bool:
        return any(item.track_by_serial for item, _ in self.get_items_for_dispense())

    def has_project_serial_items(self) -> bool:
        return bool(self.project_id) and self.has_serial_tracked_items()
    
    def __str__(self):
        if self.item_id and self.quantity is not None:
            return f"{self.request_number}: {self.item.name} ({self.quantity})"
        return self.request_number
    
    def save(self, *args, **kwargs):
        if not self.request_number:
            self.request_number = generate_number('CR', ConsumableRequest, 'request_number')
        
        # Legacy: Auto-set unit cost and total from item/quantity
        if self.item and self.quantity:
            if not self.unit_cost:
                self.unit_cost = self.item.purchase_price or Decimal('0.00')
            self.total_cost = (self.unit_cost * self.quantity).quantize(Decimal('0.01'))
        
        super().save(*args, **kwargs)
    
    def recalculate_total(self):
        """Call after saving items to update total_cost."""
        if self.items.exists():
            self.total_cost = sum(li.total_cost for li in self.items.all())
            self.save(update_fields=['total_cost'])
    
    def approve(self, user, warehouse=None):
        """Approve the request (by admin)."""
        from django.utils import timezone
        
        if self.status != 'pending':
            raise ValidationError("Only pending requests can be approved.")
        
        self.status = 'approved'
        self.approved_by = user
        self.approved_date = timezone.now()
        
        if warehouse:
            self.warehouse = warehouse
        
        self.save()
    
    def reject(self, user, reason=''):
        """Reject the request (by admin)."""
        from django.utils import timezone
        
        if self.status not in ['pending', 'approved']:
            raise ValidationError("Only pending or approved requests can be rejected.")
        
        self.status = 'rejected'
        self.approved_by = user
        self.approved_date = timezone.now()
        self.admin_notes = reason
        self.save()
    
    def dispense(self, user, warehouse=None):
        """
        Dispense the consumable and reduce stock.
        Creates StockMovement record(s) for audit trail.
        Supports multi-item (ConsumableRequestItem) or legacy single item.
        """
        from django.utils import timezone
        from datetime import date
        
        if self.status not in ['approved', 'pending']:
            raise ValidationError("Only approved or pending requests can be dispensed.")
        
        items_to_dispense = self.get_items_for_dispense()
        if not items_to_dispense:
            raise ValidationError("No items to dispense.")

        serial_items = [(item, qty) for item, qty in items_to_dispense if item.track_by_serial]
        if serial_items and not self.project_id:
            names = ', '.join({item.name for item, _ in serial_items})
            raise ValidationError(
                f'{names} is tracked by model number. '
                'Link the request to a project, or deliver from the project page instead.'
            )

        if self.project_id:
            from apps.inventory.consumable_project_lines import sync_consumable_request_to_project_item_lines

            sync_consumable_request_to_project_item_lines(self)

        dispense_warehouse = warehouse or self.warehouse
        if not dispense_warehouse:
            # Try to find a warehouse with stock for first item
            first_item, first_qty = items_to_dispense[0]
            stock_record = Stock.objects.filter(
                item=first_item,
                quantity__gte=first_qty,
                warehouse__status='active'
            ).first()
            if stock_record:
                dispense_warehouse = stock_record.warehouse
            else:
                raise ValidationError("No warehouse specified and no warehouse found with sufficient stock.")
        
        movements = []
        line_items = list(self.items.all()) if self.items.exists() else []
        for idx, (item, qty) in enumerate(items_to_dispense):
            if item.track_by_serial:
                from apps.projects.item_delivery import deliver_items_to_project

                deliver_items_to_project(
                    self.project,
                    item,
                    qty,
                    date.today(),
                    user,
                    warehouse=dispense_warehouse,
                )
                continue

            if idx < len(line_items):
                unit_cost = line_items[idx].unit_cost
            else:
                unit_cost = self.unit_cost if self.item else (
                    item.purchase_price or Decimal('0.00')
                )
            if unit_cost <= 0:
                unit_cost = item.get_issue_unit_cost(dispense_warehouse)
            allow_zero_cost = unit_cost <= 0
            try:
                stock = Stock.objects.get(item=item, warehouse=dispense_warehouse)
                if stock.quantity < qty:
                    raise ValidationError(
                        f"Insufficient stock for {item.name} in {dispense_warehouse.name}. "
                        f"Available: {stock.quantity}, Requested: {qty}"
                    )
            except Stock.DoesNotExist:
                raise ValidationError(f"No stock record for {item.name} in {dispense_warehouse.name}")
            
            movement = StockMovement.objects.create(
                item=item,
                warehouse=dispense_warehouse,
                movement_type='out',
                source='manual',
                quantity=qty,
                unit_cost=unit_cost,
                reference=f"Consumable Request: {self.request_number}",
                notes=f"Dispensed to: {self.requested_by.get_full_name() or self.requested_by.username}",
                movement_date=date.today(),
            )
            movement.execute(user=user, allow_zero_cost=allow_zero_cost)
            movements.append(movement)
        
        self.status = 'dispensed'
        self.warehouse = dispense_warehouse
        self.dispensed_by = user
        self.dispensed_date = timezone.now()
        self.stock_movement = movements[0] if movements else None
        if not self.approved_by:
            self.approved_by = user
            self.approved_date = timezone.now()
        if self.items.exists():
            self.total_cost = sum(
                (li.total_cost or Decimal('0')) for li in self.items.all()
            ).quantize(Decimal('0.01'))
        self.save()
        
        return movements[0] if movements else None


class ConsumableRequestItem(models.Model):
    """Line items for consumable requests (multi-item support)."""
    consumable_request = models.ForeignKey(
        ConsumableRequest,
        on_delete=models.CASCADE,
        related_name='items'
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name='consumable_request_items',
        limit_choices_to={'item_type': 'product', 'status': 'active'}
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['id']
    
    def save(self, *args, **kwargs):
        if not self.unit_cost and self.item:
            self.unit_cost = self.item.purchase_price or Decimal('0.00')
        self.total_cost = (self.unit_cost * self.quantity).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class ConsumableRequestAttachment(models.Model):
    """Attachments for consumable requests."""
    consumable_request = models.ForeignKey(
        ConsumableRequest,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    file = models.FileField(upload_to='consumable_request_attachments/%Y/%m/')
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

