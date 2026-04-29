"""LeaveBalance sync: entitled_days (policy), used/pending from LeaveRequest."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.hr.leave_entitlements import compute_entitled_days, refresh_carried_forward_placeholder
from apps.hr.models import Employee, LeaveBalance, LeaveRequest, LeaveType


def _location_matches(emp: Employee, lt: LeaveType) -> bool:
    loc = (emp.location or '').lower()
    ltl = (lt.location or '').lower()
    if ltl == 'both':
        return True
    if loc in ('uae', 'ksa'):
        return ltl == loc
    return ltl == 'both'


def sync_leave_balances_for_employee(employee_id: int) -> None:
    emp = Employee.objects.filter(pk=employee_id).first()
    if not emp:
        return
    years: set[int] = {date.today().year}
    for y in (
        LeaveRequest.objects.filter(employee_id=employee_id, is_active=True)
        .values_list('start_date__year', flat=True)
        .distinct()
    ):
        if y:
            years.add(int(y))
    for y in sorted(years):
        for lt in LeaveType.objects.filter(is_active=True):
            if not _location_matches(emp, lt):
                continue
            _sync_one_year_type(emp, lt.pk, int(y))


def _sync_one_year_type(emp: Employee, leave_type_id: int, year: int) -> None:
    lt = LeaveType.objects.filter(pk=leave_type_id).first()
    if not lt:
        return
    entitled = compute_entitled_days(emp, lt, year)
    lb, _ = LeaveBalance.objects.get_or_create(
        employee=emp,
        leave_type_id=leave_type_id,
        year=year,
        defaults={
            'entitled_days': entitled,
            'used_days': Decimal('0'),
            'pending_days': Decimal('0'),
            'carried_forward': Decimal('0'),
        },
    )
    carried = refresh_carried_forward_placeholder(lb, lt)

    pend = (
        LeaveRequest.objects.filter(
            employee=emp,
            leave_type_id=leave_type_id,
            start_date__year=year,
            is_active=True,
            status__in=['pending_manager', 'pending_hr'],
        ).aggregate(t=Sum('requested_working_days'))['t']
        or Decimal('0')
    )
    used = (
        LeaveRequest.objects.filter(
            employee=emp,
            leave_type_id=leave_type_id,
            start_date__year=year,
            is_active=True,
            status='approved',
        ).aggregate(t=Sum('requested_working_days'))['t']
        or Decimal('0')
    )

    LeaveBalance.objects.filter(pk=lb.pk).update(
        entitled_days=entitled.quantize(Decimal('0.01')),
        carried_forward=carried.quantize(Decimal('0.01')),
        pending_days=pend.quantize(Decimal('0.01')),
        used_days=used.quantize(Decimal('0.01')),
    )


def _is_effectively_unpaid_local(lt: LeaveType) -> bool:
    return (lt.pay_type or '').lower() == 'unpaid' or not lt.is_paid


def get_or_compute_remaining(employee: Employee, leave_type: LeaveType, year: int) -> Decimal:
    sync_leave_balances_for_employee(employee.pk)
    lb = LeaveBalance.objects.filter(employee=employee, leave_type=leave_type, year=year).first()
    if lb:
        return lb.remaining_days
    if _is_effectively_unpaid_local(leave_type):
        return Decimal('99999')
    return Decimal('0')


def sync_all_employees_for_leave_type(leave_type_id: int) -> None:
    """After LeaveType policy change — refresh balances for current year for matching employees."""
    lt = LeaveType.objects.filter(pk=leave_type_id).first()
    if not lt:
        return
    y = date.today().year
    for emp in Employee.objects.filter(is_active=True):
        if not _location_matches(emp, lt):
            continue
        _sync_one_year_type(emp, leave_type_id, y)
