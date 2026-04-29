"""Employee leave context payload, eligibility rules, and submission validation (mirrors frontend)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.hr.leave_balance_service import get_or_compute_remaining, sync_leave_balances_for_employee
from apps.hr.leave_entitlements import tier_breakdown_for_type
from apps.hr.leave_utils import count_uae_working_days, inclusive_end_date_for_uae_working_days
from apps.hr.models import Employee, LeaveBalance, LeaveRequest, LeaveType


def is_effectively_unpaid(lt: LeaveType) -> bool:
    return (lt.pay_type or '').lower() == 'unpaid' or not lt.is_paid


def employee_years_of_service_float(emp: Employee) -> float:
    if not emp.date_of_joining:
        return 0.0
    days = (date.today() - emp.date_of_joining).days
    return round(days / 365.0, 4)


def employee_service_days_int(emp: Employee) -> int:
    if not emp.date_of_joining:
        return 0
    return max(0, (date.today() - emp.date_of_joining).days)


def once_used_for_leave_type(emp: Employee, lt: LeaveType) -> bool:
    if not lt.once_in_service:
        return False
    return LeaveRequest.objects.filter(
        employee=emp,
        leave_type=lt,
        status='approved',
        is_active=True,
    ).exists()


def location_matches_employee(emp: Employee, lt: LeaveType) -> bool:
    loc = (emp.location or '').lower()
    ltl = (lt.location or '').lower()
    if ltl == 'both':
        return True
    if loc in ('uae', 'ksa'):
        return ltl == loc
    return ltl == 'both'


def gender_matches_leave_type(emp: Employee, lt: LeaveType) -> bool:
    gr = (lt.gender_restricted or '').strip().lower()
    if not gr:
        return True
    eg = (emp.gender or '').strip().lower()
    return eg == gr


def probation_rules_pass(emp: Employee, lt: LeaveType) -> bool:
    if emp.is_in_probation and not lt.probation_allowed:
        return False
    if not emp.is_in_probation and lt.is_probation_only:
        return False
    return True


def min_service_met(emp: Employee, lt: LeaveType) -> bool:
    code = (lt.code or '').strip().upper()
    if code in ('UAE_ANNUAL', 'KSA_ANNUAL'):
        return True
    if not lt.min_service_days:
        return True
    if not emp.date_of_joining:
        return False
    days_in_service = (date.today() - emp.date_of_joining).days
    return days_in_service >= lt.min_service_days


def legacy_gender_rules_pass(emp: Employee, lt: LeaveType) -> bool:
    """LeaveType.is_gender_specific / gender_required (legacy)."""
    if not lt.is_gender_specific:
        return True
    req = (lt.gender_required or '').strip().lower()
    if not req:
        return True
    return (emp.gender or '').strip().lower() == req


def leave_type_eligible_for_dropdown(
    emp: Employee,
    lt: LeaveType,
    *,
    remaining_days: Decimal,
    once_used: bool,
) -> bool:
    if not lt.is_active:
        return False
    if not location_matches_employee(emp, lt):
        return False
    if not gender_matches_leave_type(emp, lt):
        return False
    if not legacy_gender_rules_pass(emp, lt):
        return False
    if not probation_rules_pass(emp, lt):
        return False
    if not min_service_met(emp, lt):
        return False
    if lt.once_in_service and once_used:
        return False
    if not is_effectively_unpaid(lt) and remaining_days <= 0:
        return False
    return True


def balance_snapshot_for_type(emp: Employee, lt: LeaveType, year: int) -> dict[str, Any]:
    sync_leave_balances_for_employee(emp.pk)
    rem = get_or_compute_remaining(emp, lt, year)
    lb = LeaveBalance.objects.filter(employee=emp, leave_type=lt, year=year).first()
    entitled = lb.entitled_days if lb else Decimal('0')
    used = lb.used_days if lb else Decimal('0')
    pending = lb.pending_days if lb else Decimal('0')
    ou = once_used_for_leave_type(emp, lt)
    eligible = leave_type_eligible_for_dropdown(emp, lt, remaining_days=rem, once_used=ou)
    tier = tier_breakdown_for_type(emp, lt, year)
    tier_payload = {
        'full_remaining': tier.get('full_remaining'),
        'half_remaining': tier.get('half_remaining'),
        'unpaid_remaining': tier.get('unpaid_remaining'),
        'pct75_remaining': tier.get('pct75_remaining'),
    }
    return {
        'id': lt.pk,
        'leave_type_id': lt.pk,
        'name': lt.name,
        'leave_type_name': lt.name,
        'pay_type': lt.pay_type,
        'days_allowed': lt.days_allowed,
        'entitled_days': str(entitled.quantize(Decimal('0.01'))),
        'used_days': str(used.quantize(Decimal('0.01'))),
        'pending_days': str(pending.quantize(Decimal('0.01'))),
        'remaining_days': str(rem.quantize(Decimal('0.01'))),
        'once_used': ou,
        'eligible': eligible,
        'tier_breakdown': tier_payload,
    }


def build_employee_leave_context_dict(emp: Employee) -> dict[str, Any]:
    sync_leave_balances_for_employee(emp.pk)
    year = date.today().year
    balances = []
    eligible_leave_types: list[dict[str, Any]] = []
    default_unpaid_id = None
    for lt in LeaveType.objects.filter(is_active=True).order_by('name'):
        snap = balance_snapshot_for_type(emp, lt, year)
        balances.append(snap)
        if snap.get('eligible'):
            eligible_leave_types.append(snap)
        if default_unpaid_id is None and is_effectively_unpaid(lt):
            if leave_type_eligible_for_dropdown(
                emp, lt, remaining_days=Decimal(snap['remaining_days']), once_used=snap['once_used']
            ):
                default_unpaid_id = lt.pk

    active_dates = []
    existing_leave_dates = []
    for lr in LeaveRequest.objects.filter(
        employee=emp,
        status__in=['pending_manager', 'pending_hr', 'approved'],
        is_active=True,
    ).select_related('leave_type'):
        block = {
            'start_date': lr.start_date.isoformat(),
            'end_date': lr.end_date.isoformat(),
            'status': lr.status,
            'leave_type_name': lr.leave_type.name,
        }
        active_dates.append({'start_date': lr.start_date.isoformat(), 'end_date': lr.end_date.isoformat()})
        existing_leave_dates.append(block)

    svc = employee_service_days_int(emp)
    return {
        'ok': True,
        'employee_id': emp.pk,
        'name': emp.full_name,
        'gender': emp.gender or '',
        'location': emp.location or '',
        'is_in_probation': emp.is_in_probation,
        'service_days': svc,
        'years_of_service': employee_years_of_service_float(emp),
        'religion': getattr(emp, 'religion', None) or None,
        'leave_balances': balances,
        'eligible_leave_types': eligible_leave_types,
        'active_leave_dates': active_dates,
        'existing_leave_dates': existing_leave_dates,
        'default_unpaid_leave_type_id': default_unpaid_id,
    }


def get_default_unpaid_leave_type() -> LeaveType | None:
    return (
        LeaveType.objects.filter(is_active=True)
        .filter(Q(pay_type='unpaid') | Q(is_paid=False))
        .order_by('name')
        .first()
    )


def assert_leave_type_allowed_for_employee(emp: Employee, lt: LeaveType) -> None:
    """Raises ValidationError if employee cannot use this leave type."""
    if not lt.is_active:
        raise ValidationError({'leave_type': 'Selected leave type is not active.'})
    sync_leave_balances_for_employee(emp.pk)
    rem = get_or_compute_remaining(emp, lt, date.today().year)
    ou = once_used_for_leave_type(emp, lt)
    if not leave_type_eligible_for_dropdown(emp, lt, remaining_days=rem, once_used=ou):
        if not is_effectively_unpaid(lt) and rem <= 0:
            raise ValidationError(
                {
                    'leave_type': (
                        f'Your {lt.name} balance is exhausted. '
                        'Apply for Unpaid Leave instead if available.'
                    )
                }
            )
        raise ValidationError({'leave_type': 'This leave type is not available for your profile.'})


def overlap_exists(emp: Employee, start_date: date, end_date: date, exclude_pk: int | None = None) -> LeaveRequest | None:
    qs = LeaveRequest.objects.filter(
        employee=emp,
        status__in=['pending_manager', 'pending_hr', 'approved'],
        start_date__lte=end_date,
        end_date__gte=start_date,
        is_active=True,
    ).select_related('leave_type')
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


def validate_leave_request_dates_and_balance(
    *,
    employee: Employee,
    leave_type: LeaveType,
    start_date: date,
    end_date: date,
    overflow_action: str = '',
    exclude_leave_pk: int | None = None,
    allow_past_start: bool = False,
) -> None:
    """
    Full server-side validation for create/update.
    overflow_action: '' | 'reduce' | 'split'
    """
    if end_date < start_date:
        raise ValidationError({'end_date': 'End date must be on or after start date.'})
    if not allow_past_start and start_date < date.today():
        raise ValidationError({'start_date': 'Leave start date cannot be in the past.'})

    ov = overlap_exists(employee, start_date, end_date, exclude_leave_pk)
    if ov:
        raise ValidationError(
            {
                'start_date': (
                    f'You have an existing leave request ({ov.leave_type.name}) '
                    f'from {ov.start_date} to {ov.end_date} that overlaps.'
                )
            }
        )

    assert_leave_type_allowed_for_employee(employee, leave_type)

    year = start_date.year
    requested_wd = count_uae_working_days(start_date, end_date)
    rem = get_or_compute_remaining(employee, leave_type, year)

    if is_effectively_unpaid(leave_type):
        return

    if requested_wd <= rem:
        return

    # Paid / balance-backed: exceeds remaining (caller adjusts dates before validation when using reduce)
    oa = (overflow_action or '').strip().lower()
    if oa == 'split':
        ult = get_default_unpaid_leave_type()
        if not ult:
            raise ValidationError(
                'Split requires an active Unpaid leave type. Contact HR.',
            )
        end_paid = inclusive_end_date_for_uae_working_days(start_date, rem)
        start_u = end_paid + timedelta(days=1)
        if start_u > end_date:
            raise ValidationError('Invalid split date range.')
        wd2 = count_uae_working_days(start_u, end_date)
        overflow_wd = requested_wd - rem
        if wd2 != overflow_wd:
            raise ValidationError(
                'Split validation failed: unpaid portion working days do not match.',
            )
        assert_leave_type_allowed_for_employee(employee, ult)
        return

    max_end = inclusive_end_date_for_uae_working_days(start_date, rem)
    raise ValidationError(
        {
            'end_date': (
                f'You only have {rem} days remaining for {leave_type.name}. '
                f'You requested {requested_wd} working days. Please reduce your leave duration. '
                f'Maximum allowed end date: {max_end.isoformat()}.'
            )
        }
    )


def adjusted_end_date_if_reduce(
    employee: Employee,
    leave_type: LeaveType,
    start_date: date,
    end_date: date,
) -> date:
    """Smallest valid end date so working days do not exceed remaining balance."""
    rem = get_or_compute_remaining(employee, leave_type, start_date.year)
    wd = count_uae_working_days(start_date, end_date)
    if wd <= rem:
        return end_date
    return inclusive_end_date_for_uae_working_days(start_date, rem)


def create_split_leave_pair(
    *,
    employee: Employee,
    leave_type_paid: LeaveType,
    start_date: date,
    end_date: date,
    reason: str,
    submitted_publicly: bool = False,
):
    """Creates paid + unpaid leave rows sharing split_group_id."""
    import uuid

    rem = get_or_compute_remaining(employee, leave_type_paid, start_date.year)
    ult = get_default_unpaid_leave_type()
    if not ult:
        raise ValidationError('Split requires an active Unpaid leave type. Contact HR.')
    sg = uuid.uuid4()
    end_paid = inclusive_end_date_for_uae_working_days(start_date, rem)
    start_u = end_paid + timedelta(days=1)
    lr1 = LeaveRequest(
        employee=employee,
        leave_type=leave_type_paid,
        start_date=start_date,
        end_date=end_paid,
        reason=reason or '',
        status='pending_manager',
        submitted_publicly=submitted_publicly,
        split_group_id=sg,
    )
    lr1.save()
    lr2 = LeaveRequest(
        employee=employee,
        leave_type=ult,
        start_date=start_u,
        end_date=end_date,
        reason=reason or '',
        status='pending_manager',
        submitted_publicly=submitted_publicly,
        split_group_id=sg,
    )
    lr2.save()
    sync_leave_balances_for_employee(employee.pk)
    lr1.refresh_from_db()
    lr2.refresh_from_db()
    return lr1, lr2
