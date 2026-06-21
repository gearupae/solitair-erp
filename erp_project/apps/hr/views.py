"""HR Views"""
import json
import mimetypes
import os
from decimal import Decimal

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse, reverse_lazy
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.core.exceptions import ValidationError
from datetime import date
from apps.settings_app.models import Company

from .models import Department, Designation, Employee, EmployeeAdvance, LeaveType, LeaveRequest, Payroll
from .forms import DepartmentForm, DesignationForm, EmployeeBankDetailForm, EmployeeForm, LeaveRequestForm, PayrollForm
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


def _provision_employee_login_if_needed(request, form, employee):
    """When the form includes ERP role and employee has no login yet, create User + roles."""
    if 'portal_role' not in form.fields:
        return
    if employee.user_id:
        return
    _pr = form.cleaned_data.get('portal_role')
    roles = [_pr] if _pr else []
    if not roles and employee.designation_id:
        from .designation_utils import resolve_role_for_designation

        mapped = resolve_role_for_designation(employee.designation)
        if mapped:
            roles = [mapped]
    from django.conf import settings as dj_settings

    from .user_provisioning import provision_user_for_employee

    try:
        user, temp_pw = provision_user_for_employee(employee, roles)
    except ValueError as e:
        messages.error(request, str(e))
        return
    if temp_pw:
        default_pw = getattr(dj_settings, 'HR_EMPLOYEE_DEFAULT_PASSWORD', '')
        messages.warning(
            request,
            f'System login created — username: {user.username}. '
            f'Default password: {default_pw} (override HR_EMPLOYEE_DEFAULT_PASSWORD in .env; '
            'change password under Settings → Users).',
        )


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
    paginate_by = 25

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

        return queryset.order_by('-created_at', '-pk')

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
        from apps.hr.forms_extended import UAEComplianceForm

        return UAEComplianceForm(prefix='uae')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Add Employee'
        # Pass departments and roles directly to template for manual rendering
        from .models import Department, Designation
        from apps.settings_app.models import Role

        context['departments'] = Department.objects.filter(is_active=True).order_by('name')

        # Fetch Roles from settings_app and sync to Designations
        from .designation_utils import ensure_role_designations, designations_queryset, designation_option_rows

        ensure_role_designations()
        roles = Role.objects.filter(is_active=True).order_by('name')

        dept_id = None
        form = kwargs.get('form')
        if form is not None and getattr(form, 'data', None) and form.data.get('department'):
            dept_id = form.data.get('department') or None

        include_desig = None
        if getattr(self, 'object', None) and self.object.designation_id:
            include_desig = self.object.designation_id
            if not dept_id and self.object.department_id:
                dept_id = self.object.department_id

        context['designations'] = designations_queryset(None, include_desig)
        context['designation_options'] = designation_option_rows(context['designations'])
        # Also pass roles for reference
        context['roles'] = roles
        uae_form = kwargs.get('uae_form')
        if uae_form is None:
            uae_form = self._compliance_forms()
        context['uae_form'] = uae_form
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
            from apps.hr.forms_extended import UAEComplianceForm

            ctx['uae_form'] = UAEComplianceForm(request.POST, prefix='uae')
            return self.render_to_response(ctx)

        from apps.hr.forms_extended import UAEComplianceForm
        from apps.hr.models_extended import UAECompliance

        try:
            with transaction.atomic():
                employee = form.save()
                _provision_employee_login_if_needed(request, form, employee)
                uc, _ = UAECompliance.objects.get_or_create(employee=employee)
                uf = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                if not uf.is_valid():
                    transaction.set_rollback(True)
                    ctx = self.get_context_data(form=form)
                    ctx['uae_form'] = uf
                    return self.render_to_response(ctx)
                uf.save()
                bf = EmployeeBankDetailForm(
                    request.POST, instance=getattr(employee, 'bank_detail', None)
                )
                if not bf.is_valid():
                    transaction.set_rollback(True)
                    ctx = self.get_context_data(form=form)
                    ctx['bank_form'] = bf
                    ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
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
    module_name = 'hr'

    def get_success_url(self):
        return reverse('hr:employee_detail', kwargs={'pk': self.object.pk})

    def _compliance_forms(self):
        from apps.hr.forms_extended import UAEComplianceForm
        from apps.hr.models_extended import UAECompliance

        uc, _ = UAECompliance.objects.get_or_create(employee=self.object)
        return UAEComplianceForm(instance=uc, prefix='uae')

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
        from .designation_utils import ensure_role_designations, designations_queryset, designation_option_rows

        ensure_role_designations()
        roles = Role.objects.filter(is_active=True).order_by('name')

        dept_id = None
        form = kwargs.get('form')
        if form is not None and getattr(form, 'data', None) and form.data.get('department'):
            dept_id = form.data.get('department') or None
        elif self.object.department_id:
            dept_id = self.object.department_id

        include_desig = self.object.designation_id if self.object.designation_id else None
        context['designations'] = designations_queryset(None, include_desig)
        context['designation_options'] = designation_option_rows(context['designations'])
        # Also pass roles for reference
        context['roles'] = roles
        uae_form = kwargs.get('uae_form')
        if uae_form is None:
            uae_form = self._compliance_forms()
        context['uae_form'] = uae_form
        context['bank_form'] = kwargs.get('bank_form') or _employee_bank_form(
            self.request, self.object
        )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        if not form.is_valid():
            ctx = self.get_context_data(form=form)
            from apps.hr.forms_extended import UAEComplianceForm
            from apps.hr.models_extended import UAECompliance

            uc, _ = UAECompliance.objects.get_or_create(employee=self.object)
            ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
            return self.render_to_response(ctx)

        from apps.hr.forms_extended import UAEComplianceForm
        from apps.hr.models_extended import UAECompliance

        try:
            with transaction.atomic():
                employee = form.save()
                _provision_employee_login_if_needed(request, form, employee)
                uc, _ = UAECompliance.objects.get_or_create(employee=employee)
                uf = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                if not uf.is_valid():
                    transaction.set_rollback(True)
                    ctx = self.get_context_data(form=form)
                    ctx['uae_form'] = uf
                    return self.render_to_response(ctx)
                uf.save()
                bf = EmployeeBankDetailForm(
                    request.POST, instance=getattr(employee, 'bank_detail', None)
                )
                if not bf.is_valid():
                    transaction.set_rollback(True)
                    ctx = self.get_context_data(form=form)
                    ctx['bank_form'] = bf
                    ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                    return self.render_to_response(ctx)
                bf.save_for_employee(employee)
                _sync_employee_hr_profile(employee)
        except Exception:
            raise

        messages.success(request, 'Employee updated.')
        self.object = employee
        return redirect(self.get_success_url())


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
        from datetime import date as date_cls

        from apps.hr.models import LeaveBalance
        from apps.hr.models_extended import UAECompliance
        from apps.hr.uae_gratuity import (
            TERMINATION_RESIGNED,
            TERMINATION_TERMINATED,
            calculate_uae_gratuity,
            employee_gratuity_eligible,
        )

        context = super().get_context_data(**kwargs)
        context['title'] = f'Employee: {self.object.full_name}'
        context['leave_requests'] = self.object.leave_requests.all()[:10]
        context['payrolls'] = self.object.payrolls.all()[:12]

        context['leave_balances'] = (
            LeaveBalance.objects.filter(employee=self.object, year=date_cls.today().year)
            .select_related('leave_type')
            .order_by('leave_type__name')
        )

        uc, _ = UAECompliance.objects.get_or_create(employee=self.object)
        context['uae_compliance'] = uc
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'edit'
        )

        context['gratuity_eligible'] = employee_gratuity_eligible(self.object)
        today = date_cls.today()
        if context['gratuity_eligible']:
            context['gratuity_resigned'] = calculate_uae_gratuity(
                self.object, as_of_date=today, termination_type=TERMINATION_RESIGNED
            )
            context['gratuity_terminated'] = calculate_uae_gratuity(
                self.object, as_of_date=today, termination_type=TERMINATION_TERMINATED
            )
        elif getattr(self.object, 'is_uae_national', False):
            context['gratuity_national_message'] = (
                'UAE National — covered under GPSSA pension scheme. No gratuity applies.'
            )
        else:
            context['gratuity_national_message'] = ''

        from apps.inventory.utils import get_openai_api_key
        from .employee_evaluate_ai import get_cached_employee_evaluation

        context['openai_configured'] = bool(get_openai_api_key())
        context['employee_ai_evaluation'] = get_cached_employee_evaluation(self.object)
        context['employee_ai_evaluate_url'] = reverse(
            'hr:employee_ai_evaluate', args=[self.object.pk]
        )

        return context


@login_required
def employee_ai_evaluate(request, pk):
    """AJAX: AI review of employee HR/UAE compliance."""
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    employee = get_object_or_404(Employee, pk=pk, is_active=True)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'view')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    from .employee_evaluate_ai import evaluate_employee

    force = request.POST.get('force') == '1'
    try:
        result = evaluate_employee(employee, force_refresh=force)
        return JsonResponse({'ok': True, 'evaluation': result})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


@login_required
def employee_gratuity_calculator(request, pk):
    """JSON API — hypothetical UAE EOSG (no DB write)."""
    from datetime import datetime

    from apps.hr.uae_gratuity import calculate_uae_gratuity, employee_gratuity_eligible

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'view')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    employee = get_object_or_404(Employee, pk=pk, is_active=True)
    if not employee_gratuity_eligible(employee):
        msg = 'Gratuity does not apply for this employee.'
        if getattr(employee, 'is_uae_national', False):
            msg = 'UAE National — covered under GPSSA pension scheme. No gratuity applies.'
        return JsonResponse({'ok': False, 'error': msg})

    raw_date = (request.GET.get('termination_date') or '').strip()
    term_type = (request.GET.get('termination_type') or 'terminated').strip().lower()
    as_of = date.today()
    if raw_date:
        try:
            as_of = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'ok': False, 'error': 'Invalid termination date.'})

    result = calculate_uae_gratuity(employee, as_of_date=as_of, termination_type=term_type)
    return JsonResponse({
        'ok': True,
        'years_of_service': str(result['years_of_service']),
        'years_of_service_display': result['years_of_service_display'],
        'daily_rate': f'{result["daily_rate"]:.2f}',
        'raw_gratuity': f'{result["raw_gratuity"]:.2f}',
        'adjustment_factor': str(result['adjustment_factor']),
        'final_gratuity': f'{result["final_gratuity"]:.2f}',
        'cap_applied': result['cap_applied'],
    })


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


class DesignationListView(PermissionRequiredMixin, ListView):
    model = Designation
    template_name = 'hr/designation_list.html'
    context_object_name = 'designations'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        from apps.settings_app.models import Role

        self._role_names = {
            n.lower()
            for n in Role.objects.filter(is_active=True).values_list('name', flat=True)
        }
        return (
            Designation.objects.filter(is_active=True)
            .select_related('department')
            .annotate(employee_count=Count('employees', filter=Q(employees__is_active=True)))
            .order_by('department__name', 'name')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Designations'
        context['form'] = DesignationForm()
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'hr', 'create'
        )
        role_names = getattr(self, '_role_names', set())
        for desig in context['designations']:
            desig.has_matching_role = (desig.name or '').lower() in role_names
        return context

    def post(self, request, *args, **kwargs):
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'hr', 'create')):
            messages.error(request, 'Permission denied.')
            return redirect('hr:designation_list')
        form = DesignationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Designation “{form.instance.name}” created. Matching ERP role is ready under Settings → Roles.')
        else:
            messages.error(request, 'Could not save designation. Check department and name.')
        return redirect('hr:designation_list')


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
        from apps.hr.leave_approval_rules import annotate_leave_approval_actions

        annotate_leave_approval_actions(self.request.user, context['leave_requests'])
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
        from apps.hr.leave_approval_rules import user_can_act_on_leave_request

        ctx['can_act_on_leave'] = user_can_act_on_leave_request(self.request.user, leave)
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

        from apps.hr.leave_payroll_deductions import (
            paid_full_leave_working_days_in_month,
            unpaid_leave_working_days_in_month_strict,
        )
        from apps.hr.payroll_processing import get_payroll_settings
        from apps.hr.salary_payroll_utils import (
            structural_allowances_total,
            total_salary_for_daily_rate,
            working_days_divisor_from_settings,
        )
        from apps.hr.models_extended import PayrollDeductionLine

        emp = self.object.employee
        ps = get_payroll_settings()
        wd_div = working_days_divisor_from_settings(ps)
        struct_allow = structural_allowances_total(self.object)
        gross_struct = self.object.gross_salary or (self.object.basic_salary + struct_allow)
        daily_rate = (gross_struct / Decimal(wd_div)).quantize(Decimal('0.01')) if wd_div else Decimal('0')

        context['salary_template_name'] = emp.salary_template.name if getattr(emp, 'salary_template_id', None) else None
        context['structural_allowances_total'] = struct_allow
        context['gross_salary_structural'] = gross_struct
        context['payroll_working_days_divisor'] = wd_div
        context['daily_rate_for_leave'] = daily_rate
        context['paid_leave_days_month'] = paid_full_leave_working_days_in_month(emp, mf)
        context['unpaid_leave_days_month'] = unpaid_leave_working_days_in_month_strict(emp, mf)
        context['absent_days_month'] = int(summ.total_absent or 0) if summ else 0

        dlines = list(self.object.deduction_lines.all())

        def _ded_by_code(*codes):
            cset = {c.lower() for c in codes}
            return sum(
                (ln.amount for ln in dlines if (ln.code or '').lower() in cset),
                Decimal('0'),
            )

        context['unpaid_leave_deducted_aed'] = _ded_by_code(PayrollDeductionLine.CODE_UNPAID_LEAVE)
        context['absent_deducted_aed'] = _ded_by_code(PayrollDeductionLine.CODE_ABSENT)
        context['deduction_lines'] = dlines

        att_amt = Decimal('0')
        if summ and summ.is_finalized:
            from apps.hr.models_extended import AttendanceSettings

            att_set = AttendanceSettings.objects.get_or_create(pk=1)[0]
            pkg = total_salary_for_daily_rate(self.object)
            per_day = (pkg / Decimal(wd_div)).quantize(Decimal('0.01')) if wd_div else Decimal('0')
            att_amt += (per_day * Decimal(int(summ.total_absent or 0))).quantize(Decimal('0.01'))
            att_amt += (att_set.late_deduction_amount * Decimal(summ.total_late)).quantize(Decimal('0.01'))
        context['attendance_deductions_approx_aed'] = att_amt
        context['allowance_lines'] = list(self.object.allowance_lines.all().order_by('pk'))
        context['employer_contributions'] = list(self.object.employer_contributions.all())
        context['gratuity_snapshot'] = GratuityRecord.objects.filter(payroll=self.object).first()
        from apps.hr.uae_gratuity import calculate_monthly_gratuity_provision, employee_gratuity_eligible

        if employee_gratuity_eligible(emp):
            as_of = date(self.object.month.year, self.object.month.month, 1)
            context['monthly_gratuity_provision'] = calculate_monthly_gratuity_provision(emp, as_of)
        else:
            context['monthly_gratuity_provision'] = None

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
        from apps.hr.payroll_allowances import replace_allowance_lines_from_post
        from apps.hr.salary_payroll_utils import (
            ensure_payroll_allowances_from_employee_template,
            refresh_payroll_gross_and_allowances,
        )

        payroll = form.save(commit=False)
        payroll.status = payroll.status or 'draft'
        if payroll.employee_id and not payroll.company_id:
            ecid = Employee.objects.filter(pk=payroll.employee_id).values_list('company_id', flat=True).first()
            if ecid:
                payroll.company_id = ecid
        emp = Employee.objects.filter(pk=payroll.employee_id).first()
        if emp and (payroll.basic_salary is None or payroll.basic_salary == Decimal('0')):
            payroll.basic_salary = emp.basic_salary or Decimal('0')
        payroll.save()
        replace_allowance_lines_from_post(payroll, self.request.POST)
        if emp:
            ensure_payroll_allowances_from_employee_template(payroll, emp)
        refresh_payroll_gross_and_allowances(payroll)
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
        from apps.hr.payroll_allowances import replace_allowance_lines_from_post
        from apps.hr.salary_payroll_utils import (
            ensure_payroll_allowances_from_employee_template,
            refresh_payroll_gross_and_allowances,
        )

        payroll = form.save(commit=False)
        if payroll.employee_id and not payroll.company_id:
            ecid = Employee.objects.filter(pk=payroll.employee_id).values_list('company_id', flat=True).first()
            if ecid:
                payroll.company_id = ecid
        payroll.save()
        replace_allowance_lines_from_post(payroll, self.request.POST)
        emp = Employee.objects.filter(pk=payroll.employee_id).first()
        if emp:
            ensure_payroll_allowances_from_employee_template(payroll, emp)
        refresh_payroll_gross_and_allowances(payroll)
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
