"""
Inter-entity inventory transfers between legal entities (Company model).
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel
from apps.core.utils import generate_number


class InterEntityVatTreatment(models.Model):
    """Configurable VAT rules for inter-entity transfers (accountant sign-off)."""

    CODE_CHOICES = [
        ('intra_emirate', 'Intra-emirate'),
        ('inter_emirate', 'Inter-emirate'),
        ('designated_zone', 'Designated Zone'),
        ('gcc_cross_border', 'GCC Cross-border'),
        ('out_of_scope', 'Out of Scope'),
    ]

    code = models.CharField(max_length=30, choices=CODE_CHOICES, unique=True)
    name = models.CharField(max_length=120)
    vat_rate_override = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Leave blank to use item tax code rate.',
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.name


class InterEntityTransfer(BaseModel):
    STATUS_DRAFT = 'draft'
    STATUS_APPROVED = 'approved'
    STATUS_IN_TRANSIT = 'in_transit'
    STATUS_RECEIVED = 'received'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_IN_TRANSIT, 'In Transit'),
        (STATUS_RECEIVED, 'Received'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PRICING_COST = 'cost'
    PRICING_MARKUP = 'cost_markup'
    PRICING_AGREED = 'agreed'
    PRICING_CHOICES = [
        (PRICING_COST, 'At Cost'),
        (PRICING_MARKUP, 'Cost + Markup %'),
        (PRICING_AGREED, 'Agreed Price'),
    ]

    transfer_number = models.CharField(max_length=50, unique=True, editable=False)
    source_entity = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.PROTECT,
        related_name='outbound_inter_transfers',
    )
    source_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='outbound_inter_transfers',
    )
    destination_entity = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.PROTECT,
        related_name='inbound_inter_transfers',
    )
    destination_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='inbound_inter_transfers',
    )
    transfer_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    pricing_basis = models.CharField(max_length=20, choices=PRICING_CHOICES, default=PRICING_COST)
    markup_percent = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0'))
    vat_treatment = models.ForeignKey(
        InterEntityVatTreatment,
        on_delete=models.PROTECT,
        related_name='transfers',
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)
    approved_by_source = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inter_transfers_approved_source',
    )
    approved_by_dest = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inter_transfers_approved_dest',
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    source_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inter_transfer_source',
    )
    destination_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inter_transfer_destination',
    )

    class Meta:
        ordering = ['-transfer_date', '-created_at']

    def save(self, *args, **kwargs):
        if not self.transfer_number:
            self.transfer_number = generate_number('IET', InterEntityTransfer, 'transfer_number')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.transfer_number


class InterEntityTransferLine(models.Model):
    transfer = models.ForeignKey(
        InterEntityTransfer,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    item = models.ForeignKey('inventory.Item', on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    source_movement = models.ForeignKey(
        'inventory.StockMovement',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inter_transfer_source_lines',
    )
    destination_movement = models.ForeignKey(
        'inventory.StockMovement',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inter_transfer_dest_lines',
    )

    class Meta:
        ordering = ['id']

    @property
    def line_total(self):
        return (self.quantity * self.unit_price).quantize(Decimal('0.01'))

    def __str__(self):
        return f'{self.item.name} × {self.quantity}'
