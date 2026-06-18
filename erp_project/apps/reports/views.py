from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST

from apps.core.audit import log_audit
from apps.core.utils import PermissionChecker

from apps.projects.models import Project

from .lead_report import build_lead_report
from .project_report_customer import build_project_report_customer, project_choices_for_report as customer_project_choices
from .project_report_period import build_project_report_period
from .project_report_internal import build_project_report_internal, project_choices_for_report
from .sales_report import build_sales_report
from .services.lead_forecasting import build_lead_forecast_report_context
from .services.project_forecasting import build_forecast_report_context
from .services.sales_forecasting import build_sales_forecast_report_context
from .utils.lead_forecasting_export import export_lead_forecast_pdf, export_lead_forecast_xlsx
from .utils.project_forecasting_export import export_forecast_pdf, export_forecast_xlsx
from .utils.sales_forecasting_export import export_sales_forecast_pdf, export_sales_forecast_xlsx


def _reports_permission(request):
    return request.user.is_superuser or PermissionChecker.has_permission(
        request.user, 'reports', 'view'
    )


def _project_forecasting_permission(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'view')


def _lead_forecasting_permission(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'crm', 'view')


def _sales_forecasting_permission(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'sales', 'view')


def _default_period():
    today = timezone.localdate()
    start = today.replace(day=1)
    return start, today


def _parse_period_request(request):
    """Parse date range from GET or POST."""
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


def _parse_period(request):
    return _parse_period_request(request)


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


class ProjectForecastingView(LoginRequiredMixin, View):
    """AI project risk forecasting report."""

    def get(self, request):
        if not _project_forecasting_permission(request.user):
            raise PermissionDenied

        start_date, end_date = _parse_period(request)
        status = (request.GET.get('status') or '').strip()
        manager_id = (request.GET.get('manager') or '').strip()
        customer_id = (request.GET.get('customer') or '').strip()
        force_refresh = request.GET.get('refresh') == '1'
        export_fmt = (request.GET.get('export') or '').strip().lower()

        context = build_forecast_report_context(
            start_date=start_date,
            end_date=end_date,
            status=status,
            manager_id=manager_id,
            customer_id=customer_id,
            force_refresh=force_refresh,
        )
        context['title'] = 'Project Forecasting'

        if export_fmt in ('pdf', 'xlsx'):
            if not _reports_permission(request) and not _project_forecasting_permission(request.user):
                raise PermissionDenied
            generated_by = request.user.get_full_name() or request.user.username
            log_audit(
                request.user,
                'export',
                'Project',
                changes={
                    'event': 'ai_forecast_run',
                    'export': export_fmt,
                    'filters': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'status': status,
                        'manager': manager_id,
                        'customer': customer_id,
                    },
                    'project_count': context.get('project_count'),
                },
                request=request,
            )
            if export_fmt == 'pdf':
                data = export_forecast_pdf(context, generated_by)
                resp = HttpResponse(data, content_type='application/pdf')
                resp['Content-Disposition'] = 'attachment; filename="project_forecasting.pdf"'
                return resp
            data = export_forecast_xlsx(context, generated_by)
            resp = HttpResponse(
                data,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            resp['Content-Disposition'] = 'attachment; filename="project_forecasting.xlsx"'
            return resp

        if force_refresh or (not context.get('from_cache') and context.get('project_count', 0) > 0):
            log_audit(
                request.user,
                'view',
                'Project',
                changes={
                    'event': 'ai_forecast_run',
                    'from_cache': context.get('from_cache', False),
                    'filters': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'status': status,
                        'manager': manager_id,
                        'customer': customer_id,
                    },
                    'project_count': context.get('project_count'),
                    'ai_used': context.get('ai_used'),
                },
                request=request,
            )

        if context.get('ai_error') and force_refresh:
            messages.warning(request, context['ai_error'])

        return render(request, 'reports/project_forecasting.html', context)


@login_required
@require_POST
def project_forecasting_regenerate_brief(request):
    if not _project_forecasting_permission(request.user):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    start_date, end_date = _parse_period_request(request)
    status = (request.POST.get('status') or request.GET.get('status') or '').strip()
    manager_id = (request.POST.get('manager') or request.GET.get('manager') or '').strip()
    customer_id = (request.POST.get('customer') or request.GET.get('customer') or '').strip()

    context = build_forecast_report_context(
        start_date=start_date,
        end_date=end_date,
        status=status,
        manager_id=manager_id,
        customer_id=customer_id,
        regenerate_brief=True,
    )
    log_audit(
        request.user,
        'view',
        'Project',
        changes={'event': 'ai_forecast_brief_regenerate', 'project_count': context.get('project_count')},
        request=request,
    )
    return JsonResponse(
        {
            'brief': context.get('executive_brief') or '',
            'generated_at': context.get('generated_at').isoformat()
            if context.get('generated_at')
            else None,
        }
    )


class LeadForecastingView(LoginRequiredMixin, View):
    """AI lead pipeline forecasting report."""

    def get(self, request):
        if not _lead_forecasting_permission(request.user):
            raise PermissionDenied

        start_date, end_date = _parse_period(request)
        stage = (request.GET.get('stage') or '').strip()
        salesperson = (request.GET.get('salesperson') or '').strip()
        source = (request.GET.get('source') or '').strip()
        force_refresh = request.GET.get('refresh') == '1'
        export_fmt = (request.GET.get('export') or '').strip().lower()

        context = build_lead_forecast_report_context(
            start_date=start_date,
            end_date=end_date,
            stage=stage,
            salesperson=salesperson,
            source=source,
            user=request.user,
            force_refresh=force_refresh,
        )
        context['title'] = 'Lead Forecasting'

        if export_fmt in ('pdf', 'xlsx'):
            generated_by = request.user.get_full_name() or request.user.username
            log_audit(
                request.user,
                'export',
                'Lead',
                changes={
                    'event': 'ai_lead_forecast_run',
                    'export': export_fmt,
                    'filters': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'stage': stage,
                        'salesperson': salesperson,
                        'source': source,
                    },
                    'lead_count': context.get('lead_count'),
                },
                request=request,
            )
            if export_fmt == 'pdf':
                data = export_lead_forecast_pdf(context, generated_by)
                resp = HttpResponse(data, content_type='application/pdf')
                resp['Content-Disposition'] = 'attachment; filename="lead_forecasting.pdf"'
                return resp
            data = export_lead_forecast_xlsx(context, generated_by)
            resp = HttpResponse(
                data,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            resp['Content-Disposition'] = 'attachment; filename="lead_forecasting.xlsx"'
            return resp

        if force_refresh or (not context.get('from_cache') and context.get('lead_count', 0) > 0):
            log_audit(
                request.user,
                'view',
                'Lead',
                changes={
                    'event': 'ai_lead_forecast_run',
                    'from_cache': context.get('from_cache', False),
                    'filters': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'stage': stage,
                        'salesperson': salesperson,
                        'source': source,
                    },
                    'lead_count': context.get('lead_count'),
                    'ai_used': context.get('ai_used'),
                },
                request=request,
            )

        if context.get('ai_error') and force_refresh:
            messages.warning(request, context['ai_error'])

        return render(request, 'reports/lead_forecasting.html', context)


@login_required
@require_POST
def lead_forecasting_regenerate_brief(request):
    if not _lead_forecasting_permission(request.user):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    start_date, end_date = _parse_period_request(request)
    stage = (request.POST.get('stage') or request.GET.get('stage') or '').strip()
    salesperson = (request.POST.get('salesperson') or request.GET.get('salesperson') or '').strip()
    source = (request.POST.get('source') or request.GET.get('source') or '').strip()

    context = build_lead_forecast_report_context(
        start_date=start_date,
        end_date=end_date,
        stage=stage,
        salesperson=salesperson,
        source=source,
        user=request.user,
        regenerate_brief=True,
    )
    log_audit(
        request.user,
        'view',
        'Lead',
        changes={'event': 'ai_lead_forecast_brief_regenerate', 'lead_count': context.get('lead_count')},
        request=request,
    )
    return JsonResponse(
        {
            'brief': context.get('executive_brief') or '',
            'generated_at': context.get('generated_at').isoformat()
            if context.get('generated_at')
            else None,
        }
    )


class SalesForecastingView(LoginRequiredMixin, View):
    """AI sales / estimate forecasting with project learning."""

    def get(self, request):
        if not _sales_forecasting_permission(request.user):
            raise PermissionDenied

        start_date, end_date = _parse_period(request)
        status = (request.GET.get('status') or '').strip()
        salesperson_id = (request.GET.get('salesperson') or '').strip()
        customer_id = (request.GET.get('customer') or '').strip()
        job_type = (request.GET.get('job_type') or '').strip()
        force_refresh = request.GET.get('refresh') == '1'
        export_fmt = (request.GET.get('export') or '').strip().lower()

        context = build_sales_forecast_report_context(
            start_date=start_date,
            end_date=end_date,
            status=status,
            salesperson_id=salesperson_id,
            customer_id=customer_id,
            job_type=job_type,
            force_refresh=force_refresh,
        )
        context['title'] = 'Sales Forecasting'

        if export_fmt in ('pdf', 'xlsx'):
            generated_by = request.user.get_full_name() or request.user.username
            log_audit(
                request.user,
                'export',
                'Estimate',
                changes={
                    'event': 'ai_sales_forecast_run',
                    'export': export_fmt,
                    'filters': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'status': status,
                        'salesperson': salesperson_id,
                        'customer': customer_id,
                        'job_type': job_type,
                    },
                    'estimate_count': context.get('estimate_count'),
                },
                request=request,
            )
            if export_fmt == 'pdf':
                data = export_sales_forecast_pdf(context, generated_by)
                resp = HttpResponse(data, content_type='application/pdf')
                resp['Content-Disposition'] = 'attachment; filename="sales_forecasting.pdf"'
                return resp
            data = export_sales_forecast_xlsx(context, generated_by)
            resp = HttpResponse(
                data,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            resp['Content-Disposition'] = 'attachment; filename="sales_forecasting.xlsx"'
            return resp

        if force_refresh or (not context.get('from_cache') and context.get('estimate_count', 0) > 0):
            log_audit(
                request.user,
                'view',
                'Estimate',
                changes={
                    'event': 'ai_sales_forecast_run',
                    'from_cache': context.get('from_cache', False),
                    'filters': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'status': status,
                        'salesperson': salesperson_id,
                        'customer': customer_id,
                        'job_type': job_type,
                    },
                    'estimate_count': context.get('estimate_count'),
                    'ai_used': context.get('ai_used'),
                },
                request=request,
            )

        if context.get('ai_error') and force_refresh:
            messages.warning(request, context['ai_error'])

        return render(request, 'reports/sales_forecasting.html', context)


@login_required
@require_POST
def sales_forecasting_regenerate_brief(request):
    if not _sales_forecasting_permission(request.user):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    start_date, end_date = _parse_period_request(request)
    status = (request.POST.get('status') or request.GET.get('status') or '').strip()
    salesperson_id = (request.POST.get('salesperson') or request.GET.get('salesperson') or '').strip()
    customer_id = (request.POST.get('customer') or request.GET.get('customer') or '').strip()
    job_type = (request.POST.get('job_type') or request.GET.get('job_type') or '').strip()

    context = build_sales_forecast_report_context(
        start_date=start_date,
        end_date=end_date,
        status=status,
        salesperson_id=salesperson_id,
        customer_id=customer_id,
        job_type=job_type,
        regenerate_brief=True,
    )
    log_audit(
        request.user,
        'view',
        'Estimate',
        changes={'event': 'ai_sales_forecast_brief_regenerate', 'estimate_count': context.get('estimate_count')},
        request=request,
    )
    return JsonResponse(
        {
            'brief': context.get('executive_brief') or '',
            'generated_at': context.get('generated_at').isoformat()
            if context.get('generated_at')
            else None,
        }
    )
