"""
Competitive Purchase Analysis — RFQ, supplier quotes, award, PO conversion.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel
from apps.core.utils import generate_number


class RFQ(BaseModel):
    STATUS_DRAFT = 'draft'
    STATUS_SENT = 'sent'
    STATUS_QUOTES_RECEIVED = 'quotes_received'
    STATUS_AWARDED = 'awarded'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SENT, 'Sent'),
        (STATUS_QUOTES_RECEIVED, 'Quotes Received'),
        (STATUS_AWARDED, 'Awarded'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    AWARD_JUSTIFICATION_CHOICES = [
        ('price', 'Lowest Price'),
        ('lead_time', 'Shortest Lead Time'),
        ('quality', 'Quality / Specification'),
        ('other', 'Other'),
    ]

    rfq_number = models.CharField(max_length=50, unique=True, editable=False)
    title = models.CharField(max_length=255)
    material_requisition = models.ForeignKey(
        'inventory.ConsumableRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rfqs',
        help_text='Optional MR to pull requested lines from.',
    )
    required_by_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.TextField(blank=True)
    award_justification = models.CharField(
        max_length=20,
        choices=AWARD_JUSTIFICATION_CHOICES,
        blank=True,
    )
    award_notes = models.TextField(blank=True)
    awarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rfqs_awarded',
    )
    awarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'RFQ'
        verbose_name_plural = 'RFQs'

    def save(self, *args, **kwargs):
        if not self.rfq_number:
            self.rfq_number = generate_number('RFQ', RFQ, 'rfq_number')
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.rfq_number} — {self.title}'


class RFQLine(models.Model):
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.PROTECT,
        related_name='rfq_lines',
        null=True,
        blank=True,
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('1'))
    unit = models.CharField(max_length=20, default='pcs')
    spec_notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.description[:80]


class SupplierQuote(BaseModel):
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name='quotes')
    supplier = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.PROTECT,
        related_name='rfq_quotes',
    )
    quote_reference = models.CharField(max_length=120, blank=True)
    validity_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=120, blank=True)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    attachment = models.FileField(upload_to='rfq_quotes/%Y/%m/', blank=True, null=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['supplier__name']
        unique_together = [('rfq', 'supplier')]

    def __str__(self):
        return f'{self.supplier.name} — {self.rfq.rfq_number}'

    @property
    def line_total(self):
        return sum((ln.line_total for ln in self.lines.all()), Decimal('0'))


class SupplierQuoteLine(models.Model):
    quote = models.ForeignKey(SupplierQuote, on_delete=models.CASCADE, related_name='lines')
    rfq_line = models.ForeignKey(RFQLine, on_delete=models.CASCADE, related_name='quote_lines')
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    available_qty = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    line_lead_time_days = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [('quote', 'rfq_line')]
        ordering = ['rfq_line__sort_order']

    @property
    def line_total(self):
        qty = self.available_qty if self.available_qty is not None else self.rfq_line.quantity
        return (self.unit_price * qty).quantize(Decimal('0.01'))

    def __str__(self):
        return f'{self.quote.supplier.name}: {self.rfq_line.description}'


class RFQAwardLine(models.Model):
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name='awards')
    rfq_line = models.ForeignKey(RFQLine, on_delete=models.CASCADE, related_name='awards')
    supplier = models.ForeignKey('purchase.Vendor', on_delete=models.PROTECT)
    supplier_quote_line = models.ForeignKey(
        SupplierQuoteLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    awarded_qty = models.DecimalField(max_digits=15, decimal_places=2)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    purchase_order = models.ForeignKey(
        'purchase.PurchaseOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rfq_award_lines',
    )

    class Meta:
        ordering = ['rfq_line__sort_order']

    def clean(self):
        if self.awarded_qty <= 0:
            raise ValidationError('Awarded quantity must be positive.')
