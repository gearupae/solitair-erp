"""Project labour cost from technician attendance × implied hourly rate."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from apps.hr.models import Employee


def implied_hourly_rate_from_basic(basic: Decimal) -> Decimal:
    """
    Consistent with UAE OT helper text: (monthly basic × 12) / 365 / 8 hours.
    """
    if not basic or basic <= 0:
        return Decimal('0.00')
    hourly = (Decimal(basic) * Decimal('12')) / Decimal('365') / Decimal('8')
    return hourly.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def active_technician_projects(user):
    from apps.projects.models import Project

    if not user:
        return Project.objects.none()
    return Project.objects.filter(
        is_active=True,
        technicians=user,
        status__in=['planning', 'ongoing'],
    )


def infer_project_for_technician(user):
    """When a tech is on exactly one active project, attribute punches without a project."""
    qs = active_technician_projects(user)
    if qs.count() == 1:
        return qs.first()
    return None


def labour_attendance_queryset(employee: Employee, project):
    """Attendance sessions explicitly clocked to this project only."""
    from apps.hr.models_extended import AttendanceRecord

    user_id = employee.user_id
    if not user_id or not project.technicians.filter(pk=user_id).exists():
        return AttendanceRecord.objects.none()

    qs = AttendanceRecord.objects.filter(
        employee=employee,
        project=project,
        is_active=True,
        check_in__isnull=False,
        check_out__isnull=False,
    )
    if project.end_date:
        qs = qs.filter(date__lte=project.end_date)
    return qs


def sum_labour_hours(records) -> Decimal:
    from apps.hr.attendance_utils import record_working_hours

    total = Decimal('0.00')
    for rec in records:
        total += record_working_hours(rec)
    return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def project_labour_summary(project):
    """
    Per-technician totals: attendance rows with this project, sum working_hours,
    cost = hours × implied hourly rate from employee basic_salary.
    Returns (rows, total_hours, total_cost) where rows is list[dict].
    """
    technicians = list(
        project.technicians.filter(is_active=True).order_by('first_name', 'last_name', 'username')
    )

    rows = []
    total_hours = Decimal('0.00')
    total_cost = Decimal('0.00')

    for user in technicians:
        emp = (
            Employee.objects.filter(user=user, is_active=True)
            .only('id', 'user_id', 'first_name', 'last_name', 'employee_code', 'basic_salary')
            .first()
        )
        display = user.get_full_name() or user.username
        if not emp:
            rows.append(
                {
                    'display_name': display,
                    'employee_code': '—',
                    'hours': Decimal('0.00'),
                    'hourly_rate': Decimal('0.00'),
                    'labour_cost': Decimal('0.00'),
                }
            )
            continue

        attendance = labour_attendance_queryset(emp, project)
        hrs = sum_labour_hours(attendance)
        hourly = implied_hourly_rate_from_basic(emp.basic_salary or Decimal('0'))
        cost = (hrs * hourly).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_hours += hrs
        total_cost += cost
        rows.append(
            {
                'display_name': f'{emp.full_name} ({emp.employee_code})',
                'employee_code': emp.employee_code,
                'hours': hrs,
                'hourly_rate': hourly,
                'labour_cost': cost,
            }
        )

    return rows, total_hours.quantize(Decimal('0.01')), total_cost.quantize(Decimal('0.01'))
