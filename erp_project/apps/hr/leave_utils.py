"""UAE weekend Fri–Sat working-day helpers for leave calculations."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def count_uae_working_days(start: date, end: date, *, half_day: bool = False) -> Decimal:
    """Count weekdays excluding Friday (4) and Saturday (5); Mon=0."""
    if end < start:
        return Decimal('0')
    if half_day and start == end:
        if start.weekday() in (4, 5):
            return Decimal('0')
        return Decimal('0.5')
    total = Decimal('0')
    for d in _daterange(start, end):
        if d.weekday() in (4, 5):
            continue
        total += Decimal('1')
    return total.quantize(Decimal('0.01'))


def inclusive_end_date_for_uae_working_days(start: date, target_wd: Decimal) -> date:
    """Smallest end >= start such that count_uae_working_days(start, end) >= target_wd."""
    if target_wd <= 0:
        raise ValueError('target_wd must be positive')
    end = start
    while count_uae_working_days(start, end) < target_wd:
        end += timedelta(days=1)
    return end


def compute_return_date(end: date) -> date:
    """First working day after end_date (skip Fri/Sat)."""
    d = end + timedelta(days=1)
    while d.weekday() in (4, 5):
        d += timedelta(days=1)
    return d


def ensure_leave_reference(instance) -> None:
    """Assign LR-YYYY-NNNN after row exists."""
    from django.apps import apps

    LeaveRequest = apps.get_model('hr', 'LeaveRequest')
    if not instance.pk:
        return
    if instance.reference_number and str(instance.reference_number).strip():
        return
    yr = instance.created_at.year if getattr(instance, 'created_at', None) else date.today().year
    ref = f'LR-{yr}-{instance.pk:04d}'
    LeaveRequest.objects.filter(pk=instance.pk).update(reference_number=ref)
    instance.reference_number = ref


def assign_leave_reference(instance) -> None:
    """Alias used by legacy model hook."""
    ensure_leave_reference(instance)
