"""Reorder / Low-Stock report builder."""
from __future__ import annotations

from decimal import Decimal

from apps.inventory.models import Category, Stock, Warehouse

from ._common import (
    active_product_items,
    avg_daily_consumption,
    item_lead_time_days,
)


def build_reorder_report(
    *,
    warehouse_id=None,
    category_id=None,
    below_min_only=False,
) -> dict:
    warehouses = list(
        Warehouse.objects.filter(status='active', is_active=True).order_by('name')
    )
    wh_list = [w for w in warehouses if not warehouse_id or w.pk == warehouse_id]

    rows = []
    items = active_product_items()
    if category_id:
        items = items.filter(category_id=category_id)

    for item in items.order_by('name'):
        for wh in wh_list:
            from django.db.models import Sum
            from django.db.models.functions import Coalesce

            on_hand = (
                Stock.objects.filter(item=item, warehouse=wh).aggregate(
                    t=Coalesce(Sum('quantity'), Decimal('0')),
                )['t']
                or Decimal('0')
            ).quantize(Decimal('0.01'))
            min_stock = item.minimum_stock or Decimal('0')
            reorder_qty = max(Decimal('0'), (min_stock - on_hand).quantize(Decimal('0.01')))
            if below_min_only and on_hand >= min_stock:
                continue
            if not below_min_only and on_hand <= 0 and min_stock <= 0:
                continue
            adc = avg_daily_consumption(item.pk, 90, wh.pk)
            lead = item_lead_time_days(item.pk)
            safety = (adc * Decimal(lead) * Decimal('1.5')).quantize(Decimal('0.01'))
            suggested = max(reorder_qty, safety).quantize(Decimal('0.01'))
            rows.append(
                {
                    'item_name': item.name,
                    'sku': item.item_code,
                    'warehouse': wh.name,
                    'on_hand': float(on_hand),
                    'min_stock': float(min_stock),
                    'reorder_qty': float(reorder_qty),
                    'avg_daily_consumption': float(adc),
                    'lead_time_days': lead,
                    'suggested_order_qty': float(suggested),
                }
            )

    return {
        'title': 'Reorder / Low-Stock Report',
        'columns': [
            {'key': 'item_name', 'label': 'Item'},
            {'key': 'sku', 'label': 'SKU'},
            {'key': 'warehouse', 'label': 'Warehouse'},
            {'key': 'on_hand', 'label': 'On-Hand', 'format': 'number'},
            {'key': 'min_stock', 'label': 'Min Stock', 'format': 'number'},
            {'key': 'reorder_qty', 'label': 'Reorder Qty', 'format': 'number'},
            {'key': 'avg_daily_consumption', 'label': 'Avg Daily Consumption (90d)', 'format': 'number'},
            {'key': 'lead_time_days', 'label': 'Lead Time Days'},
            {'key': 'suggested_order_qty', 'label': 'Suggested Order Qty', 'format': 'number'},
        ],
        'rows': rows,
        'summary': {
            'total_rows': len(rows),
            'below_min': sum(1 for r in rows if r['reorder_qty'] > 0),
        },
        'filters': {
            'categories': Category.objects.filter(is_active=True).order_by('name'),
            'warehouses': warehouses,
        },
    }
