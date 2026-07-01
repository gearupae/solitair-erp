"""HR report data builders."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from apps.hr.models import Department, Employee, LeaveRequest, LeaveType
from apps.hr.models_extended import AttendanceRecord, EmployeeAllowanceExpense
from apps.hr.uae_gratuity import calculate_uae_gratuity, employee_gratuity_eligible
from apps.projects.models import Project
from apps.purchase.models import ExpenseClaim


def _employee_base_qs(*, department_id='', status='', include_inactive=False):
    qs = Employee.objects.select_related('department', 'designation', 'company', 'user')
    if not include_inactive:
        qs = qs.filter(is_active=True)
    if department_id:
        try:
            qs = qs.filter(department_id=int(department_id))
        except (TypeError, ValueError):
            pass
    if status:
        qs = qs.filter(status=status)
    return qs.order_by('employee_code')


def build_employee_report(*, department_id='', status='', include_inactive=False):
    employees = _employee_base_qs(
        department_id=department_id,
        status=status,
        include_inactive=include_inactive,
    )
    rows = []
    for emp in employees:
        rows.append({
            'employee_code': emp.employee_code,
            'full_name': emp.full_name,
            'email': emp.email,
            'department': emp.department.name if emp.department_id else '—',
            'designation': emp.designation.name if emp.designation_id else '—',
            'company': emp.company.name if emp.company_id else '—',
            'location': emp.get_location_display(),
            'status': emp.get_status_display(),
            'date_of_joining': emp.date_of_joining,
            'basic_salary': emp.basic_salary,
            'has_login': bool(emp.user_id),
            'employee_pk': emp.pk,
        })
    return {
        'rows': rows,
        'total_count': len(rows),
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'department_id': department_id,
        'status': status,
        'include_inactive': include_inactive,
        'status_choices': Employee.STATUS_CHOICES,
    }


def build_expense_report(*, start_date, end_date, department_id='', employee_id=''):
    payroll_expenses = EmployeeAllowanceExpense.objects.filter(
        category__startswith=EmployeeAllowanceExpense.EXPENSE_CATEGORY_PREFIX,
    ).select_related('employee', 'employee__department', 'approved_by')
    claims = ExpenseClaim.objects.filter(
        is_active=True,
    ).exclude(status='draft').select_related('employee', 'approved_by')

    if employee_id:
        try:
            emp = Employee.objects.get(pk=int(employee_id))
            payroll_expenses = payroll_expenses.filter(employee=emp)
            if emp.user_id:
                claims = claims.filter(employee_id=emp.user_id)
            else:
                claims = claims.none()
        except (TypeError, ValueError, Employee.DoesNotExist):
            pass
    elif department_id:
        try:
            dept_id = int(department_id)
            payroll_expenses = payroll_expenses.filter(employee__department_id=dept_id)
            user_ids = Employee.objects.filter(department_id=dept_id, user_id__isnull=False).values_list('user_id', flat=True)
            claims = claims.filter(employee_id__in=user_ids)
        except (TypeError, ValueError):
            pass

    payroll_expenses = payroll_expenses.filter(
        Q(start_date__gte=start_date, start_date__lte=end_date)
        | Q(created_at__date__gte=start_date, created_at__date__lte=end_date)
    )
    claims = claims.filter(claim_date__gte=start_date, claim_date__lte=end_date)

    rows = []
    total = Decimal('0.00')

    for item in payroll_expenses:
        row_date = item.start_date or item.created_at.date()
        rows.append({
            'date': row_date,
            'source': 'Payroll expense',
            'employee_code': item.employee.employee_code,
            'employee_name': item.employee.full_name,
            'department': item.employee.department.name if item.employee.department_id else '—',
            'category': item.get_category_display(),
            'description': item.description or item.notes or '—',
            'amount': item.amount,
            'status': item.get_status_display(),
        })
        total += item.amount or Decimal('0.00')

    for claim in claims:
        emp_profile = getattr(claim.employee, 'employee_profile', None)
        rows.append({
            'date': claim.claim_date,
            'source': 'Expense claim',
            'employee_code': emp_profile.employee_code if emp_profile else '—',
            'employee_name': claim.employee.get_full_name() or claim.employee.username,
            'department': (
                emp_profile.department.name
                if emp_profile and emp_profile.department_id
                else '—'
            ),
            'category': claim.claim_number,
            'description': claim.description or '—',
            'amount': claim.total_amount,
            'status': claim.get_status_display(),
        })
        total += claim.total_amount or Decimal('0.00')

    rows.sort(key=lambda r: (r['date'], r['employee_code']), reverse=True)

    return {
        'rows': rows,
        'total_amount': total,
        'row_count': len(rows),
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'employees': Employee.objects.filter(is_active=True).order_by('employee_code'),
        'department_id': department_id,
        'employee_id': employee_id,
        'start_date': start_date,
        'end_date': end_date,
    }


def build_gratuity_report(*, as_of_date, department_id='', location=''):
    employees = _employee_base_qs(department_id=department_id).filter(location='uae')
    if location:
        employees = employees.filter(location=location)

    rows = []
    total_liability = Decimal('0.00')
    for emp in employees:
        if not employee_gratuity_eligible(emp):
            calc = calculate_uae_gratuity(emp, as_of_date=as_of_date, termination_type='terminated')
            note = calc.get('message') or 'Not eligible'
            final = Decimal('0.00')
        else:
            calc = calculate_uae_gratuity(emp, as_of_date=as_of_date, termination_type='terminated')
            note = 'Eligible (terminated scenario)'
            final = calc.get('final_gratuity') or Decimal('0.00')
            total_liability += final

        rows.append({
            'employee_code': emp.employee_code,
            'full_name': emp.full_name,
            'department': emp.department.name if emp.department_id else '—',
            'date_of_joining': emp.date_of_joining,
            'basic_salary': emp.basic_salary,
            'years_display': calc.get('years_of_service_display', '—'),
            'daily_rate': calc.get('daily_rate', Decimal('0.00')),
            'final_gratuity': final,
            'note': note,
            'employee_pk': emp.pk,
        })

    return {
        'rows': rows,
        'total_liability': total_liability,
        'as_of_date': as_of_date,
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'department_id': department_id,
        'location': location,
    }


def build_exit_report(*, start_date, end_date, department_id=''):
    qs = Employee.objects.filter(
        Q(status__in=('terminated', 'inactive')) | Q(is_active=False),
    ).select_related('department', 'designation', 'company')
    qs = qs.filter(updated_at__date__gte=start_date, updated_at__date__lte=end_date)
    if department_id:
        try:
            qs = qs.filter(department_id=int(department_id))
        except (TypeError, ValueError):
            pass

    rows = []
    for emp in qs.order_by('-updated_at'):
        rows.append({
            'employee_code': emp.employee_code,
            'full_name': emp.full_name,
            'department': emp.department.name if emp.department_id else '—',
            'designation': emp.designation.name if emp.designation_id else '—',
            'status': emp.get_status_display(),
            'termination_type': emp.get_termination_type_display() or '—',
            'date_of_joining': emp.date_of_joining,
            'last_updated': emp.updated_at.date(),
            'is_active_record': emp.is_active,
            'employee_pk': emp.pk,
        })

    return {
        'rows': rows,
        'row_count': len(rows),
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'department_id': department_id,
        'start_date': start_date,
        'end_date': end_date,
    }


def build_overtime_report(*, start_date, end_date, department_id=''):
    qs = AttendanceRecord.objects.filter(
        is_active=True,
        date__gte=start_date,
        date__lte=end_date,
        overtime_hours__gt=0,
    ).select_related('employee', 'employee__department', 'project')
    if department_id:
        try:
            qs = qs.filter(employee__department_id=int(department_id))
        except (TypeError, ValueError):
            pass

    summary = (
        qs.values('employee_id', 'employee__employee_code', 'employee__first_name', 'employee__last_name')
        .annotate(
            total_ot=Coalesce(Sum('overtime_hours'), Decimal('0.00')),
            record_count=Count('pk'),
        )
        .order_by('employee__employee_code')
    )

    detail_rows = []
    for rec in qs.order_by('-date', 'employee__employee_code'):
        detail_rows.append({
            'date': rec.date,
            'employee_code': rec.employee.employee_code,
            'employee_name': rec.employee.full_name,
            'department': rec.employee.department.name if rec.employee.department_id else '—',
            'overtime_hours': rec.overtime_hours,
            'overtime_type': rec.get_overtime_type_display(),
            'project': rec.project.project_code if rec.project_id else '—',
        })

    summary_rows = []
    grand_total = Decimal('0.00')
    for row in summary:
        total_ot = row['total_ot'] or Decimal('0.00')
        grand_total += total_ot
        name = f"{row['employee__first_name']} {row['employee__last_name']}".strip()
        summary_rows.append({
            'employee_code': row['employee__employee_code'],
            'employee_name': name,
            'total_overtime_hours': total_ot,
            'record_count': row['record_count'] or 0,
        })

    return {
        'summary_rows': summary_rows,
        'detail_rows': detail_rows,
        'grand_total_hours': grand_total,
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'department_id': department_id,
        'start_date': start_date,
        'end_date': end_date,
    }


def build_leave_report(*, start_date, end_date, department_id='', leave_type_id='', status=''):
    qs = LeaveRequest.objects.filter(
        is_active=True,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).select_related('employee', 'employee__department', 'leave_type', 'approved_by')
    if department_id:
        try:
            qs = qs.filter(employee__department_id=int(department_id))
        except (TypeError, ValueError):
            pass
    if leave_type_id:
        try:
            qs = qs.filter(leave_type_id=int(leave_type_id))
        except (TypeError, ValueError):
            pass
    if status:
        qs = qs.filter(status=status)

    rows = []
    total_days = Decimal('0.00')
    for leave in qs.order_by('-start_date'):
        days = leave.requested_working_days or Decimal(str(leave.days))
        total_days += days
        rows.append({
            'reference': leave.reference_number or '—',
            'employee_code': leave.employee.employee_code,
            'employee_name': leave.employee.full_name,
            'department': leave.employee.department.name if leave.employee.department_id else '—',
            'leave_type': leave.leave_type.name,
            'start_date': leave.start_date,
            'end_date': leave.end_date,
            'days': days,
            'status': leave.get_status_display(),
            'approved_by': leave.approved_by.get_full_name() if leave.approved_by_id else '—',
        })

    return {
        'rows': rows,
        'total_days': total_days,
        'row_count': len(rows),
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'leave_types': LeaveType.objects.filter(is_active=True).order_by('name'),
        'department_id': department_id,
        'leave_type_id': leave_type_id,
        'status': status,
        'status_choices': LeaveRequest.STATUS_CHOICES,
        'start_date': start_date,
        'end_date': end_date,
    }


def build_employee_project_report(*, department_id='', status=''):
    employees = _employee_base_qs(department_id=department_id, status=status)
    employee_list = list(employees)
    user_ids = [e.user_id for e in employee_list if e.user_id]

    user_projects: dict[int, list[dict]] = defaultdict(list)
    if user_ids:
        projects = (
            Project.objects.filter(is_active=True)
            .filter(Q(members__in=user_ids) | Q(technicians__in=user_ids) | Q(manager__in=user_ids))
            .distinct()
            .select_related('customer')
            .prefetch_related('members', 'technicians')
            .order_by('project_code')
        )
        for project in projects:
            if project.manager_id and project.manager_id in user_ids:
                user_projects[project.manager_id].append({
                    'code': project.project_code,
                    'name': project.name,
                    'status': project.get_status_display(),
                    'role': 'Manager',
                    'pk': project.pk,
                })
            member_ids = {m.pk for m in project.members.all()}
            tech_ids = {t.pk for t in project.technicians.all()}
            for uid in member_ids & set(user_ids):
                if not any(r['pk'] == project.pk and r['role'] == 'Manager' for r in user_projects[uid]):
                    user_projects[uid].append({
                        'code': project.project_code,
                        'name': project.name,
                        'status': project.get_status_display(),
                        'role': 'Member',
                        'pk': project.pk,
                    })
            for uid in tech_ids & set(user_ids):
                existing = user_projects[uid]
                if not any(r['pk'] == project.pk for r in existing):
                    user_projects[uid].append({
                        'code': project.project_code,
                        'name': project.name,
                        'status': project.get_status_display(),
                        'role': 'Technician',
                        'pk': project.pk,
                    })

    rows = []
    for emp in employee_list:
        projects_for_emp = user_projects.get(emp.user_id, []) if emp.user_id else []
        rows.append({
            'employee_code': emp.employee_code,
            'full_name': emp.full_name,
            'department': emp.department.name if emp.department_id else '—',
            'designation': emp.designation.name if emp.designation_id else '—',
            'has_login': bool(emp.user_id),
            'projects': projects_for_emp,
            'project_count': len(projects_for_emp),
            'employee_pk': emp.pk,
        })

    assigned_count = sum(1 for r in rows if r['project_count'] > 0)
    return {
        'rows': rows,
        'total_employees': len(rows),
        'assigned_count': assigned_count,
        'unassigned_count': len(rows) - assigned_count,
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'department_id': department_id,
        'status': status,
        'status_choices': Employee.STATUS_CHOICES,
    }
