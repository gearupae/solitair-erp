"""Carrying cost estimates for overstock and dead stock."""
from __future__ import annotations

from decimal import Decimal

# Annual carrying rate (storage + capital) — configurable constant
ANNUAL_CARRYING_RATE = Decimal('0.22')
MONTHLY_RATE = ANNUAL_CARRYING_RATE / Decimal('12')


def carrying_cost_insight(
    *,
    overstock_value: Decimal,
    dead_value: Decimal,
) -> dict:
    locked = (overstock_value + dead_value).quantize(Decimal('0.01'))
    monthly = (locked * MONTHLY_RATE).quantize(Decimal('0.01'))
    return {
        'aed_locked': float(locked),
        'monthly_carrying_cost': float(monthly),
        'annual_carrying_cost': float((locked * ANNUAL_CARRYING_RATE).quantize(Decimal('0.01'))),
    }


def row_carrying_cost(overstock_value: float, dead_value: float) -> dict:
    ov = Decimal(str(overstock_value or 0))
    dv = Decimal(str(dead_value or 0))
    insight = carrying_cost_insight(overstock_value=ov, dead_value=dv)
    return {
        'carrying_locked_aed': insight['aed_locked'],
        'carrying_monthly_aed': insight['monthly_carrying_cost'],
        'carrying_display': (
            f"AED {insight['aed_locked']:,.0f} locked · "
            f"AED {insight['monthly_carrying_cost']:,.0f}/mo"
            if insight['aed_locked'] > 0
            else '—'
        ),
    }
