"""Inventory reporting models: FIFO cost layers and AI forecasts."""
from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.core.models import BaseModel


class InventoryCostLayer(BaseModel):
    """FIFO cost layer remaining after inbound stock movements."""

    item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.CASCADE,
        related_name='cost_layers',
    )
    warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.CASCADE,
        related_name='cost_layers',
    )
    qty_remaining = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    unit_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    received_date = models.DateField()
    source_movement = models.ForeignKey(
        'inventory.StockMovement',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cost_layers',
    )

    class Meta:
        ordering = ['received_date', 'id']
        indexes = [
            models.Index(fields=['item', 'warehouse', 'received_date']),
        ]

    def __str__(self):
        return f'{self.item_id}@{self.warehouse_id}: {self.qty_remaining} @ {self.unit_cost}'


class InventoryForecast(BaseModel):
    """Cached AI demand forecast per item."""

    item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.CASCADE,
        related_name='forecasts',
    )
    forecast_date = models.DateField()
    forecast_30 = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    forecast_60 = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    forecast_90 = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    avg_monthly_consumption = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
    )
    confidence = models.CharField(max_length=20, default='medium')
    reasoning = models.TextField(blank=True)
    raw_response = models.TextField(blank=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-forecast_date', '-refreshed_at']
        indexes = [
            models.Index(fields=['item', '-refreshed_at']),
        ]

    def __str__(self):
        return f'Forecast {self.item_id} ({self.forecast_date})'


class InventoryAIActionSummary(BaseModel):
    """Cached OpenAI-generated action bullets for the AI forecast report."""

    cache_key = models.CharField(max_length=64, unique=True)
    bullets = models.JSONField(default=list)
    generated_at = models.DateTimeField()
    raw_response = models.TextField(blank=True)

    class Meta:
        ordering = ['-generated_at']
        verbose_name_plural = 'Inventory AI action summaries'

    def __str__(self):
        return f'AI actions ({self.cache_key[:12]}…)'
