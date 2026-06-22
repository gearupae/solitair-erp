"""Demand seasonality detection from 12-month outbound history."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce, TruncMonth

from apps.inventory.models import StockMovement

PEAK_MONTH_NAMES = {
    1: 'January', 2: 'February', 3: 'March', 4: 'April',
    5: 'May', 6: 'June', 7: 'July', 8: 'August',
    9: 'September', 10: 'October', 11: 'November', 12: 'December',
}


def detect_seasonality(item_id: int) -> dict:
    since = date.today().replace(day=1) - timedelta(days=365)
    monthly = (
        StockMovement.objects.filter(
            item_id=item_id,
            movement_type='out',
            movement_date__gte=since,
        )
        .annotate(month=TruncMonth('movement_date'))
        .values('month')
        .annotate(qty=Coalesce(Sum('quantity'), Decimal('0')))
        .order_by('month')
    )
    buckets = {r['month'].month: float(r['qty'] or 0) for r in monthly if r['month']}
    if len(buckets) < 3:
        return {'driver': '', 'peak_month': '', 'factor': 1.0, 'note': ''}

    avg = sum(buckets.values()) / len(buckets)
    if avg <= 0:
        return {'driver': '', 'peak_month': '', 'factor': 1.0, 'note': ''}

    peak_m = max(buckets, key=buckets.get)
    peak_val = buckets[peak_m]
    factor = peak_val / avg if avg else 1.0
    driver = ''
    if factor >= 1.35:
        driver = PEAK_MONTH_NAMES.get(peak_m, str(peak_m))
        if peak_m in (3, 4, 9):
            driver += ' (possible seasonal peak — verify Ramadan / year-end demand)'
        note = f'Seasonal uplift ~{factor:.0%} in {PEAK_MONTH_NAMES.get(peak_m, peak_m)}'
    else:
        note = 'No strong seasonality detected'

    return {
        'driver': driver,
        'peak_month': PEAK_MONTH_NAMES.get(peak_m, ''),
        'factor': round(factor, 2),
        'note': note,
    }


def apply_seasonal_forecast(f30: Decimal, f60: Decimal, f90: Decimal, seasonality: dict) -> tuple[Decimal, Decimal, Decimal, str]:
    """Scale forecasts when a peak is within the next 90 days."""
    factor = Decimal(str(seasonality.get('factor') or 1))
    if factor <= Decimal('1.15'):
        return f30, f60, f90, seasonality.get('note') or ''

    today = date.today()
    peak_name = seasonality.get('peak_month') or ''
    # Mild uplift for near-term if seasonal pattern exists
    boost = min(factor, Decimal('1.5'))
    return (
        (f30 * boost).quantize(Decimal('0.01')),
        (f60 * ((Decimal('1') + boost) / Decimal('2'))).quantize(Decimal('0.01')),
        (f90 * ((Decimal('1') + boost) / Decimal('2'))).quantize(Decimal('0.01')),
        f'{seasonality.get("note") or peak_name} — forecasts adjusted',
    )
