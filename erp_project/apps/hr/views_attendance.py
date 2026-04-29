"""Attendance views: marks, list, import, monthly summary, holidays, settings."""
from __future__ import annotations

import csv
from urllib.parse import urlencode
from datetime import date, datetime as datetime_cls
from decimal import Decimal
from io import StringIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, HttpResponseRedirect, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import DeleteView, FormView, ListView, TemplateView, UpdateView
from django.views.generic.edit import CreateView

from apps.core.mixins import CreatePermissionMixin, PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.hr.attendance_utils import (
    attendance_snapshot_today,
    holiday_on_date_for_employee,
    is_uae_weekend,
    mark_all_present_today,
    month_absent_rate_pct,
    company_overtime_month,
    recalculate_summary_for_employee_month,
)
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
            try:
                kwargs['instance'] = AttendanceRecord.objects.get(employee=emp, date=ad)
            except AttendanceRecord.DoesNotExist:
                kwargs['instance'] = AttendanceRecord(employee=emp, date=ad)
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
def attendance_import_csv(request):
    """CSV import with preview (session) + skip weekends/holidays."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:attendance_list')

    if request.method == 'GET':
        return render(
            request,
            'hr/attendance_import.html',
            {'title': 'Import attendance CSV'},
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
            AttendanceRecord.objects.update_or_create(
                employee=emp,
                date=ad,
                defaults={
                    'check_in': ci,
                    'check_out': co,
                    'status': row.get('status') or 'present',
                    'source': 'import',
                },
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

