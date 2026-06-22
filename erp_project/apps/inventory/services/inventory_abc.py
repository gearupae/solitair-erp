"""ABC classification by annual consumption value."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.inventory.models import StockMovement
from apps.inventory.reports._common import active_product_items, avg_daily_consumption


def _unit_cost(item) -> Decimal:
    if item.purchase_price and item.purchase_price > 0:
        return item.purchase_price
    if item.selling_price and item.selling_price > 0:
        return item.selling_price * Decimal('0.7')
    return Decimal('0')


def classify_abc_for_items(items=None) -> dict[int, str]:
    """Return {item_id: 'A'|'B'|'C'} based on annual consumption value."""
    items = items or list(active_product_items())
    scored = []
    for item in items:
        adc = avg_daily_consumption(item.pk, 365)
        annual_qty = adc * Decimal('365')
        annual_value = (annual_qty * _unit_cost(item)).quantize(Decimal('0.01'))
        scored.append((item.pk, float(annual_value)))

    scored.sort(key=lambda x: x[1], reverse=True)
    total = sum(v for _, v in scored) or 1.0
    cumulative = 0.0
    out: dict[int, str] = {}
    for item_id, val in scored:
        cumulative += val
        pct = cumulative / total
        if pct <= 0.80:
            out[item_id] = 'A'
        elif pct <= 0.95:
            out[item_id] = 'B'
        else:
            out[item_id] = 'C'
    return out


def abc_badge(abc_class: str) -> str:
    return {
        'A': 'fc-badge fc-badge-red',
        'B': 'fc-badge fc-badge-orange',
        'C': 'fc-badge fc-badge-gray',
    }.get(abc_class, 'fc-badge fc-badge-gray')
