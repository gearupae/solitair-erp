"""Leave types CRUD, pending HR queue, calendar, public apply, AJAX helpers."""
from __future__ import annotations

from calendar import monthcalendar
from datetime import date, timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from apps.core.mixins import CreatePermissionMixin, PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.hr.forms import LeaveTypeForm, PublicLeaveApplicationForm
from apps.hr.leave_balance_service import get_or_compute_remaining, sync_leave_balances_for_employee
from apps.hr.models import Employee, LeaveBalance, LeaveRequest, LeaveType


class LeaveTypeListView(PermissionRequiredMixin, ListView):
    model = LeaveType
    template_name = 'hr/leavetype_list.html'
    context_object_name = 'leave_types'
    module_name = 'hr'
    permission_type = 'edit'

    def get_queryset(self):
        return LeaveType.objects.all().order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Leave types'
        return ctx


class LeaveTypeCreateView(CreatePermissionMixin, CreateView):
    module_name = 'hr'
    model = LeaveType
    template_name = 'hr/leavetype_form.html'
    form_class = LeaveTypeForm
    success_url = reverse_lazy('hr:leave_type_list')

    def form_valid(self, form):
        messages.success(self.request, 'Leave type saved.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add Leave Type'
        return ctx


class LeaveTypeUpdateView(UpdatePermissionMixin, UpdateView):
    model = LeaveType
    form_class = LeaveTypeForm
    template_name = 'hr/leavetype_form.html'
    success_url = reverse_lazy('hr:leave_type_list')
    module_name = 'hr'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit Leave Type: {self.object.name}'
        return ctx


def leave_type_deactivate(request, pk):
    if request.method != 'POST':
        return redirect('hr:leave_type_list')
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:leave_type_list')
    lt = get_object_or_404(LeaveType, pk=pk)
    lt.is_active = False
    lt.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, 'Leave type deactivated.')
    return redirect('hr:leave_type_list')


class LeavePendingHRView(PermissionRequiredMixin, ListView):
    """Requests awaiting HR final approval."""

    model = LeaveRequest
    template_name = 'hr/leave_pending_hr.html'
    context_object_name = 'leave_requests'
    module_name = 'hr'
    permission_type = 'approve'

    def get_queryset(self):
        from apps.hr.leave_approval_rules import user_can_hr_approve

        if not user_can_hr_approve(self.request.user):
            return LeaveRequest.objects.none()
        return (
            LeaveRequest.objects.filter(is_active=True, status='pending_hr')
            .select_related('employee', 'leave_type', 'employee__department')
            .order_by('created_at')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Leave pending (HR)'
        from apps.hr.leave_approval_rules import annotate_leave_approval_actions

        annotate_leave_approval_actions(self.request.user, ctx['leave_requests'])
        return ctx


class LeaveCalendarView(PermissionRequiredMixin, TemplateView):
    template_name = 'hr/leave_calendar.html'
    module_name = 'hr'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = date.today()
        y = int(self.request.GET.get('year') or today.year)
        m = int(self.request.GET.get('month') or today.month)
        dept_id = self.request.GET.get('department')
        emp_id = self.request.GET.get('employee')
        ctx['title'] = 'Leave calendar'
        ctx['year'] = y
        ctx['month'] = m
        ctx['calendar_weeks'] = monthcalendar(y, m)
        first = date(y, m, 1)
        from calendar import monthrange

        last = date(y, m, monthrange(y, m)[1])
        qs = LeaveRequest.objects.filter(
            is_active=True,
            status='approved',
            start_date__lte=last,
            end_date__gte=first,
        ).select_related('employee', 'leave_type')
        if dept_id and str(dept_id).isdigit():
            qs = qs.filter(employee__department_id=int(dept_id))
        if emp_id and str(emp_id).isdigit():
            qs = qs.filter(employee_id=int(emp_id))
        ctx['approved_leaves'] = qs
        from apps.hr.models import Department

        ctx['filter_departments'] = Department.objects.filter(is_active=True).order_by('name')
        ctx['filter_employees'] = Employee.objects.filter(is_active=True).order_by('first_name', 'last_name')
        ctx['filter_department'] = dept_id or ''
        ctx['filter_employee'] = emp_id or ''
        return ctx


def _serialize_leaves_for_public(emp: Employee):
    today = date.today()
    sync_leave_balances_for_employee(emp.pk)
    balances = []
    for lb in LeaveBalance.objects.filter(employee=emp, year=today.year).select_related('leave_type'):
        balances.append(
            {
                'leave_type': lb.leave_type.name,
                'remaining': str(lb.remaining_days),
                'code': lb.leave_type.code or '',
            }
        )
    blocks = []
    for lr in LeaveRequest.objects.filter(
        employee=emp,
        status__in=['approved', 'pending_manager', 'pending_hr'],
        is_active=True,
    ):
        blocks.append({'start': lr.start_date.isoformat(), 'end': lr.end_date.isoformat(), 'status': lr.status})
    return {'balances': balances, 'blocked_ranges': blocks}


@require_GET
def public_leave_lookup(request):
    code = (request.GET.get('code') or '').strip()
    if not code:
        return JsonResponse({'ok': False, 'error': 'Employee code required.'}, status=400)
    emp = Employee.objects.filter(employee_code__iexact=code, is_active=True).first()
    if not emp:
        return JsonResponse({'ok': False, 'error': 'Employee not found.'}, status=404)
    data = _serialize_leaves_for_public(emp)
    data['ok'] = True
    data['employee'] = {
        'name': emp.full_name,
        'department': emp.department.name if emp.department_id else '',
        'location': emp.location,
        'id': emp.pk,
    }
    return JsonResponse(data)


@require_GET
def employee_leave_context(request):
    """JSON context for leave forms: ?employee_id= or ?code= (code is anonymous)."""
    from apps.hr.leave_context_service import build_employee_leave_context_dict

    code = (request.GET.get('code') or '').strip()
    emp_id = request.GET.get('employee_id')
    emp = None
    if code:
        emp = Employee.objects.filter(employee_code__iexact=code, is_active=True).first()
        if not emp:
            return JsonResponse({'ok': False, 'error': 'Employee not found.'}, status=404)
    elif emp_id and str(emp_id).isdigit():
        if not request.user.is_authenticated:
            return JsonResponse({'ok': False, 'error': 'Authentication required.'}, status=401)
        emp = Employee.objects.filter(pk=int(emp_id), is_active=True).first()
        if not emp:
            return JsonResponse({'ok': False, 'error': 'Employee not found.'}, status=404)
        allowed = (
            request.user.is_superuser
            or PermissionChecker.has_permission(request.user, 'hr', 'create')
            or PermissionChecker.has_permission(request.user, 'hr', 'view')
        )
        if not allowed:
            try:
                self_prof = Employee.objects.get(user=request.user, is_active=True)
                allowed = self_prof.pk == emp.pk
            except Employee.DoesNotExist:
                allowed = False
        if not allowed:
            return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    else:
        return JsonResponse({'ok': False, 'error': 'Provide employee_id or code.'}, status=400)

    data = build_employee_leave_context_dict(emp)
    return JsonResponse(data)


def leave_balance_ajax(request):
    emp_id = request.GET.get('employee_id')
    lt_id = request.GET.get('leave_type_id')
    if not emp_id or not lt_id:
        return JsonResponse({'remaining': None})
    emp = get_object_or_404(Employee, pk=emp_id)
    lt = get_object_or_404(LeaveType, pk=lt_id)
    year = int(request.GET.get('year') or date.today().year)
    rem = get_or_compute_remaining(emp, lt, year)
    return JsonResponse({'remaining': str(rem)})


def _public_leave_branding_context():
    from apps.settings_app.models import CompanySettings

    co = CompanySettings.get_settings()
    logo_url = ''
    if co and getattr(co, 'logo', None) and co.logo.name:
        try:
            logo_url = co.logo.url
        except ValueError:
            logo_url = ''
    return {
        'company_name': co.company_name if co else '',
        'company_logo_url': logo_url,
    }


class PublicLeaveApplyView(TemplateView):
    """Anonymous-friendly leave application (HR shares URL)."""

    template_name = 'hr/public_leave_apply.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Apply for Leave'
        ctx.update(_public_leave_branding_context())
        ctx['form'] = PublicLeaveApplicationForm()
        return ctx

    def post(self, request, *args, **kwargs):
        ctx = self.get_context_data(**kwargs)
        form = PublicLeaveApplicationForm(request.POST, request.FILES)
        ctx['form'] = form
        if not form.is_valid():
            return self.render_to_response(ctx)

        from apps.hr.leave_balance_service import sync_leave_balances_for_employee
        from apps.hr.leave_context_service import create_split_leave_pair
        from apps.hr import hr_notifications

        emp = form.cleaned_data['employee']
        lt = form.cleaned_data['leave_type']
        sd = form.cleaned_data['start_date']
        ed = form.cleaned_data['end_date']
        reason = form.cleaned_data.get('reason') or ''
        overflow = form.cleaned_data.get('overflow_action') or ''

        reliever = form.cleaned_data.get('reliever')

        if overflow == 'split':
            lr1, lr2 = create_split_leave_pair(
                employee=emp,
                leave_type_paid=lt,
                start_date=sd,
                end_date=ed,
                reason=reason,
                submitted_publicly=True,
            )
            if reliever:
                LeaveRequest.objects.filter(pk__in=[lr1.pk, lr2.pk]).update(covering_employee_id=reliever.pk)
                lr1.refresh_from_db()
                lr2.refresh_from_db()
            if request.FILES.get('medical_certificate'):
                lr1.medical_certificate = request.FILES['medical_certificate']
                lr1.medical_certificate_uploaded = True
                lr1.save()
            hr_notifications.notify_hr_public_leave_submitted(lr1)
            hr_notifications.notify_hr_public_leave_submitted(lr2)
            request.session['public_leave_refs'] = [
                str(lr1.reference_number or lr1.pk),
                str(lr2.reference_number or lr2.pk),
            ]
            return redirect('hr:public_leave_done')

        lr = LeaveRequest(
            employee=emp,
            leave_type=lt,
            start_date=sd,
            end_date=ed,
            reason=reason,
            status='pending_manager',
            submitted_publicly=True,
            covering_employee=reliever,
        )
        lr.save()
        if request.FILES.get('medical_certificate'):
            lr.medical_certificate = request.FILES['medical_certificate']
            lr.medical_certificate_uploaded = True
            lr.save()
        lr.refresh_from_db()
        sync_leave_balances_for_employee(emp.pk)
        hr_notifications.notify_hr_public_leave_submitted(lr)
        request.session['public_leave_refs'] = [str(lr.reference_number or lr.pk)]
        return redirect('hr:public_leave_done')


class PublicLeaveApplyDoneView(TemplateView):
    template_name = 'hr/public_leave_confirm.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_public_leave_branding_context())
        ctx['refs'] = self.request.session.pop('public_leave_refs', [])
        ctx['title'] = 'Request submitted'
        return ctx

