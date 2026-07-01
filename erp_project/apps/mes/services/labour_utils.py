"""MES team labour from HR attendance × implied hourly rate."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from apps.hr.models import Employee
from apps.projects.labour_utils import implied_hourly_rate_from_basic, sum_labour_hours


def assigned_employees_for_order(production_order):
    """Union of PO-level crew, routing crew, and anyone with attendance on this PO."""
    from apps.hr.models_extended import AttendanceRecord

    employee_ids = set(
        production_order.assigned_employees.filter(is_active=True).values_list('pk', flat=True),
    )
    for op in production_order.routing_operations.filter(is_active=True).prefetch_related(
        'assigned_employees',
    ):
        for emp in op.assigned_employees.filter(is_active=True):
            employee_ids.add(emp.pk)
    employee_ids.update(
        AttendanceRecord.objects.filter(
            production_order=production_order,
            is_active=True,
            check_in__isnull=False,
            check_out__isnull=False,
        ).values_list('employee_id', flat=True).distinct(),
    )
    return Employee.objects.filter(pk__in=employee_ids, is_active=True).order_by(
        'first_name', 'last_name', 'employee_code',
    )


def mes_attendance_queryset(employee: Employee, production_order):
    from apps.hr.models_extended import AttendanceRecord

    return AttendanceRecord.objects.filter(
        employee=employee,
        production_order=production_order,
        is_active=True,
        check_in__isnull=False,
        check_out__isnull=False,
    )


def employee_labour_row(employee: Employee, production_order) -> dict:
    hourly = implied_hourly_rate_from_basic(employee.basic_salary or Decimal('0'))
    records = mes_attendance_queryset(employee, production_order)
    hours = sum_labour_hours(records)
    cost = (hours * hourly).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {
        'employee': employee,
        'display_name': f'{employee.full_name} ({employee.employee_code})',
        'hours': hours,
        'hourly_rate': hourly,
        'labour_cost': cost,
    }


def po_team_labour_summary(production_order) -> tuple[list[dict], Decimal, Decimal]:
    rows = []
    total_hours = Decimal('0.00')
    total_cost = Decimal('0.00')
    for employee in assigned_employees_for_order(production_order):
        row = employee_labour_row(employee, production_order)
        rows.append(row)
        total_hours += row['hours']
        total_cost += row['labour_cost']
    return (
        rows,
        total_hours.quantize(Decimal('0.01')),
        total_cost.quantize(Decimal('0.01')),
    )


def team_labour_cost(production_order) -> Decimal:
    _, _, total = po_team_labour_summary(production_order)
    return total
