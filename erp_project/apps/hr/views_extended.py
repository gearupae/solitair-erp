"""Extended HR views: dashboard, attendance, compliance, WPS, self-service."""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from datetime import datetime as dt
from decimal import Decimal
from io import BytesIO, StringIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    RedirectView,
    TemplateView,
    UpdateView,
)

from apps.core.mixins import CreatePermissionMixin, PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.hr.attendance_utils import (
    attendance_snapshot_today,
    company_overtime_month,
    month_absent_rate_pct,
)
from apps.hr.forms_extended import EmployeeAdvanceForm, PayrollSettingsForm, PayrollTemplateForm
from apps.hr.models import Department, Employee, LeaveBalance, LeaveRequest, Payroll
from apps.hr.models_extended import (
    AdvanceRepayment,
    AttendanceRecord,
    AttendanceSummary,
    EmployeeAdvance,
    EmployeeHRProfile,
    GOSIRecord,
    KSACompliance,
    PayrollSettings,
    PayrollTemplate,
    UAECompliance,
    WPSRecord,
)
from apps.hr.payroll_allowances import (
    allowance_lines_from_hidden_json,
    ksa_company_payroll_filter,
    payrolls_for_company_entity,
    TEMPLATE_ALLOWANCE_CHOICES,
    TEMPLATE_ALLOWANCE_DEFAULT_DESCRIPTION,
    uae_company_payroll_filter,
)
from apps.hr.payslip_pdf import build_payslip_pdf, payslip_number
from apps.hr.expiry_alerts import filter_by_tab, get_expiry_alerts, summarize_alerts
from apps.hr.payroll_processing import apply_payroll_computations, estimate_payroll_deductions_preview
from apps.hr.gosi_export_service import build_gosi_excel_bytes, collect_gosi_payload, gosi_xlsx_filename
from apps.hr.wps_service import (
    build_uae_central_bank_sif,
    build_wps_excel_bytes,
    collect_wps_payload,
    wps_excel_filename,
    wps_sif_filename,
)
from apps.settings_app.models import Company


def employee_for_user(user):
    if not user.is_authenticated:
        return None
    return Employee.objects.filter(user=user, is_active=True).first()


def can_view_payroll_pdf(user, payroll):
    if user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'view'):
        return True
    emp = employee_for_user(user)
    return bool(emp and emp.pk == payroll.employee_id)


# --- Dashboard ---
class HRDashboardView(PermissionRequiredMixin, TemplateView):
    template_name = 'hr/dashboard.html'
    module_name = 'hr'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'HR Dashboard'
        emps = Employee.objects.filter(is_active=True)
        ctx['total_employees'] = emps.count()
        ctx['active_status'] = emps.filter(status='active').count()
        ctx['inactive_status'] = emps.exclude(status='active').count()

        ctx['dept_headcount'] = (
            Department.objects.filter(is_active=True)
            .annotate(c=Count('employees', filter=Q(employees__is_active=True)))
            .values('name', 'c')
        )

        ctx['pending_leave'] = LeaveRequest.objects.filter(
            is_active=True, status__in=['pending_manager', 'pending_hr']
        ).select_related(
            'employee', 'leave_type'
        )[:20]

        # Use Django's active timezone (settings.TIME_ZONE) so payroll "this month"
        # matches operators in Dubai and production servers running UTC.
        today = timezone.localdate()
        payrolls_month = Payroll.objects.filter(
            is_active=True,
            month__year=today.year,
            month__month=today.month,
        )
        ctx['payroll_draft'] = payrolls_month.filter(status='draft').count()
        ctx['payroll_processed'] = payrolls_month.filter(status='processed').count()
        ctx['payroll_paid'] = payrolls_month.filter(status='paid').count()
        ctx['payroll_total_net'] = payrolls_month.filter(status='paid').aggregate(s=Sum('net_salary'))['s'] or Decimal(
            '0'
        )

        payroll_by_company = []
        for co in Company.objects.filter(is_active=True).order_by('name'):
            pm = payrolls_for_company_entity(payrolls_month, co)
            paid_net = pm.filter(status='paid').aggregate(s=Sum('net_salary'))['s'] or Decimal('0')
            payroll_by_company.append(
                {
                    'company': co,
                    'draft': pm.filter(status='draft').count(),
                    'processed': pm.filter(status='processed').count(),
                    'paid': pm.filter(status='paid').count(),
                    'total_net': paid_net,
                    'currency': 'AED' if co.country == 'uae' else ('SAR' if co.country == 'ksa' else ''),
                }
            )
        ctx['payroll_by_company'] = payroll_by_company

        ctx['pending_payslip_emails'] = Payroll.objects.filter(
            month__year=today.year,
            month__month=today.month,
            status='paid',
            payslip_email_sent=False,
            is_active=True,
        ).exclude(employee__email='').count()

        ksa_pay_ids = ksa_company_payroll_filter(payrolls_month).values_list('pk', flat=True)
        gosi_agg = GOSIRecord.objects.filter(payroll_id__in=ksa_pay_ids).aggregate(
            ee=Sum('employee_contribution'),
            er=Sum('employer_contribution'),
        )
        ctx['gosi_month_employee'] = gosi_agg['ee'] or Decimal('0')
        ctx['gosi_month_employer'] = gosi_agg['er'] or Decimal('0')

        uae_paid = uae_company_payroll_filter(payrolls_month.filter(status='paid'))
        ctx['wps_month_net_uae'] = uae_paid.aggregate(s=Sum('net_salary'))['s'] or Decimal('0')
        uae_all = uae_company_payroll_filter(payrolls_month)
        ctx['wps_pending_uae'] = WPSRecord.objects.filter(
            payroll_id__in=uae_all.values_list('pk', flat=True),
            status='pending',
        ).count()
        ctx['wps_submitted_uae'] = WPSRecord.objects.filter(
            payroll_id__in=uae_all.values_list('pk', flat=True),
            status='submitted',
        ).count()

        adv_active = EmployeeAdvance.objects.filter(
            is_active=True,
            status=EmployeeAdvance.STATUS_ACTIVE,
            amount_remaining__gt=0,
        )
        ctx['advance_active_employees'] = adv_active.values('employee').distinct().count()
        ctx['advance_outstanding_total'] = adv_active.aggregate(s=Sum('amount_remaining'))['s'] or Decimal('0')

        cid = self.request.GET.get('company')
        did = self.request.GET.get('department')
        loc_f = self.request.GET.get('location')
        tab = self.request.GET.get('tab') or 'all'

        company_id = int(cid) if cid and str(cid).isdigit() else None
        department_id = int(did) if did and str(did).isdigit() else None
        location = loc_f if loc_f in ('uae', 'ksa') else None

        base_rows = get_expiry_alerts(company_id=company_id, location=location, department_id=department_id)
        ctx['expiry_summary'] = summarize_alerts(base_rows)
        ctx['expiry_has_issues'] = len(base_rows) > 0
        ctx['expiry_tab'] = tab

        tab_rows = filter_by_tab(base_rows, tab)
        enriched = []
        for r in tab_rows:
            x = dict(r)
            dr = x['days_remaining']
            if dr < 0:
                ago = abs(dr)
                x['days_label'] = f'Expired {ago} day ago' if ago == 1 else f'Expired {ago} days ago'
            elif dr == 0:
                x['days_label'] = 'Due today'
            elif dr == 1:
                x['days_label'] = '1 day'
            else:
                x['days_label'] = f'{dr} days'
            enriched.append(x)
        ctx['expiry_rows'] = enriched

        ctx['filter_company'] = str(cid or '')
        ctx['filter_department'] = str(did or '')
        ctx['filter_location'] = str(loc_f or '')
        ctx['expiry_companies'] = Company.objects.filter(is_active=True).order_by('name')
        ctx['expiry_departments'] = Department.objects.filter(is_active=True).order_by('name')

        ctx['att_snap'] = attendance_snapshot_today()
        ctx['att_absent_rate_pct'] = month_absent_rate_pct(today.year, today.month)
        ctx['att_ot_company_month'] = company_overtime_month(today.year, today.month)

        ctx['gosi_month_total'] = ctx['gosi_month_employee']

        ctx['wps_pending'] = ctx['wps_pending_uae']

        ctx['leave_dashboard_pending_count'] = LeaveRequest.objects.filter(
            is_active=True, status__in=['pending_manager', 'pending_hr']
        ).count()
        ctx['employees_on_leave_today'] = (
            LeaveRequest.objects.filter(
                is_active=True,
                status='approved',
                start_date__lte=today,
                end_date__gte=today,
            )
            .select_related('employee', 'leave_type')
            .order_by('employee__first_name')[:30]
        )
        week_end = today + timedelta(days=7)
        ctx['leave_upcoming_week'] = (
            LeaveRequest.objects.filter(
                is_active=True,
                status='approved',
                start_date__gte=today,
                start_date__lte=week_end,
            )
            .select_related('employee', 'leave_type')
            .order_by('start_date')[:30]
        )
        low = []
        for lb in LeaveBalance.objects.filter(year=today.year).select_related('employee', 'leave_type'):
            if (
                lb.leave_type.code in ('UAE_ANNUAL', 'KSA_ANNUAL')
                and lb.remaining_days < Decimal('5')
            ):
                low.append(lb)
        ctx['leave_low_balance_alerts'] = low[:25]

        return ctx


# --- Payroll settings ---
class PayrollSettingsView(UpdatePermissionMixin, UpdateView):
    model = PayrollSettings
    form_class = PayrollSettingsForm
    template_name = 'hr/payroll_settings_form.html'
    success_url = reverse_lazy('hr:payroll_settings')
    module_name = 'hr'

    def get_object(self, queryset=None):
        obj, _ = PayrollSettings.objects.get_or_create(pk=1)
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Payroll settings'
        return ctx


class AttendanceMonthlySummaryView(PermissionRequiredMixin, TemplateView):
    template_name = 'hr/attendance_summary.html'
    module_name = 'hr'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = get_object_or_404(Employee, pk=self.kwargs['employee_pk'], is_active=True)
        year = int(self.kwargs['year'])
        month = int(self.kwargs['month'])
        mf = date(year, month, 1)
        summ = AttendanceSummary.objects.filter(employee=emp, month=mf).first()
        ctx['title'] = f'Attendance summary — {emp.full_name}'
        ctx['employee'] = emp
        ctx['summary'] = summ
        ctx['month_label'] = mf.strftime('%B %Y')
        return ctx


class ComplianceDashboardView(PermissionRequiredMixin, TemplateView):
    template_name = 'hr/compliance_dashboard.html'
    module_name = 'hr'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        from apps.hr.compliance_utils import expiry_band, worst_band
        from apps.settings_app.models import Company

        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Compliance'

        loc = self.request.GET.get('location') or ''
        comp = self.request.GET.get('company') or ''
        exp_filter = self.request.GET.get('expiry') or 'all'

        qs = Employee.objects.filter(is_active=True).select_related(
            'company', 'department', 'designation', 'uae_compliance', 'ksa_compliance'
        ).order_by('first_name', 'last_name')
        if loc in ('uae', 'ksa', 'other'):
            qs = qs.filter(location=loc)
        if comp.isdigit():
            qs = qs.filter(company_id=int(comp))

        def worst_for(emp, uc, kc):
            bands = []
            if emp.location == 'uae':
                if emp.visa_expiry:
                    bands.append(expiry_band(emp.visa_expiry))
                if uc:
                    for dt in (
                        uc.emirates_id_expiry,
                        uc.passport_expiry,
                        uc.labour_card_expiry,
                        uc.medical_insurance_expiry,
                    ):
                        if dt:
                            bands.append(expiry_band(dt))
            elif emp.location == 'ksa' and kc:
                for dt in (
                    kc.iqama_expiry,
                    kc.work_permit_expiry,
                    kc.medical_insurance_expiry,
                    kc.passport_expiry,
                ):
                    if dt:
                        bands.append(expiry_band(dt))
            else:
                return 'unknown'
            return worst_band(bands) if bands else 'unknown'

        rows = []
        for emp in qs:
            uc = getattr(emp, 'uae_compliance', None)
            kc = getattr(emp, 'ksa_compliance', None)
            worst = worst_for(emp, uc, kc)
            if exp_filter == 'amber' and worst != 'amber':
                continue
            if exp_filter == 'red' and worst != 'red':
                continue
            rows.append({'employee': emp, 'uc': uc, 'kc': kc, 'worst': worst})

        ctx['rows'] = rows
        ctx['filter_location'] = loc
        ctx['filter_company'] = comp
        ctx['filter_expiry'] = exp_filter
        ctx['companies'] = Company.objects.filter(is_active=True).order_by('name')
        return ctx


def _optional_positive_int(val, default: int, *, min_val: int | None = None, max_val: int | None = None) -> int:
    """Parse GET param; empty string or missing uses default (GET may send month=&year=2024)."""
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    try:
        n = int(s)
    except ValueError:
        return default
    if min_val is not None:
        n = max(min_val, n)
    if max_val is not None:
        n = min(max_val, n)
    return n


@login_required
def gosi_export(request):
    """KSA GOSI — preview page or ?download=1 for Excel (.xlsx). Download upserts GOSIRecord rows."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'view')):
        raise Http404()

    today = date.today()
    cid = (request.GET.get('company') or '').strip()
    month = _optional_positive_int(request.GET.get('month'), today.month, min_val=1, max_val=12)
    year = _optional_positive_int(request.GET.get('year'), today.year, min_val=2000, max_val=2100)

    company = None
    if cid.isdigit():
        company = Company.objects.filter(pk=int(cid), is_active=True, country='ksa').first()

    month_first = date(year, month, 1)
    payload = (
        collect_gosi_payload(company, month_first, sync_records=False) if company else None
    )

    if request.GET.get('download') and company is not None:
        payload = collect_gosi_payload(company, month_first, sync_records=True)
        try:
            data = build_gosi_excel_bytes(payload, company, month_first)
        except ImportError:
            return HttpResponse(
                'Excel export requires the openpyxl package.',
                status=500,
                content_type='text/plain; charset=utf-8',
            )
        resp = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{gosi_xlsx_filename(company, month_first)}"'
        return resp

    td = date.today()
    return render(
        request,
        'hr/gosi_export.html',
        {
            'title': 'GOSI export (KSA)',
            'company': company,
            'month': month,
            'year': year,
            'month_first': month_first,
            'payload': payload,
            'months': list(range(1, 13)),
            'years': list(range(td.year - 2, td.year + 3)),
            'ksa_companies': Company.objects.filter(is_active=True, country='ksa').order_by('name'),
        },
    )


@login_required
def wps_export(request):
    """UAE WPS — preview page, ?download=1 for .SIF, ?download=1&format=xlsx for Excel."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'view')):
        raise Http404()

    today = date.today()
    cid = (request.GET.get('company') or '').strip()
    month = _optional_positive_int(request.GET.get('month'), today.month, min_val=1, max_val=12)
    year = _optional_positive_int(request.GET.get('year'), today.year, min_val=2000, max_val=2100)

    company = None
    if cid.isdigit():
        company = Company.objects.filter(pk=int(cid), is_active=True, country='uae').first()

    month_first = date(year, month, 1)
    payload = collect_wps_payload(company, month_first) if company else None

    if request.GET.get('download') and company is not None:
        # Always build from fresh payload; missing IBAN/MOL etc. still produce a file (warnings on preview).
        payload = collect_wps_payload(company, month_first)
        fmt = (request.GET.get('format') or 'sif').strip().lower()
        if fmt in ('xlsx', 'excel', 'xls'):
            try:
                data = build_wps_excel_bytes(company, month_first, payload)
            except ImportError:
                return HttpResponse(
                    'Excel export requires the openpyxl package.',
                    status=500,
                    content_type='text/plain; charset=utf-8',
                )
            resp = HttpResponse(
                data,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            resp['Content-Disposition'] = f'attachment; filename="{wps_excel_filename(company, month_first)}"'
            return resp
        content = build_uae_central_bank_sif(company, month_first, payload.get('edr_rows') or [])
        resp = HttpResponse(content, content_type='text/plain; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="{wps_sif_filename(company, month_first)}"'
        return resp

    td = date.today()
    return render(
        request,
        'hr/wps_export.html',
        {
            'title': 'WPS SIF export (UAE)',
            'company': company,
            'month': month,
            'year': year,
            'month_first': month_first,
            'payload': payload,
            'months': list(range(1, 13)),
            'years': list(range(td.year - 2, td.year + 3)),
            'uae_companies': Company.objects.filter(is_active=True, country='uae').order_by('name'),
        },
    )


# --- Payslip PDF ---
@login_required
def payroll_payslip_pdf(request, pk):
    payroll = get_object_or_404(
        Payroll.objects.select_related('employee', 'company').prefetch_related('allowance_lines', 'deduction_lines'),
        pk=pk,
        is_active=True,
    )
    if not can_view_payroll_pdf(request.user, payroll):
        raise Http404()
    pdf = build_payslip_pdf(payroll)
    name = f'{payslip_number(payroll)}.pdf'
    return FileResponse(BytesIO(pdf), as_attachment=True, filename=name)


# --- Bulk payroll process ---
@login_required
def payroll_bulk_process_month(request):
    if request.method != 'POST':
        return redirect('hr:payroll_list')
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:payroll_list')

    raw = request.POST.get('month', '')
    try:
        y, m = [int(x) for x in raw.split('-')[:2]]
        mf = date(y, m, 1)
    except Exception:
        messages.error(request, 'Invalid month.')
        return redirect('hr:payroll_list')

    from apps.core.audit import audit_payroll_process

    qs = Payroll.objects.filter(month=mf, status='draft', is_active=True)
    cid = request.POST.get('company')
    if cid and str(cid).isdigit():
        co = Company.objects.filter(pk=int(cid), is_active=True).first()
        if co:
            qs = payrolls_for_company_entity(qs, co)
    ok = 0
    err = []
    for pr in qs:
        try:
            apply_payroll_computations(pr)
            pr.refresh_from_db()
            pr.post_to_accounting(user=request.user)
            audit_payroll_process(pr, request.user, request=request)
            ok += 1
        except Exception as exc:
            err.append(f'{pr.employee.employee_code}: {exc}')
    messages.success(request, f'Processed {ok} payroll(s).')
    if err:
        messages.warning(request, 'Some failed: ' + '; '.join(err[:5]))
    return redirect('hr:payroll_list')


@login_required
def payroll_bulk_pay_month(request):
    """Pay all processed (unpaid) payrolls for a month in one run — same journal rules as single Pay."""
    if request.method != 'POST':
        return redirect('hr:payroll_list')
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:payroll_list')

    raw = request.POST.get('month', '')
    try:
        y, m = [int(x) for x in raw.split('-')[:2]]
        mf = date(y, m, 1)
    except Exception:
        messages.error(request, 'Invalid month.')
        return redirect('hr:payroll_list')

    from apps.finance.models import BankAccount

    bank_account_id = request.POST.get('bank_account')
    bank_account = BankAccount.objects.filter(pk=bank_account_id, is_active=True).first()
    if not bank_account:
        messages.error(request, 'Select a valid bank account.')
        return redirect('hr:payroll_list')

    payment_date_raw = (request.POST.get('payment_date') or '').strip()
    try:
        if payment_date_raw:
            payment_date = dt.strptime(payment_date_raw, '%Y-%m-%d').date()
        else:
            payment_date = date.today()
    except ValueError:
        payment_date = date.today()

    reference = (request.POST.get('reference') or '').strip()

    qs = Payroll.objects.filter(
        month=mf,
        status='processed',
        is_active=True,
        payment_journal_entry__isnull=True,
    ).select_related('employee', 'company')
    cid = request.POST.get('company')
    if cid and str(cid).isdigit():
        co = Company.objects.filter(pk=int(cid), is_active=True).first()
        if co:
            qs = payrolls_for_company_entity(qs, co)

    if not qs.exists():
        messages.warning(request, 'No processed (unpaid) payrolls found for that month and filter.')
        return redirect('hr:payroll_list')

    from apps.hr import hr_notifications

    ok = 0
    err = []
    for pr in qs.order_by('employee__employee_code'):
        try:
            pr.post_payment_journal(
                bank_account=bank_account,
                payment_date=payment_date,
                reference=reference,
                user=request.user,
            )
            pr.refresh_from_db()
            hr_notifications.on_payroll_paid(pr, request=request)
            ok += 1
        except Exception as exc:
            err.append(f'{pr.employee.employee_code}: {exc}')

    messages.success(request, f'Processed payment for {ok} payroll(s).')
    if err:
        messages.warning(request, 'Some failed: ' + '; '.join(err[:8]))
    return redirect('hr:payroll_list')


@login_required
def payroll_template_json(request, pk):
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'view')):
        raise Http404()
    t = get_object_or_404(PayrollTemplate, pk=pk, is_active=True)
    from apps.hr.payroll_allowances import normalize_template_allowance_lines_json
    from decimal import Decimal

    bs = Decimal(str(t.basic_salary)).quantize(Decimal('0.01'))
    return JsonResponse(
        {
            'basic_salary': str(bs),
            'allowance_lines': normalize_template_allowance_lines_json(t.allowance_lines or []),
            'name': t.name,
        }
    )


@login_required
def payroll_generate_drafts(request):
    if request.method != 'POST':
        return redirect('hr:payroll_list')
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:payroll_list')

    raw = request.POST.get('month', '')
    try:
        y, m = [int(x) for x in raw.split('-')[:2]]
    except Exception:
        messages.error(request, 'Invalid month.')
        return redirect('hr:payroll_list')

    cid = request.POST.get('company')
    company_id = int(cid) if cid and str(cid).isdigit() else None
    loc = (request.POST.get('location') or '').strip().upper()
    location = loc if loc in ('UAE', 'KSA') else None

    from apps.hr.payroll_generation_service import generate_draft_payrolls_for_month

    n, suffix = generate_draft_payrolls_for_month(y, m, company_id=company_id, location=location)
    messages.success(request, f'Generated {n} payroll drafts for {suffix}.')
    return redirect('hr:payroll_list')


class PayrollTemplateListView(PermissionRequiredMixin, ListView):
    model = PayrollTemplate
    template_name = 'hr/payroll_template_list.html'
    context_object_name = 'templates'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        return PayrollTemplate.objects.filter(is_active=True).select_related('company').order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Salary templates'
        ctx['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'edit'
        )
        from django.db.models import Count

        dup_qs = (
            PayrollTemplate.objects.filter(is_active=True)
            .values('name', 'company_id')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )
        ctx['template_duplicate_names'] = dup_qs.exists()
        return ctx


class PayrollTemplateCreateView(CreatePermissionMixin, CreateView):
    model = PayrollTemplate
    form_class = PayrollTemplateForm
    template_name = 'hr/payroll_template_form.html'
    success_url = reverse_lazy('hr:payroll_template_list')
    module_name = 'hr'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add salary template'
        ctx['template_allowance_choices_json'] = json.dumps(TEMPLATE_ALLOWANCE_CHOICES)
        ctx['tpl_allowance_defaults_json'] = json.dumps(TEMPLATE_ALLOWANCE_DEFAULT_DESCRIPTION)
        return ctx

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.allowance_lines = allowance_lines_from_hidden_json(form.cleaned_data.get('allowance_lines'))
        obj.save()
        self.object = obj
        messages.success(self.request, 'Template saved.')
        return HttpResponseRedirect(self.get_success_url())


class PayrollTemplateUpdateView(UpdatePermissionMixin, UpdateView):
    model = PayrollTemplate
    form_class = PayrollTemplateForm
    template_name = 'hr/payroll_template_form.html'
    success_url = reverse_lazy('hr:payroll_template_list')
    module_name = 'hr'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit template: {self.object.name}'
        ctx['template_allowance_choices_json'] = json.dumps(TEMPLATE_ALLOWANCE_CHOICES)
        ctx['tpl_allowance_defaults_json'] = json.dumps(TEMPLATE_ALLOWANCE_DEFAULT_DESCRIPTION)
        return ctx

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.allowance_lines = allowance_lines_from_hidden_json(form.cleaned_data.get('allowance_lines'))
        obj.save()
        self.object = obj
        messages.success(self.request, 'Template updated.')
        return HttpResponseRedirect(self.get_success_url())


def _parse_month_query(val: str | None) -> date | None:
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    if len(val) == 7 and val[4] == '-':
        try:
            y, m = val.split('-', 1)
            return date(int(y), int(m), 1)
        except ValueError:
            return None
    if len(val) >= 10 and val[4] == '-' and val[7] == '-':
        try:
            d = dt.strptime(val[:10], '%Y-%m-%d').date()
            return date(d.year, d.month, 1)
        except ValueError:
            return None
    return None


@login_required
def payroll_deduction_preview(request):
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'view')):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    epk = request.GET.get('employee')
    if not epk or not str(epk).isdigit():
        return JsonResponse({'error': 'employee required'}, status=400)
    month_first = _parse_month_query(request.GET.get('month'))
    if not month_first:
        return JsonResponse({'error': 'month required'}, status=400)

    def _money_param(key: str) -> Decimal:
        raw = (request.GET.get(key) or '0').strip().replace(',', '')
        try:
            return Decimal(raw)
        except Exception:
            return Decimal('0')

    basic = _money_param('basic')
    allowances = _money_param('allowances')
    manual = _money_param('manual')

    prev = estimate_payroll_deductions_preview(
        employee_pk=int(epk),
        month_first=month_first,
        basic_salary=basic,
        allowances_total=allowances,
        manual_misc=manual,
    )

    def _s(d: Decimal) -> str:
        return str(d.quantize(Decimal('0.01')))

    return JsonResponse(
        {
            'absent': _s(prev['absent']),
            'late': _s(prev['late']),
            'unpaid_leave': _s(prev['unpaid_leave']),
            'half_pay_leave': _s(prev.get('half_pay_leave', Decimal('0'))),
            'sick_tiered': _s(prev.get('sick_tiered', Decimal('0'))),
            'iloe': _s(prev['iloe']),
            'gosi_employee': _s(prev['gosi_employee']),
            'advance': _s(prev['advance']),
            'manual': _s(prev['manual']),
            'total': _s(prev['total']),
            'estimated_net': _s(prev['estimated_net']),
            'attendance_finalized': prev['attendance_finalized'],
        }
    )


class EmployeeAdvanceListView(PermissionRequiredMixin, ListView):
    model = EmployeeAdvance
    template_name = 'hr/payroll_advance_list.html'
    context_object_name = 'advances'
    module_name = 'hr'
    permission_type = 'view'
    paginate_by = 50

    def get_queryset(self):
        qs = EmployeeAdvance.objects.filter(is_active=True).select_related('employee', 'approved_by').order_by(
            '-date_issued', '-pk'
        )
        eid = self.request.GET.get('employee')
        if eid and str(eid).isdigit():
            qs = qs.filter(employee_id=int(eid))
        st = self.request.GET.get('status')
        if st in dict(EmployeeAdvance.STATUS_CHOICES):
            qs = qs.filter(status=st)
        m = self.request.GET.get('issued_month')
        if m and isinstance(m, str) and len(m) >= 7 and m[4:5] == '-':
            try:
                y, mo = m.split('-', 1)
                qs = qs.filter(date_issued__year=int(y), date_issued__month=int(mo))
            except ValueError:
                pass
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Employee advances'
        ctx['employees'] = Employee.objects.filter(is_active=True).order_by('first_name', 'last_name')
        ctx['status_choices'] = EmployeeAdvance.STATUS_CHOICES
        ctx['filter_employee'] = self.request.GET.get('employee', '')
        ctx['filter_status'] = self.request.GET.get('status', '')
        ctx['filter_issued_month'] = self.request.GET.get('issued_month', '')
        ctx['can_add'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'edit'
        )
        return ctx


class EmployeeAdvanceCreateView(CreatePermissionMixin, CreateView):
    model = EmployeeAdvance
    form_class = EmployeeAdvanceForm
    template_name = 'hr/payroll_advance_form.html'
    success_url = reverse_lazy('hr:payroll_advance_list')
    module_name = 'hr'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Record employee advance'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Advance recorded.')
        return super().form_valid(form)


class EmployeeAdvanceDetailView(PermissionRequiredMixin, DetailView):
    model = EmployeeAdvance
    template_name = 'hr/payroll_advance_detail.html'
    context_object_name = 'advance'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        return EmployeeAdvance.objects.filter(is_active=True).select_related('employee', 'approved_by')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Advance — {self.object.employee.full_name}'
        ctx['repayments'] = self.object.repayments.select_related('payroll').order_by('-date', '-pk')
        return ctx


class PayrollTemplateDeleteView(UpdatePermissionMixin, DeleteView):
    model = PayrollTemplate
    template_name = 'hr/payroll_template_confirm_delete.html'
    success_url = reverse_lazy('hr:payroll_template_list')
    module_name = 'hr'

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.is_active = False
        self.object.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, 'Template deactivated.')
        return HttpResponseRedirect(self.success_url)


# --- Self-service ---
class SelfServiceProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'hr/self_service/profile.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = employee_for_user(self.request.user)
        ctx['employee'] = emp
        ctx['today_attendance'] = None
        if emp:
            today = timezone.localdate()
            rec = AttendanceRecord.objects.filter(
                employee=emp, date=today, is_active=True
            ).first()
            if rec:
                ctx['today_attendance'] = {
                    'has_check_in': bool(rec.check_in),
                    'has_check_out': bool(rec.check_out),
                    'check_in_display': rec.check_in.strftime('%H:%M') if rec.check_in else '',
                    'check_out_display': rec.check_out.strftime('%H:%M') if rec.check_out else '',
                }
            else:
                ctx['today_attendance'] = {
                    'has_check_in': False,
                    'has_check_out': False,
                    'check_in_display': '',
                    'check_out_display': '',
                }
        ctx['title'] = 'Clock in / out'
        ctx['can_link_help'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'edit'
        )
        return ctx


class SelfServicePayslipsView(LoginRequiredMixin, ListView):
    template_name = 'hr/self_service/payslips.html'
    context_object_name = 'payrolls'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'My payslips'
        return ctx

    def get_queryset(self):
        emp = employee_for_user(self.request.user)
        if not emp:
            return Payroll.objects.none()
        return Payroll.objects.filter(employee=emp, is_active=True).order_by('-month')


class SelfServiceAttendanceView(LoginRequiredMixin, RedirectView):
    permanent = False
    pattern_name = 'hr:attendance_records_self'


class SelfServiceDocumentsView(LoginRequiredMixin, TemplateView):
    template_name = 'hr/self_service/documents.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = employee_for_user(self.request.user)
        if not emp:
            raise Http404()
        uc = getattr(emp, 'uae_compliance', None)
        kc = getattr(emp, 'ksa_compliance', None)
        ctx['employee'] = emp
        ctx['uc'] = uc
        ctx['kc'] = kc
        ctx['title'] = 'My documents'
        return ctx


@login_required
def self_service_leave_redirect(request):
    return HttpResponseRedirect(reverse('hr:leave_list'))
