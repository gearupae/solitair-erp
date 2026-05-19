"""Project labour cost from technician attendance × implied hourly rate."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum

from apps.hr.models import Employee


def implied_hourly_rate_from_basic(basic: Decimal) -> Decimal:
    """
    Consistent with UAE OT helper text: (monthly basic × 12) / 365 / 8 hours.
    """
    if not basic or basic <= 0:
        return Decimal('0.00')
    hourly = (Decimal(basic) * Decimal('12')) / Decimal('365') / Decimal('8')
    return hourly.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def project_labour_summary(project):
    """
    Per-technician totals: attendance rows with this project, sum working_hours,
    cost = hours × implied hourly rate from employee basic_salary.
    Returns (rows, total_hours, total_cost) where rows is list[dict].
    """
    from apps.hr.models_extended import AttendanceRecord

    technicians = list(
        project.technicians.filter(is_active=True).order_by('first_name', 'last_name', 'username')
    )
    date_q = Q()
    if project.start_date:
        date_q &= Q(date__gte=project.start_date)
    if project.end_date:
        date_q &= Q(date__lte=project.end_date)

    rows = []
    total_hours = Decimal('0.00')
    total_cost = Decimal('0.00')

    for user in technicians:
        emp = (
            Employee.objects.filter(user=user, is_active=True)
            .only('id', 'first_name', 'last_name', 'employee_code', 'basic_salary')
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

        hrs = (
            AttendanceRecord.objects.filter(
                employee=emp,
                project=project,
                is_active=True,
            )
            .filter(date_q)
            .aggregate(s=Sum('working_hours'))['s']
        ) or Decimal('0.00')
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
