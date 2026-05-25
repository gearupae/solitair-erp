from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.utils import PermissionChecker

from apps.projects.models import Project

from .lead_report import build_lead_report
from .project_report_customer import build_project_report_customer, project_choices_for_report as customer_project_choices
from .project_report_period import build_project_report_period
from .project_report_internal import build_project_report_internal, project_choices_for_report
from .sales_report import build_sales_report


def _reports_permission(request):
    return request.user.is_superuser or PermissionChecker.has_permission(
        request.user, 'reports', 'view'
    )


def _default_period():
    today = timezone.localdate()
    start = today.replace(day=1)
    return start, today


def _parse_period(request):
    start, end = _default_period()
    start_raw = (request.GET.get('start_date') or '').strip()
    end_raw = (request.GET.get('end_date') or '').strip()
    try:
        if start_raw:
            start = date.fromisoformat(start_raw)
        if end_raw:
            end = date.fromisoformat(end_raw)
    except ValueError:
        pass
    if start > end:
        start, end = end, start
    return start, end


@login_required
def reports_index(request):
    if not _reports_permission(request):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    return render(request, 'reports/index.html')


@login_required
def lead_report(request):
    if not _reports_permission(request):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')

    start_date, end_date = _parse_period(request)
    stage = (request.GET.get('stage') or '').strip()
    salesperson = (request.GET.get('salesperson') or '').strip()
    lead_status = (request.GET.get('status') or '').strip()

    context = build_lead_report(
        start_date=start_date,
        end_date=end_date,
        stage=stage,
        salesperson=salesperson,
        lead_status=lead_status,
        user=request.user,
    )
    context['title'] = 'Lead Report'
    return render(request, 'reports/lead_report.html', context)


@login_required
def sales_report(request):
    if not _reports_permission(request):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')

    start_date, end_date = _parse_period(request)
    context = build_sales_report(start_date=start_date, end_date=end_date)
    context['title'] = 'Sales Report'
    return render(request, 'reports/sales_report.html', context)


@login_required
def project_report_internal(request):
    if not _reports_permission(request):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')

    project = None
    project_pk = (request.GET.get('project') or '').strip()
    if project_pk:
        try:
            project = Project.objects.filter(is_active=True).select_related(
                'customer', 'manager'
            ).get(pk=int(project_pk))
        except (TypeError, ValueError, Project.DoesNotExist):
            messages.error(request, 'Project not found.')
            project = None

    context = {
        'title': 'Project Profit and Loss Report',
        'project_choices': project_choices_for_report(),
        'selected_project_id': project.pk if project else '',
        'report': None,
    }
    if project:
        context['report'] = build_project_report_internal(project=project, user=request.user)
    return render(request, 'reports/project_report_internal.html', context)


@login_required
def project_report_customer(request):
    if not _reports_permission(request):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')

    project = None
    project_pk = (request.GET.get('project') or '').strip()
    if project_pk:
        try:
            project = (
                Project.objects.filter(is_active=True)
                .select_related('customer', 'manager', 'manager__employee_profile')
                .prefetch_related(
                    'members__employee_profile',
                    'members__employee_profile__designation',
                    'members__employee_profile__department',
                    'technicians__employee_profile',
                    'technicians__employee_profile__designation',
                    'technicians__employee_profile__department',
                )
                .get(pk=int(project_pk))
            )
        except (TypeError, ValueError, Project.DoesNotExist):
            messages.error(request, 'Project not found.')
            project = None

    context = {
        'title': 'Customer Progress Report',
        'project_choices': customer_project_choices(),
        'selected_project_id': project.pk if project else '',
        'report': None,
    }
    if project:
        context['report'] = build_project_report_customer(project=project)
    return render(request, 'reports/project_report_customer.html', context)


@login_required
def project_report_period(request):
    if not _reports_permission(request):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')

    start_date, end_date = _parse_period(request)
    group_by = (request.GET.get('group_by') or '').strip()
    status = (request.GET.get('status') or '').strip()
    salesman = (request.GET.get('salesman') or '').strip()
    site_engineer = (request.GET.get('site_engineer') or '').strip()
    operation_manager = (request.GET.get('operation_manager') or '').strip()

    context = build_project_report_period(
        start_date=start_date,
        end_date=end_date,
        group_by=group_by,
        status=status,
        salesman=salesman,
        site_engineer=site_engineer,
        operation_manager=operation_manager,
    )
    context['title'] = 'Period Wise Report'
    return render(request, 'reports/project_report_period.html', context)
