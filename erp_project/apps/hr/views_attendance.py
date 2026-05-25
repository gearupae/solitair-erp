"""Attendance views: marks, list, import, monthly summary, holidays, settings."""
from __future__ import annotations

import csv
import json
from urllib.parse import urlencode
from datetime import date, datetime as datetime_cls
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, HttpResponseRedirect, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone as django_timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DeleteView, FormView, ListView, TemplateView, UpdateView
from django.views.generic.edit import CreateView

from apps.core.mixins import CreatePermissionMixin, PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.hr.attendance_utils import (
    attendance_snapshot_today,
    attendance_overlap_message,
    holiday_on_date_for_employee,
    is_uae_weekend,
    mark_all_present_today,
    month_absent_rate_pct,
    company_overtime_month,
    open_attendance_session,
    recalculate_summary_for_employee_month,
)
from apps.projects.labour_utils import infer_project_for_technician
from apps.hr.forms_extended import AttendanceMarkForm, AttendanceSettingsForm, HolidayForm
from apps.hr.models import Employee
from apps.hr.models_extended import AttendanceRecord, AttendanceSettings, AttendanceSummary, Holiday


def _parse_time_cell(raw):
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime_cls.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def employee_for_user(user):
    if not user.is_authenticated:
        return None
    return Employee.objects.filter(user=user, is_active=True).first()


def _hr_admin(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'edit')


class AttendanceRecordListView(PermissionRequiredMixin, ListView):
    model = AttendanceRecord
    template_name = 'hr/attendance_list.html'
    context_object_name = 'records'
    paginate_by = 50
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        qs = AttendanceRecord.objects.filter(is_active=True).select_related('employee', 'employee__department')
        emp = self.request.GET.get('employee')
        if emp:
            qs = qs.filter(employee_id=emp)
        df = self.request.GET.get('date_from')
        dt_to = self.request.GET.get('date_to')
        if df:
            qs = qs.filter(date__gte=df)
        if dt_to:
            qs = qs.filter(date__lte=dt_to)
        dept = self.request.GET.get('department')
        if dept and str(dept).isdigit():
            qs = qs.filter(employee__department_id=int(dept))
        comp = self.request.GET.get('company')
        if comp and str(comp).isdigit():
            qs = qs.filter(employee__company_id=int(comp))
        return qs.order_by('-date', 'employee__employee_code')

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('export') == 'csv' and (
            self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'view')
        ):
            # Full filtered queryset — not the paginated page slice.
            return self._export_csv(self.get_queryset())
        return super().render_to_response(context, **response_kwargs)

    def _export_csv(self, qs):
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="attendance_export.csv"'
        w = csv.writer(resp)
        w.writerow(
            [
                'date',
                'employee_code',
                'employee_name',
                'status',
                'check_in',
                'check_out',
                'check_in_latitude',
                'check_in_longitude',
                'check_out_latitude',
                'check_out_longitude',
                'working_hours',
                'late_minutes',
                'overtime_hours',
                'overtime_type',
                'source',
            ]
        )
        for r in qs:
            w.writerow(
                [
                    r.date.isoformat(),
                    r.employee.employee_code,
                    r.employee.full_name,
                    r.get_status_display(),
                    r.check_in or '',
                    r.check_out or '',
                    r.check_in_latitude if r.check_in_latitude is not None else '',
                    r.check_in_longitude if r.check_in_longitude is not None else '',
                    r.check_out_latitude if r.check_out_latitude is not None else '',
                    r.check_out_longitude if r.check_out_longitude is not None else '',
                    r.working_hours if r.working_hours is not None else '',
                    r.late_minutes,
                    r.overtime_hours,
                    r.get_overtime_type_display(),
                    r.get_source_display(),
                ]
            )
        return resp

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Attendance'
        from apps.hr.models import Department
        from apps.settings_app.models import Company

        ctx['employees'] = Employee.objects.filter(is_active=True).order_by('first_name')
        ctx['departments'] = Department.objects.filter(is_active=True).order_by('name')
        ctx['companies'] = Company.objects.filter(is_active=True).order_by('name')
        ctx['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'create'
        )
        q = self.request.GET.copy()
        for obsolete in ('year', 'month'):
            q.pop(obsolete, None)
        q['export'] = 'csv'
        ctx['export_querystring'] = urlencode(q)
        ctx['public_attendance_url'] = self.request.build_absolute_uri(reverse('hr:public_attendance'))
        return ctx


class EmployeeAttendanceRecordsView(LoginRequiredMixin, ListView):
    """Self-service: own records only."""
    model = AttendanceRecord
    template_name = 'hr/attendance_records_self.html'
    context_object_name = 'records'
    paginate_by = 31

    def dispatch(self, request, *args, **kwargs):
        if PermissionChecker.has_permission(request.user, 'hr', 'view'):
            return redirect('hr:attendance_list')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        emp = employee_for_user(self.request.user)
        if not emp:
            return AttendanceRecord.objects.none()
        qs = AttendanceRecord.objects.filter(is_active=True, employee=emp).select_related('employee')
        y = self.request.GET.get('year')
        m = self.request.GET.get('month')
        if y and m:
            qs = qs.filter(date__year=int(y), date__month=int(m))
        return qs.order_by('-date')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = employee_for_user(self.request.user)
        ctx['title'] = 'My attendance'
        ctx['employee'] = emp
        today = date.today()
        y = int(self.request.GET.get('year') or today.year)
        m = int(self.request.GET.get('month') or today.month)
        mf = date(y, m, 1)
        summ = AttendanceSummary.objects.filter(employee=emp, month=mf).first() if emp else None
        ctx['month_summary'] = summ
        ctx['filter_year'] = y
        ctx['filter_month'] = m
        ctx['months'] = [(mm, date(2000, mm, 1).strftime('%B')) for mm in range(1, 13)]
        ctx['years'] = range(today.year - 2, today.year + 2)
        ctx['snapshot'] = attendance_snapshot_today()
        return ctx


@login_required
@require_POST
def attendance_record_delete(request, pk):
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:attendance_list')
    rec = get_object_or_404(AttendanceRecord, pk=pk, is_active=True)
    emp = rec.employee
    ad = rec.date
    rec.is_active = False
    rec.save(update_fields=['is_active', 'updated_at'])
    recalculate_summary_for_employee_month(emp, ad.year, ad.month)
    messages.success(
        request,
        f'Attendance deleted for {emp.employee_code} on {ad.strftime("%d/%m/%Y")}.',
    )
    return redirect(request.POST.get('next') or reverse('hr:attendance_list'))


class AttendanceMarkView(CreatePermissionMixin, FormView):
    form_class = AttendanceMarkForm
    template_name = 'hr/attendance_mark.html'
    success_url = reverse_lazy('hr:attendance_list')
    module_name = 'hr'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        emp_id = self.request.GET.get('employee')
        d_raw = self.request.GET.get('date')
        rid = self.request.GET.get('record')
        if rid and str(rid).isdigit():
            kwargs['instance'] = get_object_or_404(AttendanceRecord, pk=int(rid))
        elif emp_id and d_raw:
            try:
                ad = date.fromisoformat(d_raw[:10])
            except ValueError:
                return kwargs
            emp = get_object_or_404(Employee, pk=int(emp_id), is_active=True)
            kwargs['instance'] = (
                AttendanceRecord.objects.filter(employee=emp, date=ad).order_by('-pk').first()
                or AttendanceRecord(employee=emp, date=ad)
            )
        return kwargs

    def form_valid(self, form):
        form.instance.source = form.cleaned_data.get('source') or 'manual'
        form.save()
        recalculate_summary_for_employee_month(form.instance.employee, form.instance.date.year, form.instance.date.month)
        messages.success(self.request, 'Attendance saved.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Mark attendance'
        ctx['snapshot'] = attendance_snapshot_today()
        ctx['can_mark_all'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'create'
        )
        return ctx


@login_required
def attendance_mark_all_present(request):
    if request.method != 'POST':
        return redirect('hr:attendance_mark')
    if not _hr_admin(request.user) and not PermissionChecker.has_permission(request.user, 'hr', 'create'):
        messages.error(request, 'Permission denied.')
        return redirect('hr:attendance_mark')
    n = mark_all_present_today()
    messages.success(request, f'{n} employees marked present.')
    return redirect('hr:attendance_mark')


@login_required
def attendance_record_lookup(request):
    """JSON: existing row + month stats for employee/date."""
    emp_id = request.GET.get('employee_id')
    d_raw = request.GET.get('date')
    if not emp_id or not d_raw:
        return JsonResponse({'ok': False}, status=400)
    emp = get_object_or_404(Employee, pk=int(emp_id), is_active=True)
    try:
        ad = date.fromisoformat(d_raw[:10])
    except ValueError:
        return JsonResponse({'ok': False}, status=400)
    rec = AttendanceRecord.objects.filter(employee=emp, date=ad).first()
    mf = date(ad.year, ad.month, 1)
    qs = AttendanceRecord.objects.filter(employee=emp, date__year=ad.year, date__month=ad.month)
    agg = qs.aggregate(
        present=Count('pk', filter=Q(status='present')),
        absent=Count('pk', filter=Q(status='absent')),
        late=Count('pk', filter=Q(status='late')),
        wh=Sum('working_hours'),
    )
    data = {
        'ok': True,
        'record': None,
        'month': {
            'present': agg['present'] or 0,
            'absent': agg['absent'] or 0,
            'late': agg['late'] or 0,
            'hours': str(agg['wh'] or Decimal('0')),
        },
    }
    if rec:
        data['record'] = {
            'id': rec.pk,
            'check_in': rec.check_in.isoformat() if rec.check_in else '',
            'check_out': rec.check_out.isoformat() if rec.check_out else '',
            'status': rec.status,
            'overtime_type': rec.overtime_type,
            'notes': rec.notes,
            'source': rec.source,
            'project_id': rec.project_id,
        }
    return JsonResponse(data)


class AttendanceMonthlySummaryListView(PermissionRequiredMixin, TemplateView):
    template_name = 'hr/attendance_monthly_summary.html'
    module_name = 'hr'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = date.today()
        year = int(self.request.GET.get('year') or today.year)
        month = int(self.request.GET.get('month') or today.month)
        mf = date(year, month, 1)
        dept = self.request.GET.get('department')
        comp = self.request.GET.get('company')

        emps = Employee.objects.filter(is_active=True, status='active').select_related('department', 'company')
        if dept and str(dept).isdigit():
            emps = emps.filter(department_id=int(dept))
        if comp and str(comp).isdigit():
            emps = emps.filter(company_id=int(comp))

        rows = []
        for emp in emps.order_by('first_name', 'last_name'):
            summ = AttendanceSummary.objects.filter(employee=emp, month=mf).first()
            rows.append({'employee': emp, 'summary': summ})

        from apps.hr.models import Department
        from apps.settings_app.models import Company

        ctx['title'] = 'Monthly attendance summary'
        ctx['year'] = year
        ctx['month'] = month
        ctx['month_label'] = mf.strftime('%B %Y')
        ctx['rows'] = rows
        ctx['departments'] = Department.objects.filter(is_active=True).order_by('name')
        ctx['companies'] = Company.objects.filter(is_active=True).order_by('name')
        ctx['filter_department'] = dept or ''
        ctx['filter_company'] = comp or ''
        ctx['years'] = range(today.year - 2, today.year + 2)
        ctx['months'] = [(m, date(2000, m, 1).strftime('%B')) for m in range(1, 13)]
        ctx['can_edit'] = _hr_admin(self.request.user)
        return ctx


class AttendanceSettingsView(UpdatePermissionMixin, UpdateView):
    model = AttendanceSettings
    form_class = AttendanceSettingsForm
    template_name = 'hr/attendance_settings_form.html'
    success_url = reverse_lazy('hr:attendance_settings')
    module_name = 'hr'

    def get_object(self, queryset=None):
        obj, _ = AttendanceSettings.objects.get_or_create(pk=1)
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Attendance settings'
        return ctx


class HolidayListView(PermissionRequiredMixin, ListView):
    model = Holiday
    template_name = 'hr/holiday_list.html'
    context_object_name = 'holidays'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        return Holiday.objects.filter(is_active=True).order_by('date')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Holidays'
        ctx['can_edit'] = _hr_admin(self.request.user)
        return ctx


class HolidayCreateView(CreatePermissionMixin, CreateView):
    model = Holiday
    form_class = HolidayForm
    template_name = 'hr/holiday_form.html'
    success_url = reverse_lazy('hr:holiday_list')
    module_name = 'hr'

    def form_valid(self, form):
        messages.success(self.request, 'Holiday saved.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add holiday'
        return ctx


class HolidayUpdateView(UpdatePermissionMixin, UpdateView):
    model = Holiday
    form_class = HolidayForm
    template_name = 'hr/holiday_form.html'
    success_url = reverse_lazy('hr:holiday_list')
    module_name = 'hr'

    def form_valid(self, form):
        messages.success(self.request, 'Holiday updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Edit holiday'
        return ctx


class HolidayDeleteView(UpdatePermissionMixin, DeleteView):
    model = Holiday
    template_name = 'hr/holiday_confirm_delete.html'
    success_url = reverse_lazy('hr:holiday_list')
    module_name = 'hr'

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.is_active = False
        self.object.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, 'Holiday removed.')
        return HttpResponseRedirect(self.success_url)


@login_required
def attendance_generate_summaries(request):
    if request.method != 'POST':
        return redirect('hr:attendance_summary_month')
    if not _hr_admin(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('hr:attendance_summary_month')
    year = int(request.POST.get('year') or date.today().year)
    month = int(request.POST.get('month') or date.today().month)
    n = 0
    for emp in Employee.objects.filter(is_active=True, status='active'):
        recalculate_summary_for_employee_month(emp, year, month, skip_if_finalized=True)
        n += 1
    messages.success(request, f'Generated summaries for {n} employees ({month}/{year}).')
    return redirect(f"{reverse('hr:attendance_summary_month')}?year={year}&month={month}")


@login_required
def attendance_finalize_summary(request, pk):
    if request.method != 'POST':
        return redirect('hr:attendance_summary_month')
    if not _hr_admin(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('hr:attendance_summary_month')
    summ = get_object_or_404(AttendanceSummary, pk=pk)
    summ.is_finalized = True
    summ.save(update_fields=['is_finalized'])
    messages.success(request, 'Summary finalized.')
    url = request.META.get('HTTP_REFERER')
    if url:
        return HttpResponseRedirect(url)
    return redirect('hr:attendance_summary_month')


@login_required
def attendance_summary_export_csv(request):
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'view')):
        return HttpResponseForbidden()
    year = int(request.GET.get('year') or date.today().year)
    month = int(request.GET.get('month') or date.today().month)
    mf = date(year, month, 1)
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="attendance_summary_{year}_{month:02d}.csv"'
    w = csv.writer(resp)
    w.writerow(
        [
            'employee_code',
            'name',
            'present',
            'absent',
            'late',
            'half_day',
            'holiday',
            'overtime_hrs',
            'total_hrs',
            'absent_deduction_days',
            'finalized',
        ]
    )
    for summ in AttendanceSummary.objects.filter(month=mf, is_active=True).select_related('employee'):
        w.writerow(
            [
                summ.employee.employee_code,
                summ.employee.full_name,
                summ.total_present,
                summ.total_absent,
                summ.total_late,
                summ.total_half_day,
                summ.total_holidays,
                summ.total_overtime_hours,
                summ.total_working_hours,
                summ.absent_deduction_days,
                'yes' if summ.is_finalized else 'no',
            ]
        )
    return resp


@login_required
def attendance_import_sample_csv(request):
    """Download sample CSV for bulk attendance import."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'create')):
        return HttpResponseForbidden('Permission denied.')
    path = settings.BASE_DIR / 'import_templates' / 'attendance_import.csv'
    response = HttpResponse(path.read_text(encoding='utf-8'), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="attendance_import_sample.csv"'
    return response


@login_required
def attendance_import_csv(request):
    """CSV import with preview (session) + skip weekends/holidays."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:attendance_list')

    if request.method == 'GET':
        return render(
            request,
            'hr/attendance_import.html',
            {
                'title': 'Import attendance CSV',
                'sample_csv_url': reverse('hr:attendance_import_sample_csv'),
            },
        )

    step = request.POST.get('step') or 'preview'
    f = request.FILES.get('file')

    if step == 'confirm':
        payload = request.session.pop('attendance_import_preview', None)
        if not payload:
            messages.error(request, 'Nothing to import. Upload again.')
            return redirect('hr:attendance_import')
        saved = 0
        for row in payload['ready']:
            emp = Employee.objects.filter(pk=row['employee_id'], is_active=True).first()
            if not emp:
                continue
            ad = date.fromisoformat(row['date'])
            ci = _parse_time_cell(row.get('check_in'))
            co = _parse_time_cell(row.get('check_out'))
            overlap = attendance_overlap_message(emp, ad, ci, co)
            if overlap:
                continue
            AttendanceRecord.objects.create(
                employee=emp,
                date=ad,
                check_in=ci,
                check_out=co,
                status=row.get('status') or 'present',
                source='import',
            )
            recalculate_summary_for_employee_month(emp, ad.year, ad.month)
            saved += 1
        messages.success(request, f'Imported {saved} rows. Skipped {payload.get("skipped", 0)}.')
        return redirect('hr:attendance_list')

    if not f:
        messages.error(request, 'Upload a CSV file.')
        return redirect('hr:attendance_import')

    decoded = StringIO(f.read().decode('utf-8-sig', errors='replace'))
    reader = csv.DictReader(decoded)
    ready = []
    skipped = 0
    errors = []
    batch_sessions: dict[tuple[int, date], list[tuple]] = {}
    for raw in reader:
        row = {(k or '').strip().lstrip('\ufeff'): (v or '').strip() for k, v in raw.items()}
        code = (row.get('employee_code') or '').strip()
        if not code:
            errors.append({'row': row, 'reason': 'Missing employee_code'})
            continue
        emp = Employee.objects.filter(employee_code__iexact=code, is_active=True).first()
        if not emp:
            errors.append({'employee_code': code, 'reason': 'Employee not found'})
            continue
        d_raw = (row.get('date') or '').strip()
        try:
            ad = date.fromisoformat(d_raw[:10]) if d_raw else None
        except ValueError:
            errors.append({'employee_code': code, 'reason': 'Invalid date'})
            continue
        if not ad:
            errors.append({'employee_code': code, 'reason': 'Invalid date'})
            continue
        if is_uae_weekend(ad):
            skipped += 1
            continue
        if holiday_on_date_for_employee(ad, emp):
            skipped += 1
            continue

        ci = row.get('check_in') or None
        co = row.get('check_out') or None
        if ci == '':
            ci = None
        if co == '':
            co = None
        ci_parsed = _parse_time_cell(ci)
        co_parsed = _parse_time_cell(co)
        if (ci and not ci_parsed) or (co and not co_parsed):
            errors.append({'employee_code': code, 'reason': 'Invalid check_in or check_out time'})
            continue
        if ci_parsed and co_parsed and co_parsed <= ci_parsed:
            errors.append({'employee_code': code, 'reason': 'check_out must be after check_in'})
            continue

        batch_key = (emp.pk, ad)
        overlap = attendance_overlap_message(
            emp,
            ad,
            ci_parsed,
            co_parsed,
            extra_sessions=batch_sessions.get(batch_key, []),
        )
        if overlap:
            errors.append({'employee_code': code, 'reason': overlap})
            continue

        if ci_parsed and co_parsed:
            batch_sessions.setdefault(batch_key, []).append((ci_parsed, co_parsed))

        ready.append(
            {
                'employee_id': emp.pk,
                'date': ad.isoformat(),
                'check_in': ci,
                'check_out': co,
                'status': 'present',
            }
        )

    request.session['attendance_import_preview'] = {'ready': ready, 'skipped': skipped, 'errors': errors[:50]}
    return render(
        request,
        'hr/attendance_import_preview.html',
        {
            'title': 'Confirm import',
            'ready_count': len(ready),
            'skipped': skipped,
            'errors': errors[:50],
            'preview_rows': ready[:500],
        },
    )


def _coerce_lat_lng(lat, lng):
    try:
        if lat is None or lng is None:
            return None, None
        la = Decimal(str(lat))
        lo = Decimal(str(lng))
        if not (Decimal('-90') <= la <= Decimal('90') and Decimal('-180') <= lo <= Decimal('180')):
            return None, None
        return la, lo
    except (InvalidOperation, TypeError, ValueError, ArithmeticError):
        return None, None


def _parse_client_datetime(raw):
    if not raw:
        return django_timezone.localtime()
    try:
        s = str(raw).strip().replace('Z', '+00:00')
        dt = datetime_cls.fromisoformat(s)
        if dt.tzinfo is None:
            dt = django_timezone.make_aware(dt, django_timezone.get_current_timezone())
        return django_timezone.localtime(dt)
    except ValueError:
        return django_timezone.localtime()


def _fmt_coords(la, lo):
    if la is None or lo is None:
        return None
    return f'{la},{lo}'


def _resolve_technician_project_for_punch(employee: Employee, raw_project_id):
    """Optional project on clock-in: must be a project where this employee's user is a technician."""
    from apps.projects.models import Project

    if raw_project_id in (None, '', 0, '0', False):
        return None, None
    try:
        pid = int(raw_project_id)
    except (TypeError, ValueError):
        return None, 'Invalid project.'
    project = Project.objects.filter(pk=pid, is_active=True).first()
    if not project:
        return None, 'Project not found.'
    if not employee.user_id:
        return None, 'This employee has no linked user; project cannot be set from punch.'
    if not project.technicians.filter(pk=employee.user_id).exists():
        return None, 'This employee is not a technician on the selected project.'
    return project, None


def _punch_record_json(rec: AttendanceRecord, action: str):
    open_sess = open_attendance_session(rec.employee, rec.date)
    display = open_sess or rec
    msg = 'Clock in saved.' if action == 'check_in' else 'Clock out saved.'
    return {
        'ok': True,
        'message': msg,
        'employee_code': rec.employee.employee_code,
        'date': rec.date.isoformat(),
        'check_in': display.check_in.isoformat() if display.check_in else None,
        'check_out': display.check_out.isoformat() if display.check_out else None,
        'check_in_coords': _fmt_coords(display.check_in_latitude, display.check_in_longitude),
        'check_out_coords': _fmt_coords(display.check_out_latitude, display.check_out_longitude),
        'open_session': open_sess is not None,
    }


def _perform_attendance_punch(*, employee: Employee, action: str, when, lat, lng, source: str, project=None):
    if action not in ('check_in', 'check_out'):
        return False, 'Invalid action.'
    la, lo = _coerce_lat_lng(lat, lng)
    d = when.date()
    t = when.time().replace(microsecond=0)

    if action == 'check_in':
        if open_attendance_session(employee, d):
            return False, 'Already clocked in. Clock out first.'
        overlap = attendance_overlap_message(employee, d, t, check_out=None)
        if overlap:
            return False, overlap
        if project is None and employee.user_id:
            project = infer_project_for_technician(employee.user)
        status = 'present'
        rec = AttendanceRecord(
            employee=employee,
            date=d,
            status=status,
            source=source,
            check_in=t,
            check_in_latitude=la,
            check_in_longitude=lo,
            project=project,
        )
        rec.save()
        recalculate_summary_for_employee_month(employee, d.year, d.month)
        return True, rec

    open_sess = open_attendance_session(employee, d)
    if not open_sess:
        return False, 'Clock in first.'

    overlap = attendance_overlap_message(
        employee,
        d,
        open_sess.check_in,
        t,
        exclude_pk=open_sess.pk,
    )
    if overlap:
        return False, overlap

    open_sess.check_out = t
    open_sess.check_out_latitude = la
    open_sess.check_out_longitude = lo
    open_sess.save()
    recalculate_summary_for_employee_month(employee, d.year, d.month)
    return True, open_sess


@require_GET
def attendance_technician_projects(request):
    """JSON: projects where employee (by code) is assigned as technician. For public punch project picker."""
    from apps.projects.models import Project

    code = (request.GET.get('code') or '').strip()
    if not code:
        return JsonResponse({'ok': False, 'error': 'Employee code is required.'}, status=400)
    emp = Employee.objects.filter(employee_code__iexact=code, is_active=True).first()
    if not emp:
        return JsonResponse({'ok': False, 'error': 'Employee not found.'}, status=404)
    if not emp.user_id:
        return JsonResponse({'ok': True, 'projects': []})
    rows = (
        Project.objects.filter(is_active=True, technicians__pk=emp.user_id)
        .distinct()
        .order_by('-created_at', '-id')
        .values('id', 'project_code', 'name')
    )
    return JsonResponse({'ok': True, 'projects': list(rows)})


@method_decorator(ensure_csrf_cookie, name='dispatch')
class PublicAttendancePunchView(TemplateView):
    """Anonymous-friendly clock in/out (shareable link)."""

    template_name = 'hr/public_attendance_punch.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.hr.views_leave_extended import _public_leave_branding_context

        ctx.update(_public_leave_branding_context())
        ctx['title'] = 'Mark attendance'
        return ctx


@require_POST
def attendance_public_punch(request):
    try:
        data = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)

    code = (data.get('employee_code') or '').strip()
    action = (data.get('action') or '').strip()
    if not code:
        return JsonResponse({'ok': False, 'error': 'Employee code is required.'}, status=400)

    emp = Employee.objects.filter(employee_code__iexact=code, is_active=True).first()
    if not emp:
        return JsonResponse({'ok': False, 'error': 'Employee not found for this code.'}, status=404)

    project, err = _resolve_technician_project_for_punch(emp, data.get('project_id'))
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)

    when = _parse_client_datetime(data.get('client_time'))
    ok, result = _perform_attendance_punch(
        employee=emp,
        action=action,
        when=when,
        lat=data.get('latitude'),
        lng=data.get('longitude'),
        source='public_link',
        project=project if action == 'check_in' else None,
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': result}, status=400)
    return JsonResponse(_punch_record_json(result, action))


@login_required
@require_POST
def attendance_self_punch(request):
    emp = employee_for_user(request.user)
    if not emp:
        return JsonResponse({'ok': False, 'error': 'No employee profile is linked to your user.'}, status=400)
    try:
        data = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)
    action = (data.get('action') or '').strip()
    when = _parse_client_datetime(data.get('client_time'))
    project, err = _resolve_technician_project_for_punch(emp, data.get('project_id'))
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    ok, result = _perform_attendance_punch(
        employee=emp,
        action=action,
        when=when,
        lat=data.get('latitude'),
        lng=data.get('longitude'),
        source='self_service',
        project=project if action == 'check_in' else None,
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': result}, status=400)
    return JsonResponse(_punch_record_json(result, action))
