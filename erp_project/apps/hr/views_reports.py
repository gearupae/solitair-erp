"""HR reports views."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.utils import PermissionChecker

from .hr_reports import (
    build_employee_project_report,
    build_employee_report,
    build_exit_report,
    build_expense_report,
    build_gratuity_report,
    build_leave_report,
    build_overtime_report,
)

HR_REPORTS = [
    {
        'slug': 'employees',
        'title': 'Employee Report',
        'description': 'Master list of employees with department, designation, status, joining date, and salary.',
        'icon': 'fa-id-card',
        'url_name': 'hr:report_employees',
    },
    {
        'slug': 'expenses',
        'title': 'Expense Report',
        'description': 'Payroll expense reimbursements and purchase expense claims by employee and period.',
        'icon': 'fa-receipt',
        'url_name': 'hr:report_expenses',
    },
    {
        'slug': 'gratuity',
        'title': 'Gratuity Report',
        'description': 'UAE end-of-service gratuity liability per employee as of a selected date.',
        'icon': 'fa-hand-holding-usd',
        'url_name': 'hr:report_gratuity',
    },
    {
        'slug': 'exit',
        'title': 'Employee Exit Report',
        'description': 'Terminated or inactive employees with termination type and last record update.',
        'icon': 'fa-sign-out-alt',
        'url_name': 'hr:report_exit',
    },
    {
        'slug': 'overtime',
        'title': 'Overtime Report',
        'description': 'Overtime hours from attendance records, summarized and detailed by employee.',
        'icon': 'fa-business-time',
        'url_name': 'hr:report_overtime',
    },
    {
        'slug': 'leave',
        'title': 'Leave Report',
        'description': 'Leave requests overlapping a period, with type, days, and approval status.',
        'icon': 'fa-plane-departure',
        'url_name': 'hr:report_leave',
    },
    {
        'slug': 'projects',
        'title': 'Project Report',
        'description': 'Each employee and the projects they are allocated to (manager, member, or technician).',
        'icon': 'fa-project-diagram',
        'url_name': 'hr:report_projects',
    },
]


def _hr_reports_permission(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'view')


def _parse_period(request):
    today = timezone.localdate()
    start = today.replace(day=1)
    end = today
    for key in ('start_date', 'end_date'):
        raw = (request.POST.get(key) or request.GET.get(key) or '').strip()
        if not raw:
            continue
        try:
            parsed = date.fromisoformat(raw)
            if key == 'start_date':
                start = parsed
            else:
                end = parsed
        except ValueError:
            pass
    if start > end:
        start, end = end, start
    return start, end


def _parse_as_of(request):
    raw = (request.POST.get('as_of_date') or request.GET.get('as_of_date') or '').strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return timezone.localdate()


def _deny_or_continue(request):
    if not _hr_reports_permission(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    return None


@login_required
def reports_index(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    return render(request, 'hr/reports/index.html', {
        'title': 'HR Reports',
        'reports': HR_REPORTS,
    })


@login_required
def report_employees(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    context = build_employee_report(
        department_id=(request.GET.get('department') or '').strip(),
        status=(request.GET.get('status') or '').strip(),
        include_inactive=request.GET.get('include_inactive') == '1',
    )
    context.update({'title': 'Employee Report', 'reports_hub_url': 'hr:reports_index'})
    return render(request, 'hr/reports/employee_report.html', context)


@login_required
def report_expenses(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    start_date, end_date = _parse_period(request)
    context = build_expense_report(
        start_date=start_date,
        end_date=end_date,
        department_id=(request.GET.get('department') or '').strip(),
        employee_id=(request.GET.get('employee') or '').strip(),
    )
    context.update({'title': 'Expense Report', 'reports_hub_url': 'hr:reports_index'})
    return render(request, 'hr/reports/expense_report.html', context)


@login_required
def report_gratuity(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    context = build_gratuity_report(
        as_of_date=_parse_as_of(request),
        department_id=(request.GET.get('department') or '').strip(),
        location=(request.GET.get('location') or '').strip(),
    )
    context.update({'title': 'Gratuity Report', 'reports_hub_url': 'hr:reports_index'})
    return render(request, 'hr/reports/gratuity_report.html', context)


@login_required
def report_exit(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    start_date, end_date = _parse_period(request)
    context = build_exit_report(
        start_date=start_date,
        end_date=end_date,
        department_id=(request.GET.get('department') or '').strip(),
    )
    context.update({'title': 'Employee Exit Report', 'reports_hub_url': 'hr:reports_index'})
    return render(request, 'hr/reports/exit_report.html', context)


@login_required
def report_overtime(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    start_date, end_date = _parse_period(request)
    context = build_overtime_report(
        start_date=start_date,
        end_date=end_date,
        department_id=(request.GET.get('department') or '').strip(),
    )
    context.update({'title': 'Overtime Report', 'reports_hub_url': 'hr:reports_index'})
    return render(request, 'hr/reports/overtime_report.html', context)


@login_required
def report_leave(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    start_date, end_date = _parse_period(request)
    context = build_leave_report(
        start_date=start_date,
        end_date=end_date,
        department_id=(request.GET.get('department') or '').strip(),
        leave_type_id=(request.GET.get('leave_type') or '').strip(),
        status=(request.GET.get('status') or '').strip(),
    )
    context.update({'title': 'Leave Report', 'reports_hub_url': 'hr:reports_index'})
    return render(request, 'hr/reports/leave_report.html', context)


@login_required
def report_projects(request):
    denied = _deny_or_continue(request)
    if denied:
        return denied
    context = build_employee_project_report(
        department_id=(request.GET.get('department') or '').strip(),
        status=(request.GET.get('status') or '').strip(),
    )
    context.update({'title': 'Project Report', 'reports_hub_url': 'hr:reports_index'})
    return render(request, 'hr/reports/project_report.html', context)
