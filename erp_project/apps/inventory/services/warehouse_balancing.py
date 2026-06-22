"""Multi-warehouse transfer suggestions."""
from __future__ import annotations

from decimal import Decimal

from apps.inventory.models import Stock, Warehouse
from apps.inventory.reports._common import active_product_items, avg_daily_consumption


def build_transfer_suggestions_report(
    *,
    warehouse_id=None,
    category_id=None,
) -> dict:
    warehouses = list(
        Warehouse.objects.filter(status='active', is_active=True).order_by('name')
    )
    if warehouse_id:
        warehouses = [w for w in warehouses if w.pk == warehouse_id]

    items = active_product_items()
    if category_id:
        items = items.filter(category_id=category_id)

    rows = []
    for item in items.order_by('name'):
        wh_data = []
        for wh in warehouses:
            on_hand = (
                Stock.objects.filter(item=item, warehouse=wh)
                .values_list('quantity', flat=True)
                .first()
            ) or Decimal('0')
            adc = avg_daily_consumption(item.pk, 90, wh.pk)
            days_cover = int(on_hand / adc) if adc > 0 else 999
            target = (adc * Decimal('14')).quantize(Decimal('0.01'))
            surplus = max(Decimal('0'), on_hand - target * Decimal('2'))
            deficit = max(Decimal('0'), target - on_hand)
            wh_data.append(
                {
                    'warehouse_id': wh.pk,
                    'warehouse': wh.name,
                    'on_hand': on_hand,
                    'surplus': surplus,
                    'deficit': deficit,
                    'adc': adc,
                    'days_cover': days_cover,
                }
            )

        donors = [w for w in wh_data if w['surplus'] > 0]
        receivers = [w for w in wh_data if w['deficit'] > 0]
        if not donors or not receivers:
            continue

        donor = max(donors, key=lambda w: w['surplus'])
        receiver = max(receivers, key=lambda w: w['deficit'])
        qty = min(donor['surplus'], receiver['deficit']).quantize(Decimal('0.01'))
        if qty <= 0:
            continue

        rows.append(
            {
                'item_name': item.name,
                'sku': item.item_code,
                'from_warehouse': donor['warehouse'],
                'to_warehouse': receiver['warehouse'],
                'suggested_qty': float(qty),
                'from_on_hand': float(donor['on_hand']),
                'to_on_hand': float(receiver['on_hand']),
                'reason': f"Surplus at {donor['warehouse']}, shortage at {receiver['warehouse']}",
            }
        )

    rows.sort(key=lambda r: -r['suggested_qty'])
    return {
        'title': 'Transfer Suggestions',
        'columns': [
            {'key': 'item_name', 'label': 'Item'},
            {'key': 'sku', 'label': 'SKU'},
            {'key': 'from_warehouse', 'label': 'From'},
            {'key': 'to_warehouse', 'label': 'To'},
            {'key': 'suggested_qty', 'label': 'Transfer Qty', 'format': 'number', 'align': 'right'},
            {'key': 'reason', 'label': 'Reason'},
        ],
        'rows': rows,
        'summary': {'suggestion_count': len(rows)},
    }
