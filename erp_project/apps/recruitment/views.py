"""Recruitment views."""
from __future__ import annotations

import json
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import CreatePermissionMixin, PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.hr.forms import DepartmentForm, EmployeeForm
from apps.hr.models import Department, Designation, Employee, EmployeeAttachment
from apps.hr.views import EmployeeCreateView

from .forms import CandidateForm, PositionForm, RecruitmentRequestEditForm, RecruitmentRequestForm
from .models import Candidate, Position, RecruitmentRequest

from .approval_rules import annotate_recruitment_approval_actions, user_can_act_on_recruitment_request

KANBAN_META = {
    Candidate.STATUS_NEW: {'label': 'New', 'header_bg': '#eff6ff', 'header_color': '#1d4ed8'},
    Candidate.STATUS_SCREENING: {'label': 'Screening', 'header_bg': '#fef3c7', 'header_color': '#92400e'},
    Candidate.STATUS_INTERVIEW: {'label': 'Interview', 'header_bg': '#f3e8ff', 'header_color': '#6b21a8'},
    Candidate.STATUS_OFFER: {'label': 'Offer', 'header_bg': '#ecfdf5', 'header_color': '#047857'},
    Candidate.STATUS_HIRED: {'label': 'Hired', 'header_bg': '#dcfce7', 'header_color': '#166534'},
    Candidate.STATUS_REJECTED: {'label': 'Rejected', 'header_bg': '#fee2e2', 'header_color': '#991b1b'},
}


def _hr_access(user) -> bool:
    return user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'view')


def _hr_edit(user) -> bool:
    return user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'edit')


def _hr_create(user) -> bool:
    return user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'create')


def _designation_for_position(position: Position) -> Designation | None:
    if not position or not position.department_id:
        return None
    match = Designation.objects.filter(
        department_id=position.department_id,
        name__iexact=position.title,
        is_active=True,
    ).first()
    if match:
        return match
    return Designation.objects.filter(department_id=position.department_id, is_active=True).first()


def _copy_resume_to_employee(candidate: Candidate, employee: Employee, user) -> None:
    if not candidate.resume:
        return
    EmployeeAttachment.objects.create(
        employee=employee,
        file=candidate.resume,
        filename=os.path.basename(candidate.resume.name),
        label='Resume (from recruitment)',
        uploaded_by=user,
    )


class RecruitmentRequestListView(PermissionRequiredMixin, ListView):
    model = RecruitmentRequest
    template_name = 'recruitment/request_list.html'
    context_object_name = 'requests'
    paginate_by = 25
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        qs = RecruitmentRequest.objects.filter(is_active=True).select_related(
            'position',
            'position__department',
            'requested_by',
            'approved_by',
        )
        status = self.request.GET.get('status')
        if status in dict(RecruitmentRequest.STATUS_CHOICES):
            qs = qs.filter(status=status)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Recruitment Requests'
        ctx['can_create'] = _hr_create(self.request.user)
        ctx['can_edit'] = _hr_edit(self.request.user)
        base = RecruitmentRequest.objects.filter(is_active=True)
        ctx['pending_count'] = base.filter(status=RecruitmentRequest.STATUS_PENDING).count()
        ctx['open_count'] = base.filter(status=RecruitmentRequest.STATUS_OPEN).count()
        ctx['closed_count'] = base.filter(status=RecruitmentRequest.STATUS_CLOSED).count()
        ctx['status_choices'] = RecruitmentRequest.STATUS_CHOICES
        annotate_recruitment_approval_actions(self.request.user, ctx.get('requests', []))
        return ctx


class RecruitmentRequestCreateView(CreatePermissionMixin, CreateView):
    model = RecruitmentRequest
    form_class = RecruitmentRequestForm
    template_name = 'recruitment/request_form.html'
    module_name = 'hr'

    def form_valid(self, form):
        from apps.settings_app.models import ApprovalConfiguration, Notification

        form.instance.requested_by = self.request.user
        form.instance.status = RecruitmentRequest.STATUS_PENDING
        self.object = form.save()
        ApprovalConfiguration.notify_approver(self.object, 'recruitment_request')
        Notification.create(
            user=self.request.user,
            title='Recruitment Request Submitted',
            message=f'Your request for {self.object.display_reference} was submitted for approval.',
            link=f'/recruitment/requests/{self.object.pk}/',
        )
        messages.success(self.request, 'Recruitment request submitted for approval.')
        return redirect('recruitment:request_detail', pk=self.object.pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'New Recruitment Request'
        ctx['is_create'] = True
        return ctx


class RecruitmentRequestDetailView(PermissionRequiredMixin, DetailView):
    model = RecruitmentRequest
    template_name = 'recruitment/request_detail.html'
    context_object_name = 'recruitment_request'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        return RecruitmentRequest.objects.filter(is_active=True).select_related(
            'position',
            'position__department',
            'requested_by',
            'approved_by',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = self.object
        ctx['title'] = req.display_reference
        ctx['can_edit'] = _hr_edit(self.request.user) and req.status in (
            RecruitmentRequest.STATUS_PENDING,
            RecruitmentRequest.STATUS_REJECTED,
            RecruitmentRequest.STATUS_OPEN,
        )
        ctx['can_approve'] = user_can_act_on_recruitment_request(self.request.user, req)
        ctx['can_reject'] = ctx['can_approve']
        return ctx


class RecruitmentRequestUpdateView(UpdatePermissionMixin, UpdateView):
    model = RecruitmentRequest
    form_class = RecruitmentRequestEditForm
    template_name = 'recruitment/request_form.html'
    module_name = 'hr'

    def get_queryset(self):
        return RecruitmentRequest.objects.filter(is_active=True)

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.status == RecruitmentRequest.STATUS_CLOSED:
            messages.error(request, 'Closed recruitment requests cannot be edited.')
            return redirect('recruitment:request_detail', pk=obj.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('recruitment:request_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Recruitment request updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit Request — {self.object.position.title}'
        ctx['is_create'] = False
        return ctx


@login_required
def recruitment_request_approve(request, pk):
    req = get_object_or_404(RecruitmentRequest, pk=pk, is_active=True)
    if req.status != RecruitmentRequest.STATUS_PENDING:
        messages.error(request, 'Only pending requests can be approved.')
        return redirect('recruitment:request_detail', pk=pk)
    if not user_can_act_on_recruitment_request(request.user, req):
        messages.error(request, 'Only the configured approver can approve this request.')
        return redirect('recruitment:request_detail', pk=pk)

    req.status = RecruitmentRequest.STATUS_OPEN
    req.approved_by = request.user
    req.rejection_reason = ''
    req.save(update_fields=['status', 'approved_by', 'rejection_reason', 'updated_at'])

    from apps.settings_app.models import ApprovalAuditLog, Notification

    ApprovalAuditLog.objects.create(
        module='recruitment_request',
        reference=req.display_reference,
        approver=request.user,
        action='approve',
        comment='',
    )
    Notification.create(
        user=req.requested_by,
        title='Recruitment Request Approved',
        message=f'Your request for {req.display_reference} has been approved.',
        link=f'/recruitment/requests/{req.pk}/',
    )
    messages.success(request, 'Recruitment request approved.')
    return redirect('recruitment:request_detail', pk=pk)


@login_required
@require_POST
def recruitment_request_reject(request, pk):
    req = get_object_or_404(RecruitmentRequest, pk=pk, is_active=True)
    if not user_can_act_on_recruitment_request(request.user, req):
        messages.error(request, 'Only the configured approver can reject this request.')
        return redirect('recruitment:request_detail', pk=pk)
    if req.status != RecruitmentRequest.STATUS_PENDING:
        messages.error(request, 'Only pending requests can be rejected.')
        return redirect('recruitment:request_detail', pk=pk)

    comment = (request.POST.get('comment') or '').strip()
    req.status = RecruitmentRequest.STATUS_REJECTED
    req.rejection_reason = comment
    req.save(update_fields=['status', 'rejection_reason', 'updated_at'])

    from apps.settings_app.models import ApprovalAuditLog, Notification

    ApprovalAuditLog.objects.create(
        module='recruitment_request',
        reference=req.display_reference,
        approver=request.user,
        action='reject',
        comment=comment,
    )
    Notification.create(
        user=req.requested_by,
        title='Recruitment Request Rejected',
        message=f'Your request for {req.display_reference} was rejected.',
        link=f'/recruitment/requests/{req.pk}/',
    )
    messages.success(request, 'Recruitment request rejected.')
    return redirect('recruitment:request_detail', pk=pk)


class CandidateListView(PermissionRequiredMixin, ListView):
    model = Candidate
    template_name = 'recruitment/candidate_list.html'
    context_object_name = 'candidates'
    paginate_by = 25
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        qs = Candidate.objects.filter(is_active=True).select_related(
            'position_applied',
            'position_applied__department',
            'converted_employee',
        )
        search = (self.request.GET.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(position_applied__title__icontains=search)
            )
        status = self.request.GET.get('status')
        if status in dict(Candidate.STATUS_CHOICES):
            qs = qs.filter(status=status)
        return qs.order_by('-applied_date', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Candidates'
        ctx['can_create'] = _hr_create(self.request.user)
        ctx['can_edit'] = _hr_edit(self.request.user)
        ctx['status_choices'] = Candidate.STATUS_CHOICES
        return ctx


class CandidateCreateView(CreatePermissionMixin, CreateView):
    model = Candidate
    form_class = CandidateForm
    template_name = 'recruitment/candidate_form.html'
    success_url = reverse_lazy('recruitment:candidate_list')
    module_name = 'hr'

    def get_initial(self):
        initial = super().get_initial()
        initial.setdefault('applied_date', timezone.localdate())
        initial.setdefault('status', Candidate.STATUS_NEW)
        return initial

    def form_valid(self, form):
        messages.success(self.request, 'Candidate added.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add Candidate'
        return ctx


class CandidateDetailView(PermissionRequiredMixin, DetailView):
    model = Candidate
    template_name = 'recruitment/candidate_detail.html'
    context_object_name = 'candidate'
    module_name = 'hr'
    permission_type = 'view'

    def get_queryset(self):
        return Candidate.objects.filter(is_active=True).select_related(
            'position_applied',
            'position_applied__department',
            'converted_employee',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = self.object.name
        ctx['can_edit'] = _hr_edit(self.request.user) and not self.object.is_locked
        ctx['can_convert'] = (
            _hr_create(self.request.user)
            and self.object.status == Candidate.STATUS_HIRED
            and not self.object.converted_employee_id
        )
        return ctx


class CandidateUpdateView(UpdatePermissionMixin, UpdateView):
    model = Candidate
    form_class = CandidateForm
    template_name = 'recruitment/candidate_form.html'
    module_name = 'hr'

    def get_queryset(self):
        return Candidate.objects.filter(is_active=True)

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_locked:
            messages.error(request, 'This candidate is locked after conversion to employee.')
            return redirect('recruitment:candidate_detail', pk=obj.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('recruitment:candidate_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Candidate updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit Candidate — {self.object.name}'
        return ctx


class CandidateConvertEmployeeView(EmployeeCreateView):
    """Reuse HR employee create form; link candidate on success."""

    module_name = 'hr'

    def dispatch(self, request, candidate_pk, *args, **kwargs):
        self.candidate = get_object_or_404(
            Candidate.objects.select_related('position_applied', 'position_applied__department'),
            pk=candidate_pk,
            is_active=True,
        )
        if self.candidate.status != Candidate.STATUS_HIRED:
            messages.error(request, 'Only hired candidates can be converted to employees.')
            return redirect('recruitment:candidate_detail', pk=candidate_pk)
        if self.candidate.converted_employee_id:
            messages.error(request, 'This candidate was already converted.')
            return redirect('recruitment:candidate_detail', pk=candidate_pk)
        if not _hr_create(request.user):
            messages.error(request, 'Permission denied.')
            return redirect('recruitment:candidate_detail', pk=candidate_pk)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        first, last = self.candidate.split_name()
        position = self.candidate.position_applied
        designation = _designation_for_position(position)
        initial.update({
            'first_name': first,
            'last_name': last,
            'email': self.candidate.email or '',
            'phone': self.candidate.phone or '',
            'department': position.department_id if position else None,
            'designation': designation.pk if designation else None,
            'date_of_joining': timezone.localdate(),
            'status': 'active',
        })
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Convert to Employee — {self.candidate.name}'
        ctx['candidate'] = self.candidate
        ctx['from_candidate'] = True
        return ctx

    def post(self, request, candidate_pk, *args, **kwargs):
        self.candidate = get_object_or_404(
            Candidate.objects.select_related('position_applied', 'position_applied__department'),
            pk=candidate_pk,
            is_active=True,
        )
        return _employee_create_post_with_candidate(self, request, self.candidate)


def _employee_create_post_with_candidate(view, request, candidate):
    from apps.hr.forms_extended import EmployeeBankDetailForm, UAEComplianceForm
    from apps.hr.models_extended import UAECompliance
    from apps.hr.views import (
        _employee_hr_profile_form,
        _provision_employee_login_if_needed,
        _sync_employee_hr_profile,
    )

    view.object = None
    form = view.get_form()
    if not form.is_valid():
        ctx = view.get_context_data(form=form)
        ctx['uae_form'] = UAEComplianceForm(request.POST, prefix='uae')
        return view.render_to_response(ctx)

    try:
        with transaction.atomic():
            employee = form.save()
            view.object = employee
            _provision_employee_login_if_needed(request, form, employee)
            uc, _ = UAECompliance.objects.get_or_create(employee=employee)
            uf = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
            if not uf.is_valid():
                transaction.set_rollback(True)
                ctx = view.get_context_data(form=form)
                ctx['uae_form'] = uf
                return view.render_to_response(ctx)
            uf.save()
            bf = EmployeeBankDetailForm(request.POST, instance=getattr(employee, 'bank_detail', None))
            if not bf.is_valid():
                transaction.set_rollback(True)
                ctx = view.get_context_data(form=form)
                ctx['bank_form'] = bf
                ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                return view.render_to_response(ctx)
            bf.save_for_employee(employee)
            _sync_employee_hr_profile(employee)
            hpf = _employee_hr_profile_form(request, employee)
            if not hpf.is_valid():
                transaction.set_rollback(True)
                ctx = view.get_context_data(form=form)
                ctx['hr_profile_form'] = hpf
                ctx['uae_form'] = UAEComplianceForm(request.POST, instance=uc, prefix='uae')
                return view.render_to_response(ctx)
            hpf.save()

            candidate.converted_employee = employee
            candidate.conversion_date = employee.date_of_joining or timezone.localdate()
            candidate.save(update_fields=['converted_employee', 'conversion_date', 'updated_at'])
            _copy_resume_to_employee(candidate, employee, request.user)
    except Exception:
        raise

    messages.success(request, f'{candidate.name} converted to employee {employee.employee_code}.')
    return redirect('hr:employee_detail', pk=employee.pk)


@login_required
@require_POST
def candidate_kanban_move(request):
    if not _hr_edit(request.user):
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    try:
        body = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    pk = body.get('candidate_id')
    status = (body.get('status') or '').strip()
    if not pk or status not in Candidate.KANBAN_STATUSES:
        return JsonResponse({'error': 'candidate_id and valid status required.'}, status=400)

    candidate = Candidate.objects.filter(pk=pk, is_active=True).first()
    if not candidate:
        return JsonResponse({'error': 'Candidate not found.'}, status=404)
    if candidate.is_locked:
        return JsonResponse({'error': 'Candidate is locked after conversion.'}, status=400)

    candidate.status = status
    candidate.save(update_fields=['status', 'updated_at'])
    return JsonResponse({'ok': True, 'status': status})


@login_required
def recruitment_settings(request):
    if not _hr_access(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')

    can_edit = _hr_edit(request.user)
    position_form = PositionForm(prefix='pos')
    dept_form = DepartmentForm(prefix='dept')

    if request.method == 'POST' and can_edit:
        if 'save_position' in request.POST:
            position_form = PositionForm(request.POST, prefix='pos')
            if position_form.is_valid():
                position_form.save()
                messages.success(request, 'Position saved.')
                return redirect('recruitment:settings')
        elif 'save_department' in request.POST:
            dept_form = DepartmentForm(request.POST, prefix='dept')
            if dept_form.is_valid():
                dept_form.save()
                messages.success(request, 'Department saved.')
                return redirect('recruitment:settings')
        elif 'delete_position' in request.POST:
            pos_id = request.POST.get('position_id')
            pos = Position.objects.filter(pk=pos_id, is_active=True).first()
            if pos:
                pos.is_active = False
                pos.save(update_fields=['is_active', 'updated_at'])
                messages.success(request, 'Position removed.')
            return redirect('recruitment:settings')

    positions = Position.objects.filter(is_active=True).select_related('department').order_by('title')
    departments = Department.objects.filter(is_active=True).order_by('name')

    return render(
        request,
        'recruitment/settings.html',
        {
            'title': 'Recruitment Settings',
            'positions': positions,
            'departments': departments,
            'position_form': position_form,
            'dept_form': dept_form,
            'can_edit': can_edit,
        },
    )
