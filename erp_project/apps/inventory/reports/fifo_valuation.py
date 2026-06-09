"""True FIFO stock valuation report from cost layers."""
from __future__ import annotations

from decimal import Decimal

from apps.inventory.models import Warehouse
from apps.inventory.models_reporting import InventoryCostLayer


def build_fifo_valuation_report(*, warehouse_id=None, category_id=None) -> dict:
    qs = InventoryCostLayer.objects.filter(
        qty_remaining__gt=0,
        item__is_active=True,
        item__item_type='product',
    ).select_related('item', 'warehouse', 'item__category')
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    if category_id:
        qs = qs.filter(item__category_id=category_id)

    grouped: dict[tuple, dict] = {}
    for layer in qs.order_by('item_id', 'warehouse_id', 'received_date', 'id'):
        key = (layer.item_id, layer.warehouse_id)
        if key not in grouped:
            grouped[key] = {
                'item_name': layer.item.name,
                'sku': layer.item.item_code,
                'warehouse': layer.warehouse.name,
                'total_qty': Decimal('0'),
                'total_value': Decimal('0'),
                'layers': [],
            }
        g = grouped[key]
        qty = layer.qty_remaining
        val = (qty * layer.unit_cost).quantize(Decimal('0.01'))
        g['total_qty'] += qty
        g['total_value'] += val
        g['layers'].append(
            {
                'received_date': layer.received_date.isoformat(),
                'qty': float(qty),
                'unit_cost': float(layer.unit_cost),
                'value': float(val),
            }
        )

    rows = []
    grand = Decimal('0')
    for g in grouped.values():
        grand += g['total_value']
        layer_text = '; '.join(
            f"{l['received_date']}: {l['qty']} @ {l['unit_cost']}" for l in g['layers']
        )
        qty = g['total_qty']
        wavg = (g['total_value'] / qty).quantize(Decimal('0.01')) if qty else Decimal('0')
        rows.append(
            {
                'item_name': g['item_name'],
                'sku': g['sku'],
                'warehouse': g['warehouse'],
                'total_qty': float(qty.quantize(Decimal('0.01'))),
                'fifo_value': float(g['total_value'].quantize(Decimal('0.01'))),
                'weighted_unit_cost': float(wavg),
                'layer_breakdown': layer_text,
            }
        )

    rows.sort(key=lambda r: r['item_name'])

    if not rows:
        return {
            'title': 'FIFO Stock Valuation Report',
            'columns': [
                {'key': 'item_name', 'label': 'Item'},
                {'key': 'sku', 'label': 'SKU'},
                {'key': 'warehouse', 'label': 'Warehouse'},
                {'key': 'total_qty', 'label': 'Total Qty', 'format': 'number'},
                {'key': 'fifo_value', 'label': 'FIFO Value (AED)', 'format': 'number'},
                {'key': 'weighted_unit_cost', 'label': 'Avg Unit Cost', 'format': 'number'},
                {'key': 'layer_breakdown', 'label': 'Layer Breakdown'},
            ],
            'rows': [],
            'summary': {
                'total_items': 0,
                'grand_total_value': 0.0,
                'note': 'No FIFO layers found. Run: python manage.py rebuild_fifo_layers',
            },
            'filters': {
                'warehouses': Warehouse.objects.filter(status='active', is_active=True).order_by('name'),
            },
        }

    return {
        'title': 'FIFO Stock Valuation Report',
        'columns': [
            {'key': 'item_name', 'label': 'Item'},
            {'key': 'sku', 'label': 'SKU'},
            {'key': 'warehouse', 'label': 'Warehouse'},
            {'key': 'total_qty', 'label': 'Total Qty', 'format': 'number'},
            {'key': 'fifo_value', 'label': 'FIFO Value (AED)', 'format': 'number'},
            {'key': 'weighted_unit_cost', 'label': 'Avg Unit Cost', 'format': 'number'},
            {'key': 'layer_breakdown', 'label': 'Layer Breakdown'},
        ],
        'rows': rows,
        'summary': {
            'total_items': len(rows),
            'grand_total_value': float(grand.quantize(Decimal('0.01'))),
        },
        'filters': {
            'warehouses': Warehouse.objects.filter(status='active', is_active=True).order_by('name'),
        },
    }
