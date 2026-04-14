"""
Stock Take (stock verification) — standalone module; no FK to inventory items.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class StockTakeSession(models.Model):
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    client_name = models.CharField(max_length=200)
    location = models.CharField(max_length=200)
    session_date = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_take_sessions',
    )
    public_scan_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text='Secret token for the public camera page (no login).',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.client_name} @ {self.location} ({self.session_date})"


class StockTakeLine(models.Model):
    """Expected row from upload; actual_qty updated by scans."""
    session = models.ForeignKey(
        StockTakeSession,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    sku = models.CharField(max_length=120, db_index=True)
    scan_code = models.CharField(
        max_length=200,
        blank=True,
        default='',
        db_index=True,
        help_text='Barcode / QR / label value scanned at the shelf. If empty, scans match SKU.',
    )
    item_name = models.CharField(max_length=300)
    expected_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    actual_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        ordering = ['sku']
        constraints = [
            models.UniqueConstraint(fields=['session', 'sku'], name='uniq_stocktake_session_sku'),
        ]

    @property
    def variance(self):
        from decimal import Decimal
        return self.actual_qty - self.expected_qty


class StockTakeScanLog(models.Model):
    """Audit: every scan with resulting actual for that SKU after the scan."""
    session = models.ForeignKey(
        StockTakeSession,
        on_delete=models.CASCADE,
        related_name='scan_logs',
    )
    sku = models.CharField(max_length=120, blank=True, help_text='Matched SKU when known')
    barcode_raw = models.CharField(max_length=200)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    actual_qty_after = models.DecimalField(max_digits=14, decimal_places=3)
    matched = models.BooleanField(default=True)

    class Meta:
        ordering = ['-timestamp']


class StockTakeUnknownScan(models.Model):
    """Unknown barcode (not in expected list) with timestamp."""
    session = models.ForeignKey(
        StockTakeSession,
        on_delete=models.CASCADE,
        related_name='unknown_scans',
    )
    barcode_raw = models.CharField(max_length=200)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-timestamp']
