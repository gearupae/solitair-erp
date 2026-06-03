"""
Goods Receipt Note (GRN) — formal document wrapping PO goods receipt + stock-in.
PurchaseOrderReceipt is the underlying storage; GRN fields extend it.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel
from apps.core.utils import generate_number


class GoodsReceiptNote(BaseModel):
    """
    First-class GRN document. Links 1:1 to PurchaseOrderReceipt when created from PO receive,
    or stands alone for direct receipts.
    """

    STATUS_DRAFT = 'draft'
    STATUS_POSTED = 'posted'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_POSTED, 'Posted'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    grn_number = models.CharField(max_length=50, unique=True, editable=False)
    supplier = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.PROTECT,
        related_name='goods_receipt_notes',
        null=True,
        blank=True,
    )
    purchase_order = models.ForeignKey(
        'purchase.PurchaseOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn_documents',
    )
    warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='grn_documents',
    )
    received_on = models.DateField()
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='goods_receipt_notes_received',
        null=True,
        blank=True,
    )
    supplier_delivery_note = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.TextField(blank=True)
    purchase_receipt = models.OneToOneField(
        'purchase.PurchaseOrderReceipt',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn_document',
    )

    class Meta:
        ordering = ['-received_on', '-created_at']
        verbose_name = 'Goods Receipt Note'
        verbose_name_plural = 'Goods Receipt Notes'

    def save(self, *args, **kwargs):
        if not self.grn_number:
            self.grn_number = generate_number('GRN', GoodsReceiptNote, 'grn_number')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.grn_number


class GRNLine(models.Model):
    QC_PENDING = 'pending'
    QC_PASSED = 'passed'
    QC_FAILED = 'failed'
    QC_CHOICES = [
        (QC_PENDING, 'Pending'),
        (QC_PASSED, 'Passed'),
        (QC_FAILED, 'Failed'),
    ]

    grn = models.ForeignKey(
        GoodsReceiptNote,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    purchase_order_item = models.ForeignKey(
        'purchase.PurchaseOrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn_lines',
    )
    item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.PROTECT,
        related_name='grn_lines',
    )
    ordered_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    received_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    accepted_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    rejected_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    rejection_reason = models.CharField(max_length=255, blank=True)
    storage_location = models.ForeignKey(
        'inventory.StorageLocation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    unit_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    qc_status = models.CharField(max_length=20, choices=QC_CHOICES, default=QC_PENDING)
    stock_movement = models.ForeignKey(
        'inventory.StockMovement',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn_lines',
    )
    receipt_line = models.ForeignKey(
        'purchase.PurchaseOrderReceiptLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn_line',
    )

    class Meta:
        ordering = ['id']

    def clean(self):
        if self.accepted_qty + self.rejected_qty > self.received_qty:
            raise ValidationError('Accepted + rejected cannot exceed received quantity.')

    def __str__(self):
        return f'{self.grn.grn_number}: {self.item.name}'


class GRNAttachment(models.Model):
    grn = models.ForeignKey(
        GoodsReceiptNote,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    file = models.FileField(upload_to='grn_attachments/%Y/%m/')
    filename = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-uploaded_at']
