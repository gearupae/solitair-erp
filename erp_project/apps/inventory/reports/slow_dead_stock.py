"""Slow-moving and dead stock report (movement-based, separate from aging)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Max

from apps.inventory.models import Category, Stock, StockMovement, Warehouse

from ._common import active_product_items


def _unit_cost(item) -> Decimal:
    if item.purchase_price and item.purchase_price > 0:
        return item.purchase_price.quantize(Decimal('0.01'))
    return Decimal('0')


def build_slow_dead_stock_report(
    *,
    warehouse_id=None,
    category_id=None,
    slow_threshold=60,
    dead_threshold=180,
) -> dict:
    today = date.today()
    items = active_product_items()
    if category_id:
        items = items.filter(category_id=category_id)

    last_move = {}
    qs = StockMovement.objects.filter(item__in=items)
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    for row in qs.values('item_id').annotate(last=Max('movement_date')):
        last_move[row['item_id']] = row['last']

    stock_qs = Stock.objects.filter(item__in=items, quantity__gt=0)
    if warehouse_id:
        stock_qs = stock_qs.filter(warehouse_id=warehouse_id)
    stock_qs = stock_qs.select_related('item', 'warehouse')

    rows = []
    slow_count = dead_count = 0
    for st in stock_qs:
        item = st.item
        last_dt = last_move.get(item.pk)
        if last_dt:
            days_since = (today - last_dt).days
        else:
            days_since = 9999
        uc = _unit_cost(item)
        value = (st.quantity * uc).quantize(Decimal('0.01'))
        if days_since >= dead_threshold:
            classification = 'Dead Stock'
            dead_count += 1
        elif days_since >= slow_threshold:
            classification = 'Slow Moving'
            slow_count += 1
        else:
            continue
        rows.append(
            {
                'item_name': item.name,
                'sku': item.item_code,
                'warehouse': st.warehouse.name if st.warehouse_id else '',
                'last_movement_date': last_dt.isoformat() if last_dt else '',
                'days_since_movement': days_since if days_since < 9999 else '',
                'on_hand_qty': float(st.quantity),
                'value': float(value),
                'classification': classification,
            }
        )

    rows.sort(key=lambda r: (-(r['days_since_movement'] or 0), r['item_name']))

    return {
        'title': 'Slow-Moving & Dead Stock Report',
        'columns': [
            {'key': 'item_name', 'label': 'Item'},
            {'key': 'sku', 'label': 'SKU'},
            {'key': 'warehouse', 'label': 'Warehouse'},
            {'key': 'last_movement_date', 'label': 'Last Movement Date'},
            {'key': 'days_since_movement', 'label': 'Days Since Movement'},
            {'key': 'on_hand_qty', 'label': 'On-Hand Qty', 'format': 'number'},
            {'key': 'value', 'label': 'Value (AED)', 'format': 'number'},
            {'key': 'classification', 'label': 'Classification'},
        ],
        'rows': rows,
        'summary': {
            'slow_moving_count': slow_count,
            'dead_stock_count': dead_count,
            'total_value': float(sum(r['value'] for r in rows)),
        },
        'filters': {
            'categories': Category.objects.filter(is_active=True).order_by('name'),
            'warehouses': Warehouse.objects.filter(status='active', is_active=True).order_by('name'),
            'slow_threshold': slow_threshold,
            'dead_threshold': dead_threshold,
        },
    }
