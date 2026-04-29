"""Leave overlap counts and payroll deductions (unpaid / half / tiered sick)."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from apps.hr.leave_context_service import location_matches_employee
from apps.hr.leave_utils import _daterange, count_uae_working_days
from apps.hr.models import LeaveRequest, LeaveType


def _month_bounds(month_first: date) -> tuple[date, date]:
    _, last = monthrange(month_first.year, month_first.month)
    return month_first, date(month_first.year, month_first.month, last)


def _approved_leave_qs(employee, month_first: date, month_end: date):
    return LeaveRequest.objects.filter(
        employee=employee,
        status='approved',
        is_active=True,
        start_date__lte=month_end,
        end_date__gte=month_first,
    ).select_related('leave_type')


def unpaid_leave_working_days_in_month_strict(employee, month_first: date) -> Decimal:
    """Only LeaveType.pay_type == 'unpaid' (approved, overlapping month)."""
    month_end = _month_bounds(month_first)[1]
    total = Decimal('0')
    for lr in _approved_leave_qs(employee, month_first, month_end):
        lt = lr.leave_type
        if (lt.pay_type or '').lower() != 'unpaid':
            continue
        if not location_matches_employee(employee, lt):
            continue
        overlap_start = max(lr.start_date, month_first)
        overlap_end = min(lr.end_date, month_end)
        total += count_uae_working_days(overlap_start, overlap_end, half_day=lr.is_half_day)
    return total.quantize(Decimal('0.01'))


def paid_full_leave_working_days_in_month(employee, month_first: date) -> Decimal:
    month_end = _month_bounds(month_first)[1]
    total = Decimal('0')
    for lr in _approved_leave_qs(employee, month_first, month_end):
        lt = lr.leave_type
        if (lt.pay_type or '').lower() != 'full':
            continue
        if not location_matches_employee(employee, lt):
            continue
        overlap_start = max(lr.start_date, month_first)
        overlap_end = min(lr.end_date, month_end)
        total += count_uae_working_days(overlap_start, overlap_end, half_day=lr.is_half_day)
    return total.quantize(Decimal('0.01'))


def half_pay_leave_deduction(
    employee, month_first: date, daily_rate: Decimal
) -> tuple[Decimal, Decimal]:
    """Half-pay leave: deduct 50% of daily rate per overlapping working day."""
    month_end = _month_bounds(month_first)[1]
    wd_total = Decimal('0')
    for lr in _approved_leave_qs(employee, month_first, month_end):
        lt = lr.leave_type
        if (lt.pay_type or '').lower() != 'half':
            continue
        if not location_matches_employee(employee, lt):
            continue
        overlap_start = max(lr.start_date, month_first)
        overlap_end = min(lr.end_date, month_end)
        wd_total += count_uae_working_days(overlap_start, overlap_end, half_day=lr.is_half_day)
    if wd_total <= 0:
        return Decimal('0'), Decimal('0')
    amt = (daily_rate * Decimal('0.5') * wd_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return amt, wd_total


def _is_payroll_working_day(d: date, loc: str) -> bool:
    """Fri/Sat off (UAE-style weekend in this codebase)."""
    if d.weekday() in (4, 5):
        return False
    return True


def tiered_sick_leave_deduction(
    employee, month_first: date, daily_rate: Decimal
) -> tuple[Decimal, int]:
    """
    Tiered sick: UAE calendar day index 16–45 → deduct 50% of daily per working day;
    KSA 31–90 → deduct 25% of daily per working day. Day index from leave start_date.
    """
    month_end = _month_bounds(month_first)[1]
    loc = (getattr(employee, 'location', None) or 'uae').lower()
    total_amt = Decimal('0')
    tier_days = 0
    for lr in _approved_leave_qs(employee, month_first, month_end):
        lt = lr.leave_type
        if (lt.pay_type or '').lower() != 'tiered':
            continue
        if not location_matches_employee(employee, lt):
            continue
        overlap_start = max(lr.start_date, month_first)
        overlap_end = min(lr.end_date, month_end)
        for d in _daterange(overlap_start, overlap_end):
            if not _is_payroll_working_day(d, loc):
                continue
            idx = (d - lr.start_date).days + 1
            if loc == 'ksa':
                if 31 <= idx <= 90:
                    total_amt += daily_rate * Decimal('0.25')
                    tier_days += 1
            else:
                if 16 <= idx <= 45:
                    total_amt += daily_rate * Decimal('0.5')
                    tier_days += 1
    total_amt = total_amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return total_amt, tier_days
