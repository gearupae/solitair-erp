"""UAE-style overtime: hourly rate from basic salary only; rates by overtime type."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from apps.hr.models_extended import AttendanceRecord, AttendanceSettings


def basic_hourly_rate_uae(basic: Decimal) -> Decimal:
    """(basic_salary × 12) / 365 / 8 — basic only, no allowances."""
    b = basic or Decimal('0')
    if b <= 0:
        return Decimal('0')
    return (b * Decimal('12') / Decimal('365') / Decimal('8')).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def overtime_multipliers(att_set: AttendanceSettings) -> dict[str, Decimal]:
    return {
        'normal': (att_set.overtime_rate_normal or Decimal('1.25')).quantize(Decimal('0.01')),
        'night': (att_set.overtime_rate_night or Decimal('1.50')).quantize(Decimal('0.01')),
        'holiday': (att_set.overtime_rate_holiday or Decimal('1.50')).quantize(Decimal('0.01')),
    }


def compute_uae_overtime_allowance_for_month(
    *,
    employee,
    month_first: date,
    basic_salary: Decimal,
    att_set: AttendanceSettings,
) -> tuple[Decimal, str, Decimal]:
    """
    Sum OT pay from AttendanceRecord rows in the month (per overtime_type).
    Returns (total_amount, description, total_hours).
    """
    _, last = monthrange(month_first.year, month_first.month)
    month_end = date(month_first.year, month_first.month, last)
    hourly = basic_hourly_rate_uae(basic_salary)
    mults = overtime_multipliers(att_set)

    qs = AttendanceRecord.objects.filter(
        employee=employee,
        date__gte=month_first,
        date__lte=month_end,
        is_active=True,
        overtime_hours__gt=0,
    )

    total_pay = Decimal('0')
    total_h = Decimal('0')
    for rec in qs:
        h = rec.overtime_hours or Decimal('0')
        if h <= 0:
            continue
        ot_type = (rec.overtime_type or 'normal').lower()
        if ot_type not in mults:
            ot_type = 'normal'
        m = mults[ot_type]
        pay = (hourly * h * m).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_pay += pay
        total_h += h

    if total_pay <= 0 or hourly <= 0:
        return Decimal('0'), '', Decimal('0')

    eff = (total_pay / (hourly * total_h)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if total_h > 0 else Decimal('0')
    desc = (
        f'Overtime ({total_h} hrs @ AED {hourly:.2f}/hr × {eff})'
    )
    return total_pay.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), desc, total_h.quantize(Decimal('0.01'))
