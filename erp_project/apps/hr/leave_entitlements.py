"""Annual leave rules (UAE/KSA), tier breakdown for sick leave, and entitled_days computation."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.hr.models import Employee, LeaveBalance, LeaveRequest, LeaveType


def service_days(employee: Employee, ref: date | None = None) -> int:
    ref = ref or date.today()
    if not employee.date_of_joining:
        return 0
    return max(0, (ref - employee.date_of_joining).days)


def compute_entitled_days(employee: Employee, lt: LeaveType, year: int, ref: date | None = None) -> Decimal:
    """
    Policy entitlement for LeaveBalance.entitled_days (calendar year bucket).
    Unlimited unpaid types return a large Decimal so remaining_days stays effectively unlimited.
    """
    ref = ref or date.today()
    sd = service_days(employee, ref)
    code = (lt.code or '').strip().upper()

    if lt.pay_type == 'unpaid' or not lt.is_paid:
        if lt.days_allowed is None or lt.days_allowed == 0:
            return Decimal('99999.00')

    if employee.is_in_probation and not lt.probation_allowed:
        return Decimal('0')

    if code not in ('UAE_ANNUAL', 'KSA_ANNUAL'):
        if lt.min_service_days and sd < lt.min_service_days:
            return Decimal('0')

    if code == 'UAE_ANNUAL':
        if sd < 180:
            return Decimal('0')
        if sd < 365:
            raw = (Decimal(sd - 180) / Decimal(30)) * Decimal(2)
            return raw.quantize(Decimal('0.01'))
        return Decimal('30')

    if code == 'KSA_ANNUAL':
        yrs = Decimal(sd) / Decimal(365)
        return Decimal('21') if yrs < Decimal('5') else Decimal('30')

    if lt.days_allowed is None:
        return Decimal('99999.00')

    return Decimal(str(int(lt.days_allowed)))


def sick_usage_working_days(employee: Employee, lt: LeaveType, year: int) -> Decimal:
    """Approved + pending sick leave working days in year for tier breakdown."""
    agg = (
        LeaveRequest.objects.filter(
            employee=employee,
            leave_type=lt,
            start_date__year=year,
            is_active=True,
            status__in=['pending_manager', 'pending_hr', 'approved'],
        ).aggregate(t=Sum('requested_working_days'))['t']
    )
    return (agg or Decimal('0')).quantize(Decimal('0.01'))


def tier_breakdown_uae_sick(used_wd: Decimal) -> dict[str, Any]:
    """UAE sick 90d: full 1–15, half 16–45 (30 wd), unpaid 46–90 (45 wd)."""
    u = float(used_wd)
    full_used = min(u, 15.0)
    u2 = max(0.0, u - 15.0)
    half_used = min(u2, 30.0)
    u3 = max(0.0, u - 45.0)
    unpaid_used = min(u3, 45.0)
    return {
        'full_remaining': max(0.0, 15.0 - full_used),
        'half_remaining': max(0.0, 30.0 - half_used),
        'unpaid_remaining': max(0.0, 45.0 - unpaid_used),
    }


def tier_breakdown_ksa_sick(used_wd: Decimal) -> dict[str, Any]:
    """KSA sick 120d: full 1–30, 31–90 at 75%, 91–120 unpaid."""
    u = float(used_wd)
    full_used = min(u, 30.0)
    u2 = max(0.0, u - 30.0)
    pct75_used = min(u2, 60.0)
    u3 = max(0.0, u - 90.0)
    unpaid_used = min(u3, 30.0)
    return {
        'full_remaining': max(0.0, 30.0 - full_used),
        'pct75_remaining': max(0.0, 60.0 - pct75_used),
        'unpaid_remaining': max(0.0, 30.0 - unpaid_used),
    }


def tier_breakdown_for_type(employee: Employee, lt: LeaveType, year: int) -> dict[str, Any]:
    code = (lt.code or '').strip().upper()
    used = sick_usage_working_days(employee, lt, year)
    if code == 'UAE_SICK':
        return tier_breakdown_uae_sick(used)
    if code == 'KSA_SICK':
        return tier_breakdown_ksa_sick(used)
    return {
        'full_remaining': None,
        'half_remaining': None,
        'unpaid_remaining': None,
        'pct75_remaining': None,
    }


def apply_carry_forward_cap(lt: LeaveType, carried: Decimal) -> Decimal:
    cap = getattr(lt, 'carry_forward_cap', None)
    if cap is None:
        return carried
    return min(carried, Decimal(str(cap)))


def refresh_carried_forward_placeholder(lb: LeaveBalance, lt: LeaveType) -> Decimal:
    """Keep stored carried_forward but cap by leave type policy."""
    raw = lb.carried_forward or Decimal('0')
    return apply_carry_forward_cap(lt, raw)
