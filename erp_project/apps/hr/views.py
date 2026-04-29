"""HR Views"""
import json
import mimetypes
import os
from decimal import Decimal

from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy
from django.db import transaction
from django.db.models import Q, Sum
from django.core.exceptions import ValidationError
from datetime import date
from apps.settings_app.models import Company

from .models import Department, Designation, Employee, EmployeeAdvance, LeaveType, LeaveRequest, Payroll
from .forms import DepartmentForm, EmployeeBankDetailForm, EmployeeForm, LeaveRequestForm, PayrollForm
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker


def _employee_bank_form(request, employee):
    """Build bank detail form; employee is None on create, or an Employee with pk when editing."""
    inst = None
    if employee is not None and employee.pk:
        inst = getattr(employee, 'bank_detail', None)
    if request.method == 'POST':
        return EmployeeBankDetailForm(request.POST, instance=inst)
    return EmployeeBankDetailForm(instance=inst)


def leave_requests_queryset_for_user(user):
    """Leave rows the user may see: full HR access, or own employee only."""
    qs = LeaveRequest.objects.filter(is_active=True).select_related(
        'employee', 'employee__department', 'leave_type', 'approved_by', 'covering_employee'
    )
    if user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'view'):
        return qs
    try:
        emp = Employee.objects.get(user=user, is_active=True)
        return qs.filter(employee=emp)
    except Employee.DoesNotExist:
        return LeaveRequest.objects.none()


def _payroll_form_allowance_context(payroll=None):
    from apps.hr.models_extended import PayrollTemplate
    from apps.hr.payroll_allowances import TEMPLATE_ALLOWANCE_CHOICES

    rows = []
    if payroll and payroll.pk:
        for ln in payroll.allowance_lines.exclude(source='attendance').order_by('pk'):
            rows.append(
                {
                    'code': ln.code,
                    'description': ln.description,
                    'amount': str(ln.amount),
                }
            )
    if not rows:
        rows = [{'code': 'HOUSING', 'description': '', 'amount': ''}]
    return {
        'standard_allowance_choices': TEMPLATE_ALLOWANCE_CHOICES,
        'payroll_templates': PayrollTemplate.objects.filter(is_active=True).select_related('company').order_by(
            'name'
        ),
        'allowance_rows': rows,
    }


def _sync_employee_hr_profile(employee):
    """Keep EmployeeHRProfile.entity / GOSI category aligned with Employee.location & KSA compliance."""
    from apps.hr.models_extended import EmployeeHRProfile, KSACompliance

    prof, _ = EmployeeHRProfile.objects.get_or_create(employee=employee)
    prof.employment_entity = employee.location
    if employee.location == 'ksa':
        kc = KSACompliance.objects.filter(employee=employee).first()
        if kc:
            prof.gosi_employee_category = 'saudi' if kc.nationality == 'saudi' else 'non_saudi'
    prof.save()


class EmployeeListView(PermissionRequiredMixin, ListView):
    model = Employee
    template_name = 'hr/employee_list.html'
    context_object_name = 'employees'
    module_name = 'hr'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = Employee.objects.filter(is_active=True).select_related(
            'company', 'department', 'designation'
        )
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(employee_code__icontains=search))

        loc = self.request.GET.get('location')
        if loc in ('uae', 'ksa', 'other'):
            queryset = queryset.filter(location=loc)

        cid = self.request.GET.get('company')
        if cid and str(cid).isdigit():
            queryset = queryset.filter(company_id=int(cid))

        did = self.request.GET.get('department')
        if did and str(did).isdigit():
            queryset = queryset.filter(department_id=int(did))

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Employees'
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'edit')

        context['filter_companies'] = Company.objects.filter(is_active=True).order_by('name')
        context['filter_departments'] = Department.objects.filter(is_active=True).order_by('name')
        context['filter_location'] = self.request.GET.get('location') or ''
        context['filter_company'] = self.request.GET.get('company') or ''
        context['filter_department'] = self.request.GET.get('department') or ''

        # Calculate metrics
        all_employees = Employee.objects.filter(is_active=True)
        context['total_employees'] = all_employees.count()
        context['active_employees'] = all_employees.filter(status='active').count()
        context['total_departments'] = Department.objects.filter(is_active=True).count()

        return context


class EmployeeCreateView(CreatePermissionMixin, CreateView):
    model = Employee
    form_class = EmployeeForm
    template_name = 'hr/employee_form.html'
    success_url = reverse_lazy('hr:employee_list')
    module_name = 'hr'

    def _compliance_forms(self):
        from apps.hr.forms_extended import KSAComplianceForm, UAEComplianceForm

        return UAEComplianceForm(prefix='uae'), KSAComplianceForm(prefix='ksa')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Add Employee'
        # Pass departments and roles directly to template for manual rendering
        from .models import Department, Designation
        from apps.settings_app.models import Role

        context['departments'] = Department.objects.filter(is_active=True).order_by('name')

        # Fetch Roles from settings_app and sync to Designations
        roles = Role.objects.filter(is_active=True).order_by('name')
        # Sync roles to designations (create if they don't exist)
        default_dept = Department.objects.filter(is_active=True).first()
        for role in roles:
            if default_dept:
                Designation.objects.get_or_create(
                    name=role.name,
                    defaults={'department': default_dept}
                )

        # Now fetch designations (which includes synced roles)
        context['designations'] = Designation.objects.filter(is_active=True).order_by('name')
        # Also pass roles for reference
        context['roles'] = roles
        uae_form = kwargs.get('uae_form')
        ksa_form = kwargs.get('ksa_form')
        if uae_form is None or ksa_form is None:
            uae_form, ksa_form = self._compliance_forms()
        context['uae_form'] = uae_form
        context['ksa_form'] = ksa_form
        emp = getattr(self, 'object', None)
        employee_for_bank = emp if (emp and emp.pk) else None
        context['bank_form'] = kwargs.get('bank_form') or _employee_bank_form(
            self.request, employee_for_bank
        )
        return context

    def post(self, request, *args, **kwargs):
        # Required for ModelFormMixin/SingleObjectMixin.get_context_data on invalid POST.
        self.object = None
        form = self.get_form()
        if not form.is_valid():
            ctx = self.get_context_data(form=form)
            from apps.hr.forms_extended import KSAComplianceForm, UAEComplianceForm

            ctx['uae_form'] = UAEComplianceForm(request.POST, prefix='uae')
            ctx['ksa_form'] = KSAComplianceForm(request.POST, prefix='ksa')
            return self.render_to_response(ctx)

        from apps.hr.forms_extended import KSAComplianceForm, UAEComplianceForm
        from apps.hr.models_extended import KSACompliance, UAECompliance

        try:
            with transaction.atomic():
                employee = form.save()
                uc, _ = UAECompliance.objects.get_or_create(employee=employee)
                kc, _ = KSACompliance.objects.get_or_create(employee=employee)
                if employee.location == 'uae':
                    uf = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                    if not uf.is_valid():
                        transaction.set_rollback(True)
                        ctx = self.get_context_data(form=form)
                        ctx['uae_form'] = uf
                        ctx['ksa_form'] = KSAComplianceForm(prefix='ksa')
                        return self.render_to_response(ctx)
                    uf.save()
                elif employee.location == 'ksa':
                    kf = KSAComplianceForm(request.POST, instance=kc, prefix='ksa')
                    if not kf.is_valid():
                        transaction.set_rollback(True)
                        ctx = self.get_context_data(form=form)
                        ctx['uae_form'] = UAEComplianceForm(prefix='uae')
                        ctx['ksa_form'] = kf
                        return self.render_to_response(ctx)
                    kf.save()
                bf = EmployeeBankDetailForm(
                    request.POST, instance=getattr(employee, 'bank_detail', None)
                )
                if not bf.is_valid():
                    transaction.set_rollback(True)
                    ctx = self.get_context_data(form=form)
                    ctx['bank_form'] = bf
                    if employee.location == 'uae':
                        ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                        ctx['ksa_form'] = KSAComplianceForm(prefix='ksa')
                    elif employee.location == 'ksa':
                        ctx['uae_form'] = UAEComplianceForm(prefix='uae')
                        ctx['ksa_form'] = KSAComplianceForm(request.POST, instance=kc, prefix='ksa')
                    else:
                        ctx['uae_form'] = UAEComplianceForm(prefix='uae')
                        ctx['ksa_form'] = KSAComplianceForm(prefix='ksa')
                    return self.render_to_response(ctx)
                bf.save_for_employee(employee)
                _sync_employee_hr_profile(employee)
        except Exception:
            raise

        messages.success(request, 'Employee created.')
        return redirect(self.success_url)


class EmployeeUpdateView(UpdatePermissionMixin, UpdateView):
    model = Employee
    form_class = EmployeeForm
    template_name = 'hr/employee_form.html'
    success_url = reverse_lazy('hr:employee_list')
    module_name = 'hr'

    def _compliance_forms(self):
        from apps.hr.forms_extended import KSAComplianceForm, UAEComplianceForm
        from apps.hr.models_extended import KSACompliance, UAECompliance

        uc, _ = UAECompliance.objects.get_or_create(employee=self.object)
        kc, _ = KSACompliance.objects.get_or_create(employee=self.object)
        return UAEComplianceForm(instance=uc, prefix='uae'), KSAComplianceForm(instance=kc, prefix='ksa')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Employee: {self.object.full_name}'
        # Pass departments and roles directly to template for manual rendering
        from .models import Department, Designation
        from apps.settings_app.models import Role

        # Include current department even if inactive
        departments = Department.objects.filter(is_active=True)
        if self.object.department_id:
            departments = Department.objects.filter(
                Q(is_active=True) | Q(pk=self.object.department_id)
            )
        context['departments'] = departments.order_by('name')

        # Fetch Roles from settings_app and sync to Designations
        roles = Role.objects.filter(is_active=True).order_by('name')
        # Sync roles to designations (create if they don't exist)
        default_dept = Department.objects.filter(is_active=True).first()
        for role in roles:
            if default_dept:
                Designation.objects.get_or_create(
                    name=role.name,
                    defaults={'department': default_dept}
                )

        # Now fetch designations (which includes synced roles)
        # Include current designation even if inactive
        designations = Designation.objects.filter(is_active=True)
        if self.object.designation_id:
            designations = Designation.objects.filter(
                Q(is_active=True) | Q(pk=self.object.designation_id)
            )
        context['designations'] = designations.order_by('name')
        # Also pass roles for reference
        context['roles'] = roles
        uae_form = kwargs.get('uae_form')
        ksa_form = kwargs.get('ksa_form')
        if uae_form is None or ksa_form is None:
            uae_form, ksa_form = self._compliance_forms()
        context['uae_form'] = uae_form
        context['ksa_form'] = ksa_form
        context['bank_form'] = kwargs.get('bank_form') or _employee_bank_form(
            self.request, self.object
        )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        if not form.is_valid():
            ctx = self.get_context_data(form=form)
            from apps.hr.forms_extended import KSAComplianceForm, UAEComplianceForm
            from apps.hr.models_extended import KSACompliance, UAECompliance

            uc, _ = UAECompliance.objects.get_or_create(employee=self.object)
            kc, _ = KSACompliance.objects.get_or_create(employee=self.object)
            ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
            ctx['ksa_form'] = KSAComplianceForm(request.POST, instance=kc, prefix='ksa')
            return self.render_to_response(ctx)

        from apps.hr.forms_extended import KSAComplianceForm, UAEComplianceForm
        from apps.hr.models_extended import KSACompliance, UAECompliance

        try:
            with transaction.atomic():
                employee = form.save()
                uc, _ = UAECompliance.objects.get_or_create(employee=employee)
                kc, _ = KSACompliance.objects.get_or_create(employee=employee)
                if employee.location == 'uae':
                    uf = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                    if not uf.is_valid():
                        transaction.set_rollback(True)
                        ctx = self.get_context_data(form=form)
                        ctx['uae_form'] = uf
                        ctx['ksa_form'] = KSAComplianceForm(instance=kc, prefix='ksa')
                        return self.render_to_response(ctx)
                    uf.save()
                elif employee.location == 'ksa':
                    kf = KSAComplianceForm(request.POST, instance=kc, prefix='ksa')
                    if not kf.is_valid():
                        transaction.set_rollback(True)
                        ctx = self.get_context_data(form=form)
                        ctx['uae_form'] = UAEComplianceForm(instance=uc, prefix='uae')
                        ctx['ksa_form'] = kf
                        return self.render_to_response(ctx)
                    kf.save()
                bf = EmployeeBankDetailForm(
                    request.POST, instance=getattr(employee, 'bank_detail', None)
                )
                if not bf.is_valid():
                    transaction.set_rollback(True)
                    ctx = self.get_context_data(form=form)
                    ctx['bank_form'] = bf
                    if employee.location == 'uae':
                        ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                        ctx['ksa_form'] = KSAComplianceForm(instance=kc, prefix='ksa')
                    elif employee.location == 'ksa':
                        ctx['uae_form'] = UAEComplianceForm(instance=uc, prefix='uae')
                        ctx['ksa_form'] = KSAComplianceForm(request.POST, instance=kc, prefix='ksa')
                    else:
                        ctx['uae_form'] = UAEComplianceForm(instance=uc, prefix='uae')
                        ctx['ksa_form'] = KSAComplianceForm(instance=kc, prefix='ksa')
                    return self.render_to_response(ctx)
                bf.save_for_employee(employee)
                _sync_employee_hr_profile(employee)
        except Exception:
            raise

        messages.success(request, 'Employee updated.')
        return redirect(self.success_url)


class EmployeeDetailView(PermissionRequiredMixin, DetailView):
    model = Employee
    template_name = 'hr/employee_detail.html'
    context_object_name = 'employee'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        return Employee.objects.select_related(
            'company', 'department', 'designation', 'bank_detail'
        )

    def get_context_data(self, **kwargs):
        from apps.hr.models_extended import KSACompliance, UAECompliance

        context = super().get_context_data(**kwargs)
        context['title'] = f'Employee: {self.object.full_name}'
        context['leave_requests'] = self.object.leave_requests.all()[:10]
        context['payrolls'] = self.object.payrolls.all()[:12]

        from datetime import date as date_cls

        from apps.hr.models import LeaveBalance

        context['leave_balances'] = (
            LeaveBalance.objects.filter(employee=self.object, year=date_cls.today().year)
            .select_related('leave_type')
            .order_by('leave_type__name')
        )

        uc, _ = UAECompliance.objects.get_or_create(employee=self.object)
        kc, _ = KSACompliance.objects.get_or_create(employee=self.object)
        context['uae_compliance'] = uc
        context['ksa_compliance'] = kc
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'edit'
        )
        return context


class DepartmentListView(PermissionRequiredMixin, ListView):
    model = Department
    template_name = 'hr/department_list.html'
    context_object_name = 'departments'
    module_name = 'hr'
    permission_type = 'view'
    
    def get_queryset(self):
        return Department.objects.filter(is_active=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Departments'
        context['form'] = DepartmentForm()
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'create')
        return context
    
    def post(self, request, *args, **kwargs):
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Department created.')
        return redirect('hr:department_list')


class LeaveRequestListView(PermissionRequiredMixin, ListView):
    model = LeaveRequest
    template_name = 'hr/leave_list.html'
    context_object_name = 'leave_requests'
    module_name = 'hr'
    permission_type = 'view'
    
    def get_queryset(self):
        return leave_requests_queryset_for_user(self.request.user).order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Leave Requests'
        context['can_approve'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'approve')
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'edit')
        # Check if user has employee profile (for self-application)
        try:
            context['has_employee_profile'] = Employee.objects.filter(user=self.request.user, is_active=True).exists()
        except:
            context['has_employee_profile'] = False
        
        # Calculate metrics
        all_leave_requests = LeaveRequest.objects.filter(is_active=True)
        context['total_leave_requests'] = all_leave_requests.count()
        context['pending_leave_requests'] = all_leave_requests.filter(
            status__in=['pending_manager', 'pending_hr']
        ).count()
        context['approved_leave_requests'] = all_leave_requests.filter(status='approved').count()
        
        return context


class LeaveRequestCreateView(CreatePermissionMixin, CreateView):
    model = LeaveRequest
    form_class = LeaveRequestForm
    template_name = 'hr/leave_form.html'
    success_url = reverse_lazy('hr:leave_list')
    module_name = 'hr'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['is_admin'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'create')
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        is_admin = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'create')
        context['title'] = 'Apply for Leave' if not is_admin else 'Add Leave Request'
        context['is_admin'] = is_admin
        # Get employee name if self-applying
        if not is_admin:
            try:
                employee = Employee.objects.get(user=self.request.user, is_active=True)
                context['employee_name'] = employee.full_name
            except Employee.DoesNotExist:
                pass
        return context
    
    def form_valid(self, form):
        is_admin = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'create')
        if not is_admin:
            try:
                employee = Employee.objects.get(user=self.request.user, is_active=True)
                form.instance.employee = employee
            except Employee.DoesNotExist:
                messages.error(self.request, 'Employee profile not found. Please contact HR.')
                return self.form_invalid(form)

        from apps.hr.leave_balance_service import sync_leave_balances_for_employee
        from apps.hr.leave_context_service import create_split_leave_pair
        from apps.hr import hr_notifications

        if form.cleaned_data.get('overflow_action') == 'split':
            reliever = form.cleaned_data.get('covering_employee')
            lr1, lr2 = create_split_leave_pair(
                employee=form.cleaned_data['employee'],
                leave_type_paid=form.cleaned_data['leave_type'],
                start_date=form.cleaned_data['start_date'],
                end_date=form.cleaned_data['end_date'],
                reason=form.cleaned_data.get('reason') or '',
                submitted_publicly=False,
            )
            if reliever:
                LeaveRequest.objects.filter(pk__in=[lr1.pk, lr2.pk]).update(covering_employee_id=reliever.pk)
            medical = self.request.FILES.get('medical_certificate')
            if medical:
                lr1.medical_certificate = medical
                lr1.medical_certificate_uploaded = True
                lr1.save(update_fields=['medical_certificate', 'medical_certificate_uploaded', 'updated_at'])
            hr_notifications.notify_department_manager(lr1)
            hr_notifications.notify_department_manager(lr2)
            messages.success(
                self.request,
                f'Split leave submitted: {lr1.reference_number or lr1.pk}, {lr2.reference_number or lr2.pk}',
            )
            self.object = lr2
            return redirect(self.get_success_url())

        resp = super().form_valid(form)
        sync_leave_balances_for_employee(form.instance.employee_id)
        hr_notifications.notify_department_manager(self.object)
        messages.success(self.request, f'Leave request submitted. Reference: {self.object.reference_number or self.object.pk}')
        return resp


class LeaveRequestUpdateView(UpdatePermissionMixin, UpdateView):
    model = LeaveRequest
    form_class = LeaveRequestForm
    template_name = 'hr/leave_form.html'
    success_url = reverse_lazy('hr:leave_list')
    module_name = 'hr'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['is_admin'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'edit')
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        is_admin = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'edit')
        context['title'] = 'Edit Leave Request'
        context['is_admin'] = is_admin
        if self.object and self.object.employee_id:
            context['employee_name'] = self.object.employee.full_name
        return context
    
    def form_valid(self, form):
        resp = super().form_valid(form)
        from apps.hr.leave_balance_service import sync_leave_balances_for_employee

        sync_leave_balances_for_employee(form.instance.employee_id)
        messages.success(self.request, 'Leave request updated successfully.')
        return resp


class LeaveRequestDetailView(PermissionRequiredMixin, DetailView):
    """View leave request details, reason, and uploaded attachment (public apply)."""

    model = LeaveRequest
    template_name = 'hr/leave_detail.html'
    context_object_name = 'leave'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        return leave_requests_queryset_for_user(self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        leave = self.object
        ctx['title'] = f'Leave — {leave.employee.full_name}'
        name = (leave.medical_certificate.name if leave.medical_certificate else '') or ''
        base = os.path.basename(name)
        mime, _ = mimetypes.guess_type(base)
        ctx['attachment_mime'] = mime or ''
        ctx['attachment_is_image'] = bool(mime and mime.startswith('image/'))
        ctx['attachment_is_pdf'] = mime == 'application/pdf'
        ctx['has_attachment'] = bool(leave.medical_certificate)
        return ctx


@login_required
def leave_attachment(request, pk):
    """Serve medical certificate with same access rules as leave detail; supports ?preview=1 for inline."""
    leave = get_object_or_404(leave_requests_queryset_for_user(request.user), pk=pk)
    f = leave.medical_certificate
    if not f:
        raise Http404('No attachment for this leave request.')
    filename = os.path.basename(f.name)
    mime, _ = mimetypes.guess_type(filename)
    try:
        fh = f.open('rb')
    except FileNotFoundError:
        raise Http404('Attachment file is missing on disk.') from None
    resp = FileResponse(fh, content_type=mime or 'application/octet-stream')
    disp = 'inline' if request.GET.get('preview') == '1' else 'attachment'
    resp['Content-Disposition'] = f'{disp}; filename="{filename}"'
    return resp


@login_required
@require_POST
def leave_approve(request, pk):
    leave = get_object_or_404(leave_requests_queryset_for_user(request.user), pk=pk)
    from apps.hr.leave_workflow import approve_leave_request

    ok, msg = approve_leave_request(request, leave)
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect('hr:leave_list')


@login_required
@require_POST
def leave_reject(request, pk):
    leave = get_object_or_404(leave_requests_queryset_for_user(request.user), pk=pk)
    from apps.hr.leave_workflow import reject_leave_request

    reason = request.POST.get('rejection_reason', '').strip()
    ok, msg = reject_leave_request(request, leave, reason=reason)
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect('hr:leave_list')


class PayrollListView(PermissionRequiredMixin, ListView):
    model = Payroll
    template_name = 'hr/payroll_list.html'
    context_object_name = 'payrolls'
    module_name = 'hr'
    permission_type = 'view'
    
    def get_queryset(self):
        qs = Payroll.objects.filter(is_active=True).select_related('employee', 'employee__company', 'company')
        cid = self.request.GET.get('company')
        if cid and str(cid).isdigit():
            co = Company.objects.filter(pk=int(cid), is_active=True).first()
            if co:
                qs = qs.filter(Q(company_id=co.pk) | Q(company__isnull=True, employee__company_id=co.pk))
        return qs.order_by('-month', 'employee__employee_code')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Payroll'
        queryset = self.get_queryset()
        context['total_payroll'] = queryset.aggregate(Sum('net_salary'))['net_salary__sum'] or 0
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'edit')
        
        # Calculate metrics
        all_payrolls = Payroll.objects.filter(is_active=True)
        context['total_payroll_records'] = all_payrolls.count()
        context['paid_payrolls'] = all_payrolls.filter(status='paid').count()
        context['processed_payrolls'] = all_payrolls.filter(status='processed').count()
        context['filter_companies'] = Company.objects.filter(is_active=True).order_by('name')
        context['filter_company'] = self.request.GET.get('company') or ''
        if context.get('can_edit'):
            from apps.finance.models import BankAccount

            context['payroll_bank_accounts'] = BankAccount.objects.filter(is_active=True).order_by(
                'name', 'pk'
            )

        ac = Company.objects.filter(is_active=True)
        context['has_uae_company'] = ac.filter(country='uae').exists()
        context['has_ksa_company'] = ac.filter(country='ksa').exists()
        context['wps_export_companies'] = ac.filter(country='uae').order_by('name')
        context['gosi_export_companies'] = ac.filter(country='ksa').order_by('name')
        td = date.today()
        context['export_years'] = list(range(td.year - 2, td.year + 3))
        context['export_months'] = list(range(1, 13))
        context['default_export_month'] = td.month
        context['default_export_year'] = td.year

        if self.request.GET.get('wps_preview') == '1':
            from apps.hr.wps_service import collect_wps_payload

            wc = self.request.GET.get('wps_company')
            wm = self.request.GET.get('wps_month')
            wy = self.request.GET.get('wps_year')
            if wc and wm and wy and str(wc).isdigit() and str(wm).isdigit() and str(wy).isdigit():
                co = Company.objects.filter(pk=int(wc), is_active=True, country='uae').first()
                if co:
                    mf = date(int(wy), int(wm), 1)
                    context['wps_export_preview'] = collect_wps_payload(co, mf)
                    context['wps_export_preview_company'] = co
                    context['wps_export_preview_month'] = int(wm)
                    context['wps_export_preview_year'] = int(wy)

        if self.request.GET.get('gosi_preview') == '1':
            from apps.hr.gosi_export_service import collect_gosi_payload

            gc = self.request.GET.get('gosi_company')
            gm = self.request.GET.get('gosi_month')
            gy = self.request.GET.get('gosi_year')
            if gc and gm and gy and str(gc).isdigit() and str(gm).isdigit() and str(gy).isdigit():
                co = Company.objects.filter(pk=int(gc), is_active=True, country='ksa').first()
                if co:
                    mf = date(int(gy), int(gm), 1)
                    context['gosi_export_preview'] = collect_gosi_payload(co, mf, sync_records=False)
                    context['gosi_export_preview_company'] = co
                    context['gosi_export_preview_month'] = int(gm)
                    context['gosi_export_preview_year'] = int(gy)

        return context


class PayrollDetailView(PermissionRequiredMixin, DetailView):
    model = Payroll
    template_name = 'hr/payroll_detail.html'
    context_object_name = 'payroll'
    module_name = 'hr'
    permission_type = 'view'
    
    def get_queryset(self):
        return Payroll.objects.filter(is_active=True).select_related(
            'employee',
            'employee__company',
            'company',
            'journal_entry',
            'payment_journal_entry',
            'paid_from_bank',
        ).prefetch_related(
            'deduction_lines',
            'employer_contributions',
            'allowance_lines',
        )
    
    def get_context_data(self, **kwargs):
        from datetime import date
        from decimal import Decimal

        from apps.core.audit import get_entity_audit_history
        from apps.hr.models_extended import AttendanceSummary, GratuityRecord

        context = super().get_context_data(**kwargs)
        context['title'] = f'Payroll - {self.object.employee.full_name}'
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'hr', 'edit')

        mf = date(self.object.month.year, self.object.month.month, 1)
        summ = AttendanceSummary.objects.filter(employee=self.object.employee, month=mf).first()
        context['attendance_summary'] = summ
        context['attendance_finalized'] = bool(summ and summ.is_finalized)
        context['attendance_not_finalized_warning'] = self.object.status == 'draft' and (
            summ is None or not summ.is_finalized
        )

        att_amt = Decimal('0')
        if summ and summ.is_finalized:
            from apps.hr.attendance_utils import working_days_in_calendar_month
            from apps.hr.models_extended import AttendanceSettings

            att_set = AttendanceSettings.objects.get_or_create(pk=1)[0]
            wd = max(
                working_days_in_calendar_month(self.object.month.year, self.object.month.month),
                int(att_set.working_days_in_month),
                1,
            )
            per_day = (self.object.basic_salary / Decimal(wd)).quantize(Decimal('0.01'))
            att_amt += (per_day * (summ.absent_deduction_days or Decimal('0'))).quantize(Decimal('0.01'))
            att_amt += (att_set.late_deduction_amount * Decimal(summ.total_late)).quantize(Decimal('0.01'))
        context['attendance_deductions_approx_aed'] = att_amt
        context['deduction_lines'] = list(self.object.deduction_lines.all())
        context['allowance_lines'] = list(self.object.allowance_lines.all().order_by('pk'))
        context['employer_contributions'] = list(self.object.employer_contributions.all())
        context['gratuity_snapshot'] = GratuityRecord.objects.filter(payroll=self.object).first()

        context['employee_active_advances'] = (
            EmployeeAdvance.objects.filter(
                employee=self.object.employee,
                is_active=True,
                status=EmployeeAdvance.STATUS_ACTIVE,
            )
            .order_by('-date_issued', '-pk')
        )

        viewer_emp = Employee.objects.filter(user=self.request.user, is_active=True).first()
        context['can_payslip_pdf'] = (
            self.request.user.is_superuser
            or PermissionChecker.has_permission(self.request.user, 'hr', 'view')
            or (viewer_emp is not None and viewer_emp.pk == self.object.employee_id)
        )

        # Audit History
        context['audit_history'] = get_entity_audit_history('Payroll', self.object.pk)

        return context


class PayrollCreateView(CreatePermissionMixin, CreateView):
    model = Payroll
    form_class = PayrollForm
    template_name = 'hr/payroll_form.html'
    success_url = reverse_lazy('hr:payroll_list')
    module_name = 'hr'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Add Payroll'
        context.update(_payroll_form_allowance_context())
        context['employee_company_map'] = {
            str(e.pk): (str(e.company_id) if e.company_id else '')
            for e in Employee.objects.filter(is_active=True).only('pk', 'company_id')
        }
        context['employee_company_json'] = json.dumps(context['employee_company_map'])
        return context
    
    def form_valid(self, form):
        from apps.hr.payroll_allowances import replace_allowance_lines_from_post, total_allowances_amount

        payroll = form.save(commit=False)
        payroll.status = payroll.status or 'draft'
        if payroll.employee_id and not payroll.company_id:
            ecid = Employee.objects.filter(pk=payroll.employee_id).values_list('company_id', flat=True).first()
            if ecid:
                payroll.company_id = ecid
        payroll.save()
        replace_allowance_lines_from_post(payroll, self.request.POST)
        payroll.allowances = total_allowances_amount(payroll)
        ded = payroll.deductions or Decimal('0')
        payroll.net_salary = (payroll.basic_salary or Decimal('0')) + payroll.allowances - ded
        payroll.save(update_fields=['allowances', 'net_salary', 'company'])
        messages.success(self.request, f'Payroll for {payroll.employee.full_name} created successfully.')
        return redirect(self.success_url)


class PayrollUpdateView(UpdatePermissionMixin, UpdateView):
    model = Payroll
    form_class = PayrollForm
    template_name = 'hr/payroll_form.html'
    success_url = reverse_lazy('hr:payroll_list')
    module_name = 'hr'

    def get_queryset(self):
        return Payroll.objects.filter(is_active=True, status='draft')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Payroll: {self.object.employee.full_name}'
        context.update(_payroll_form_allowance_context(self.object))
        context['employee_company_map'] = {
            str(e.pk): (str(e.company_id) if e.company_id else '')
            for e in Employee.objects.filter(is_active=True).only('pk', 'company_id')
        }
        context['employee_company_json'] = json.dumps(context['employee_company_map'])
        return context
    
    def form_valid(self, form):
        from apps.hr.payroll_allowances import replace_allowance_lines_from_post, total_allowances_amount

        payroll = form.save(commit=False)
        if payroll.employee_id and not payroll.company_id:
            ecid = Employee.objects.filter(pk=payroll.employee_id).values_list('company_id', flat=True).first()
            if ecid:
                payroll.company_id = ecid
        payroll.save()
        replace_allowance_lines_from_post(payroll, self.request.POST)
        payroll.allowances = total_allowances_amount(payroll)
        ded = payroll.deductions or Decimal('0')
        payroll.net_salary = (payroll.basic_salary or Decimal('0')) + payroll.allowances - ded
        payroll.save(update_fields=['allowances', 'net_salary', 'company'])
        messages.success(self.request, f'Payroll for {payroll.employee.full_name} updated successfully.')
        return redirect(self.success_url)



# ============ PAYROLL ACCOUNTING VIEWS ============

@login_required
def payroll_process(request, pk):
    """
    Process payroll and post to accounting.
    SAP/Oracle Standard: Dr Salary Expense, Cr Salary Payable
    """
    from apps.core.audit import audit_payroll_process
    
    payroll = get_object_or_404(Payroll, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:payroll_list')
    
    if payroll.status != 'draft':
        messages.error(request, 'Only draft payrolls can be processed.')
        return redirect('hr:payroll_list')
    
    try:
        from apps.hr.payroll_processing import apply_payroll_computations

        apply_payroll_computations(payroll)
        payroll.refresh_from_db()

        journal = payroll.post_to_accounting(user=request.user)
        # Audit log with IP address
        audit_payroll_process(payroll, request.user, request=request)
        messages.success(request, f'Payroll for {payroll.employee.full_name} processed and posted. Journal: {journal.entry_number}')
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f'Error processing payroll: {e}')
    
    return redirect('hr:payroll_list')


@login_required
def payroll_pay(request, pk):
    """
    Pay processed payroll.
    SAP/Oracle Standard: Dr Salary Payable, Cr Bank
    """
    from apps.finance.models import BankAccount
    from datetime import date
    
    payroll = get_object_or_404(Payroll, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('hr:payroll_list')
    
    if payroll.status != 'processed':
        messages.error(request, 'Only processed payrolls can be paid.')
        return redirect('hr:payroll_list')
    
    if request.method == 'POST':
        bank_account_id = request.POST.get('bank_account')
        payment_date = request.POST.get('payment_date')
        reference = request.POST.get('reference', '')
        
        bank_account = BankAccount.objects.filter(pk=bank_account_id, is_active=True).first()
        if not bank_account:
            messages.error(request, 'Invalid bank account.')
            return redirect('hr:payroll_list')
        
        from datetime import datetime
        try:
            if payment_date:
                payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
            else:
                payment_date = date.today()
        except ValueError:
            payment_date = date.today()
        
        try:
            journal = payroll.post_payment_journal(
                bank_account=bank_account,
                payment_date=payment_date,
                reference=reference,
                user=request.user
            )
            payroll.refresh_from_db()
            from apps.hr import hr_notifications

            hr_notifications.on_payroll_paid(payroll, request=request)
            messages.success(request, f'Payroll payment for {payroll.employee.full_name} processed. Journal: {journal.entry_number}')
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error processing payment: {e}')
        
        return redirect('hr:payroll_list')
    
    # GET - Show payment form
    bank_accounts = BankAccount.objects.filter(is_active=True)
    context = {
        'title': f'Pay Salary - {payroll.employee.full_name}',
        'payroll': payroll,
        'bank_accounts': bank_accounts,
        'today': date.today().strftime('%Y-%m-%d'),
    }
    return render(request, 'hr/payroll_pay.html', context)
