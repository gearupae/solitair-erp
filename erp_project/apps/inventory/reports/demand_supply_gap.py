"""Demand vs Supply gap report."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.inventory.models import Category, ConsumableRequest, Stock, Warehouse
from apps.inventory.models_inter_entity import InterEntityTransfer, InterEntityTransferLine
from apps.inventory.models_reporting import InventoryForecast
from apps.purchase.models import PurchaseOrderItem

from ._common import active_product_items, avg_daily_consumption


def _pending_demand_qty(item_id: int) -> Decimal:
    """Open consumable/MR lines not fully issued."""
    pending_statuses = (
        'draft', 'submitted', 'pending', 'approved', 'partially_issued',
    )
    total = Decimal('0')
    for cr in ConsumableRequest.objects.filter(status__in=pending_statuses):
        for line in cr.items.filter(item_id=item_id):
            qty = line.quantity or Decimal('0')
            issued = line.qty_issued or Decimal('0')
            total += max(Decimal('0'), qty - issued)
    return total.quantize(Decimal('0.01'))


def _open_po_qty(item_id: int, warehouse_id=None) -> Decimal:
    qs = PurchaseOrderItem.objects.filter(
        inventory_item_id=item_id,
        purchase_order__status__in=('sent', 'confirmed', 'partial_received'),
    )
    total = Decimal('0')
    for line in qs:
        rem = (line.quantity or Decimal('0')) - (line.quantity_received or Decimal('0'))
        total += max(Decimal('0'), rem)
    return total.quantize(Decimal('0.01'))


def _in_transit_qty(item_id: int, warehouse_id=None) -> Decimal:
    qs = InterEntityTransferLine.objects.filter(
        item_id=item_id,
        transfer__status=InterEntityTransfer.STATUS_IN_TRANSIT,
    )
    if warehouse_id:
        qs = qs.filter(transfer__destination_warehouse_id=warehouse_id)
    t = qs.aggregate(t=Coalesce(Sum('quantity'), Decimal('0')))['t'] or Decimal('0')
    return t.quantize(Decimal('0.01'))


def _forecast_demand(item_id: int, period_days: int) -> Decimal:
    fc = InventoryForecast.objects.filter(item_id=item_id).order_by('-refreshed_at').first()
    if fc:
        if period_days <= 30:
            return fc.forecast_30
        if period_days <= 60:
            return fc.forecast_60
        return fc.forecast_90
    adc = avg_daily_consumption(item_id, 90)
    return (adc * Decimal(period_days)).quantize(Decimal('0.01'))


def build_demand_supply_gap_report(*, period_days=30, warehouse_id=None, category_id=None) -> dict:
    items = active_product_items()
    if category_id:
        items = items.filter(category_id=category_id)

    rows = []
    for item in items.order_by('name'):
        stock_qs = Stock.objects.filter(item=item)
        if warehouse_id:
            stock_qs = stock_qs.filter(warehouse_id=warehouse_id)
        on_hand = stock_qs.aggregate(
            t=Coalesce(Sum('quantity'), Decimal('0')),
        )['t'] or Decimal('0')

        pending = _pending_demand_qty(item.pk)
        forecast = _forecast_demand(item.pk, period_days)
        demand = (pending + forecast).quantize(Decimal('0.01'))

        open_po = _open_po_qty(item.pk, warehouse_id)
        in_transit = _in_transit_qty(item.pk, warehouse_id)
        supply = (on_hand + open_po + in_transit).quantize(Decimal('0.01'))
        gap = (demand - supply).quantize(Decimal('0.01'))
        adc = avg_daily_consumption(item.pk, 90, warehouse_id)
        coverage = (
            int(supply / adc) if adc > 0 else 999
        )

        rows.append(
            {
                'item_name': item.name,
                'sku': item.item_code,
                'demand': float(demand),
                'pending_requests': float(pending),
                'forecast_component': float(forecast),
                'supply': float(supply),
                'on_hand': float(on_hand),
                'open_po': float(open_po),
                'in_transit': float(in_transit),
                'gap': float(gap),
                'coverage_days': coverage if coverage < 999 else '',
            }
        )

    rows.sort(key=lambda r: r['gap'], reverse=True)

    return {
        'title': f'Demand vs Supply Gap Report ({period_days}d)',
        'period_days': period_days,
        'columns': [
            {'key': 'item_name', 'label': 'Item'},
            {'key': 'sku', 'label': 'SKU'},
            {'key': 'demand', 'label': f'Demand ({period_days}d)', 'format': 'number'},
            {'key': 'supply', 'label': 'Supply', 'format': 'number'},
            {'key': 'gap', 'label': 'Gap', 'format': 'number'},
            {'key': 'coverage_days', 'label': 'Coverage Days'},
            {'key': 'on_hand', 'label': 'On-Hand', 'format': 'number'},
            {'key': 'open_po', 'label': 'Open PO', 'format': 'number'},
            {'key': 'in_transit', 'label': 'In Transit', 'format': 'number'},
        ],
        'rows': rows,
        'summary': {
            'shortage_count': sum(1 for r in rows if r['gap'] > 0),
            'total_rows': len(rows),
        },
        'filters': {
            'categories': Category.objects.filter(is_active=True).order_by('name'),
            'warehouses': Warehouse.objects.filter(status='active', is_active=True).order_by('name'),
        },
    }
