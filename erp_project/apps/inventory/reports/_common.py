"""Shared helpers for inventory report builders."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.inventory.models import Item, Stock, StockMovement


DEFAULT_LEAD_TIME_DAYS = 14


def active_product_items():
    return Item.objects.filter(
        is_active=True,
        item_type='product',
        status='active',
    ).select_related('category')


def stock_by_item_warehouse(warehouse_id=None) -> dict[tuple[int, int | None], Decimal]:
    qs = Stock.objects.filter(item__is_active=True, item__item_type='product')
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    out: dict[tuple[int, int | None], Decimal] = {}
    for row in qs.values('item_id', 'warehouse_id').annotate(
        total=Coalesce(Sum('quantity'), Decimal('0')),
    ):
        out[(row['item_id'], row['warehouse_id'])] = (row['total'] or Decimal('0')).quantize(
            Decimal('0.01')
        )
    return out


def avg_daily_consumption(item_id: int, days: int = 90, warehouse_id=None) -> Decimal:
    since = date.today() - timedelta(days=days)
    qs = StockMovement.objects.filter(
        item_id=item_id,
        movement_type='out',
        movement_date__gte=since,
    )
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    total = qs.aggregate(t=Coalesce(Sum('quantity'), Decimal('0')))['t'] or Decimal('0')
    if days <= 0:
        return Decimal('0')
    return (total / Decimal(days)).quantize(Decimal('0.0001'))


def item_lead_time_days(item_id: int) -> int:
    """Average PO order-to-receipt days for item, else default."""
    from apps.purchase.models import PurchaseOrderItem, PurchaseOrderReceiptLine

    lines = PurchaseOrderReceiptLine.objects.filter(
        purchase_order_item__inventory_item_id=item_id,
    ).select_related('receipt__purchase_order', 'purchase_order_item__purchase_order')
    deltas = []
    for ln in lines[:50]:
        po = ln.receipt.purchase_order
        if po and po.order_date and ln.receipt.received_on:
            deltas.append((ln.receipt.received_on - po.order_date).days)
    if deltas:
        return max(1, int(sum(deltas) / len(deltas)))
    return DEFAULT_LEAD_TIME_DAYS
