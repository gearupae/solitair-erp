"""
Operations views — staff duty scheduling, calendar, and public schedule board.
"""
from calendar import monthcalendar, monthrange
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import FormView, ListView, TemplateView, UpdateView

from apps.core.mixins import CreatePermissionMixin, PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.hr.models import Employee
from apps.settings_app.models import AuditLog
from apps.core.middleware import get_current_request

from .dashboard import build_dashboard_context
from .exports import export_completed_schedules
from .forms import StaffDutyBulkScheduleForm, StaffDutyScheduleForm
from .models import StaffDutySchedule
from .utils import (
    ensure_operations_public_token,
    find_employee_schedule_conflicts,
    format_conflict_message,
    get_hr_employee_queryset,
    get_schedule_for_public_token,
)


def log_action(user, action, model, record_id, changes=None):
    request = get_current_request()
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0]
        else:
            ip_address = request.META.get('REMOTE_ADDR')
    AuditLog.objects.create(
        user=user,
        action=action,
        model=model,
        record_id=str(record_id),
        changes=changes or {},
        ip_address=ip_address,
    )


def apply_schedule_filters(queryset, params):
    search = (params.get('search') or '').strip()
    if search:
        queryset = queryset.filter(
            Q(employee__first_name__icontains=search)
            | Q(employee__last_name__icontains=search)
            | Q(employee__employee_code__icontains=search)
            | Q(project__name__icontains=search)
            | Q(project__project_code__icontains=search)
            | Q(amc_contract__name__icontains=search)
            | Q(amc_contract__contract_number__icontains=search)
        )
    status = (params.get('status') or '').strip()
    if status:
        queryset = queryset.filter(status=status)
    link_type = (params.get('link_type') or '').strip()
    if link_type:
        queryset = queryset.filter(link_type=link_type)
    employee = (params.get('employee') or '').strip()
    if employee:
        try:
            queryset = queryset.filter(employee_id=int(employee))
        except (TypeError, ValueError):
            pass
    date_from = (params.get('date_from') or '').strip()
    date_to = (params.get('date_to') or '').strip()
    if date_from:
        queryset = queryset.filter(duty_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(duty_date__lte=date_to)
    return queryset


def _parse_period(params, default_start=None, default_end=None):
    today = timezone.localdate()
    start = default_start or today
    end = default_end or today
    for key, target in (('date_from', 'start'), ('date_to', 'end'), ('start_date', 'start'), ('end_date', 'end')):
        raw = (params.get(key) or '').strip()
        if not raw:
            continue
        try:
            parsed = date.fromisoformat(raw)
            if target == 'start':
                start = parsed
            else:
                end = parsed
        except ValueError:
            pass
    if start > end:
        start, end = end, start
    return start, end


class StaffDutyScheduleListView(PermissionRequiredMixin, ListView):
    model = StaffDutySchedule
    template_name = 'operations/schedule_list.html'
    context_object_name = 'schedules'
    module_name = 'projects'
    permission_type = 'view'
    paginate_by = 50

    def get_queryset(self):
        qs = (
            StaffDutySchedule.objects.filter(is_active=True)
            .select_related('employee', 'project', 'amc_contract')
            .order_by('-duty_date', 'start_time', 'employee__first_name')
        )
        return apply_schedule_filters(qs, self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx['title'] = 'Operations — Staff Duty'
        ctx['can_create'] = user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'create')
        ctx['can_edit'] = user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'edit')
        ctx['can_delete'] = user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'delete')
        ctx['filter_employees'] = get_hr_employee_queryset()
        ctx['filter_status'] = self.request.GET.get('status', '')
        ctx['filter_link_type'] = self.request.GET.get('link_type', '')
        ctx['filter_employee'] = self.request.GET.get('employee', '')
        ctx['filter_date_from'] = self.request.GET.get('date_from', '')
        ctx['filter_date_to'] = self.request.GET.get('date_to', '')
        ctx['filter_search'] = self.request.GET.get('search', '')
        ctx['status_choices'] = StaffDutySchedule.STATUS_CHOICES
        token = ensure_operations_public_token()
        ctx['public_schedule_url'] = self.request.build_absolute_uri(
            reverse('operations:public_schedule', kwargs={'token': token})
        )
        return ctx


class StaffDutyDashboardView(PermissionRequiredMixin, TemplateView):
    template_name = 'operations/schedule_dashboard.html'
    module_name = 'projects'
    permission_type = 'view'

    def get(self, request, *args, **kwargs):
        export_fmt = (request.GET.get('export') or '').strip().lower()
        if export_fmt in ('xlsx', 'pdf'):
            return export_completed_schedules(request, export_fmt)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Operations — Dashboard'
        dash = build_dashboard_context(self.request.GET)
        ctx.update(dash)
        user = self.request.user
        ctx['can_create'] = user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'create')
        ctx['can_edit'] = user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'edit')
        ctx['hub_url'] = reverse('projects:project_dashboard')
        return ctx


class StaffDutyScheduleCreateView(CreatePermissionMixin, FormView):
    template_name = 'operations/schedule_form.html'
    form_class = StaffDutyBulkScheduleForm
    module_name = 'projects'
    success_url = reverse_lazy('operations:schedule_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Schedule Staff Duty'
        ctx['is_create'] = True
        return ctx

    def form_valid(self, form):
        try:
            created = form.create_schedules()
        except Exception as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        for schedule in created:
            log_action(self.request.user, 'create', 'StaffDutySchedule', schedule.id)
        messages.success(
            self.request,
            f'Scheduled {len(created)} staff member{"s" if len(created) != 1 else ""}.',
        )
        return redirect(self.success_url)


class StaffDutyScheduleUpdateView(UpdatePermissionMixin, UpdateView):
    model = StaffDutySchedule
    form_class = StaffDutyScheduleForm
    template_name = 'operations/schedule_form.html'
    module_name = 'projects'
    success_url = reverse_lazy('operations:schedule_list')

    def get_queryset(self):
        return StaffDutySchedule.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        staff = self.object.employee.full_name if self.object.employee_id else 'Unassigned'
        ctx['title'] = f'Edit duty — {staff}'
        ctx['is_create'] = False
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request.user, 'update', 'StaffDutySchedule', self.object.id)
        messages.success(self.request, 'Duty schedule updated.')
        return response


class StaffDutyCalendarView(PermissionRequiredMixin, TemplateView):
    template_name = 'operations/schedule_calendar.html'
    module_name = 'projects'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        view_mode = (self.request.GET.get('view') or 'month').strip()
        ctx['view_mode'] = view_mode
        ctx['title'] = 'Operations — Duty Calendar'

        if view_mode == 'period':
            start, end = _parse_period(self.request.GET, today, today + timedelta(days=6))
            ctx['period_start'] = start
            ctx['period_end'] = end
            ctx['period_days'] = []
            cur = start
            while cur <= end:
                ctx['period_days'].append(cur)
                cur += timedelta(days=1)
        else:
            y = int(self.request.GET.get('year') or today.year)
            m = int(self.request.GET.get('month') or today.month)
            ctx['year'] = y
            ctx['month'] = m
            ctx['calendar_weeks'] = monthcalendar(y, m)
            start = date(y, m, 1)
            end = date(y, m, monthrange(y, m)[1])

        employee_id = (self.request.GET.get('employee') or '').strip()
        qs = StaffDutySchedule.objects.filter(
            is_active=True,
            status__in=(
                StaffDutySchedule.STATUS_SCHEDULED,
                StaffDutySchedule.STATUS_PENDING,
                StaffDutySchedule.STATUS_IN_PROGRESS,
                StaffDutySchedule.STATUS_OVERDUE,
                StaffDutySchedule.STATUS_PAUSED,
            ),
            duty_date__gte=start,
            duty_date__lte=end,
        ).select_related('employee', 'project', 'amc_contract')
        if employee_id.isdigit():
            qs = qs.filter(employee_id=int(employee_id))
            ctx['filter_employee'] = employee_id
        else:
            ctx['filter_employee'] = ''

        ctx['schedules'] = qs.order_by('duty_date', 'start_time')
        ctx['days_data'] = [
            {'date': d, 'schedules': [s for s in ctx['schedules'] if s.duty_date == d]}
            for d in (ctx.get('period_days') or [])
        ]

        ctx['filter_employees'] = get_hr_employee_queryset()
        ctx['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'projects', 'edit'
        )
        token = ensure_operations_public_token()
        ctx['public_schedule_url'] = self.request.build_absolute_uri(
            reverse('operations:public_schedule', kwargs={'token': token})
        )
        return ctx


@login_required
@require_POST
def staff_duty_pause(request, pk):
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'projects', 'edit')
    ):
        messages.error(request, 'Permission denied.')
        return redirect('operations:schedule_list')

    schedule = get_object_or_404(StaffDutySchedule, pk=pk, is_active=True)
    schedule.status = 'paused'
    schedule.save(update_fields=['status', 'updated_at'])
    log_action(request.user, 'update', 'StaffDutySchedule', schedule.id, {'action': 'pause'})
    messages.success(request, f'Paused duty for {schedule.employee.full_name}.')
    return redirect(request.POST.get('next') or 'operations:schedule_list')


@login_required
@require_POST
def staff_duty_resume(request, pk):
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'projects', 'edit')
    ):
        messages.error(request, 'Permission denied.')
        return redirect('operations:schedule_list')

    schedule = get_object_or_404(StaffDutySchedule, pk=pk, is_active=True)
    conflicts = find_employee_schedule_conflicts(
        [schedule.employee_id],
        schedule.duty_date,
        exclude_pk=schedule.pk,
    )
    if schedule.employee_id in conflicts:
        messages.error(request, format_conflict_message(conflicts[schedule.employee_id]))
        return redirect(request.POST.get('next') or 'operations:schedule_list')

    schedule.status = 'scheduled'
    schedule.save(update_fields=['status', 'updated_at'])
    log_action(request.user, 'update', 'StaffDutySchedule', schedule.id, {'action': 'resume'})
    messages.success(request, f'Resumed duty for {schedule.employee.full_name}.')
    return redirect(request.POST.get('next') or 'operations:schedule_list')


@login_required
@require_POST
def staff_duty_delete(request, pk):
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'projects', 'delete')
    ):
        messages.error(request, 'Permission denied.')
        return redirect('operations:schedule_list')

    schedule = get_object_or_404(StaffDutySchedule, pk=pk, is_active=True)
    schedule.is_active = False
    schedule.save(update_fields=['is_active', 'updated_at'])
    log_action(request.user, 'delete', 'StaffDutySchedule', schedule.id)
    messages.success(request, 'Duty assignment removed.')
    return redirect('operations:schedule_list')


@login_required
@require_GET
def staff_availability_check(request):
    """JSON: which employees are unavailable on a given date."""
    duty_date_raw = (request.GET.get('duty_date') or '').strip()
    exclude_pk = (request.GET.get('exclude_pk') or '').strip()
    try:
        duty_date = date.fromisoformat(duty_date_raw)
    except ValueError:
        return JsonResponse({'error': 'Invalid date.'}, status=400)

    exclude_id = None
    if exclude_pk.isdigit():
        exclude_id = int(exclude_pk)

    conflicts = find_employee_schedule_conflicts(
        list(get_hr_employee_queryset().values_list('pk', flat=True)),
        duty_date,
        exclude_pk=exclude_id,
    )
    unavailable = []
    for emp_id, schedule in conflicts.items():
        unavailable.append({
            'employee_id': emp_id,
            'message': format_conflict_message(schedule),
            'target': schedule.target_label,
        })
    return JsonResponse({'unavailable': unavailable})


@never_cache
def public_staff_schedule(request, token):
    """Public read-only schedule board (no login)."""
    if not get_schedule_for_public_token(token):
        return render(request, 'operations/public_schedule_unavailable.html', status=404)

    today = timezone.localdate()
    view_mode = (request.GET.get('view') or 'day').strip()
    if view_mode == 'period':
        start, end = _parse_period(request.GET, today, today + timedelta(days=6))
    else:
        day_raw = (request.GET.get('date') or '').strip()
        try:
            start = date.fromisoformat(day_raw) if day_raw else today
        except ValueError:
            start = today
        end = start

    qs = StaffDutySchedule.objects.filter(
        is_active=True,
        status='scheduled',
        duty_date__gte=start,
        duty_date__lte=end,
    ).select_related('employee', 'project', 'amc_contract').order_by(
        'duty_date', 'start_time', 'employee__first_name'
    )

    schedules = list(qs)
    period_days = []
    cur = start
    while cur <= end:
        period_days.append(cur)
        cur += timedelta(days=1)
    days_data = [
        {'date': d, 'schedules': [s for s in schedules if s.duty_date == d]}
        for d in period_days
    ]

    return render(
        request,
        'operations/public_schedule.html',
        {
            'title': 'Staff Duty Schedule',
            'view_mode': view_mode,
            'period_start': start,
            'period_end': end,
            'period_days': period_days,
            'days_data': days_data,
            'selected_date': start,
            'schedules': schedules,
            'today': today,
        },
    )
