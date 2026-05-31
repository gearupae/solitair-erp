"""Projects Views"""
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseNotAllowed
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse, reverse_lazy
from django.db.models import Q, Sum, Count, Value, Prefetch
from django.db.models.fields import DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from .models import (
    Project,
    Task,
    ProjectExpense,
    ProjectGatepass,
    ProjectPublicUpload,
    ProjectItemLine,
)
from .forms import ProjectForm, ProjectTaskCreateForm, TaskForm, ProjectExpenseForm, ProjectGatepassForm, ProjectItemDeliveryForm, ProjectItemReturnForm
from .gatepass_alerts import pick_display_gatepass
from .item_delivery import (
    deliver_items_to_project,
    project_delivery_display_rows,
    project_delivery_summary_groups,
    project_inventory_spend_total,
    project_item_delivered_qty,
    project_item_remaining_qty,
    project_item_returnable_qty,
    project_return_history_rows,
    return_items_from_project,
    return_serial_unit_from_project,
)
from .labour_utils import project_labour_summary
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.notification_utils import notify_if_new_assignee, notify_user
from apps.core.utils import PermissionChecker

User = get_user_model()


class ProjectListView(PermissionRequiredMixin, ListView):
    model = Project
    template_name = 'projects/project_list.html'
    context_object_name = 'projects'
    module_name = 'projects'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = Project.objects.filter(is_active=True).select_related('customer', 'manager', 'created_by')
        from apps.core.visibility import filter_projects_for_user

        queryset = filter_projects_for_user(queryset, self.request.user)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(project_code__icontains=search))
        status = self.request.GET.get('status')
        if status == 'completion_pending':
            queryset = queryset.filter(edit_approval_status='pending')
        elif status:
            queryset = queryset.filter(status=status)
        # Sum manual project expenses (active, not rejected, not from a vendor bill)
        queryset = queryset.annotate(
            manual_expenses_sum=Coalesce(
                Sum(
                    'project_expenses__total_amount',
                    filter=Q(project_expenses__is_active=True)
                    & ~Q(project_expenses__status='rejected')
                    & Q(project_expenses__vendor_bill__isnull=True),
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )
        # Sum vendor bill amounts linked to the project (all active, non-cancelled)
        queryset = queryset.annotate(
            vendor_bills_sum=Coalesce(
                Sum(
                    'vendor_bills__total_amount',
                    filter=Q(vendor_bills__is_active=True)
                    & ~Q(vendor_bills__status='cancelled'),
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )
        return queryset.order_by('-created_at', '-pk')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Projects'
        context['status_choices'] = Project.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'edit')

        from .approval_rules import (
            pending_completion_projects_for_user,
            user_is_project_completion_approver,
        )

        pending_completion = pending_completion_projects_for_user(self.request.user)
        context['pending_completion_projects'] = pending_completion
        context['pending_completion_count'] = len(pending_completion)
        context['is_project_completion_approver'] = user_is_project_completion_approver(self.request.user)
        context['status_filter_choices'] = list(Project.STATUS_CHOICES) + [
            ('completion_pending', 'Pending completion approval'),
        ]
        
        # Calculate metrics (respect visibility scope for non-elevated users)
        from apps.core.visibility import filter_projects_for_user

        all_projects = filter_projects_for_user(
            Project.objects.filter(is_active=True), self.request.user
        )
        context['total_projects'] = all_projects.count()
        context['in_progress_projects'] = all_projects.filter(status='in_progress').count()
        context['completed_projects'] = all_projects.filter(status='completed').count()
        
        return context


@never_cache
@require_http_methods(['GET', 'POST'])
def public_project_upload(request):
    """
    Public (no login): select a project and attach many files or camera photos.
    Files appear on the project overview page for staff.
    """
    project_qs = Project.objects.filter(is_active=True).order_by('project_code', 'name')

    if request.method == 'POST':
        raw_pid = request.POST.get('project')
        note = (request.POST.get('note') or '').strip()[:500]
        if not raw_pid or not str(raw_pid).isdigit():
            messages.error(request, 'Please select a project.')
            return render(
                request,
                'projects/public_upload_form.html',
                {'projects': project_qs, 'posted_note': note},
                status=400,
            )
        project = Project.objects.filter(pk=int(raw_pid), is_active=True).first()
        if not project:
            messages.error(request, 'Invalid project.')
            return render(
                request,
                'projects/public_upload_form.html',
                {'projects': project_qs, 'posted_note': note},
                status=400,
            )
        files = request.FILES.getlist('files')
        if not files:
            messages.error(request, 'Please add at least one file or photo.')
            return render(
                request,
                'projects/public_upload_form.html',
                {
                    'projects': project_qs,
                    'selected_project_id': project.pk,
                    'posted_note': note,
                },
                status=400,
            )
        created = 0
        for f in files:
            if not f.name:
                continue
            ProjectPublicUpload.objects.create(
                project=project,
                file=f,
                original_filename=(getattr(f, 'name', '') or '')[:255],
                note=note,
            )
            created += 1
        if created == 0:
            messages.error(request, 'No files were saved. Try again.')
            return render(
                request,
                'projects/public_upload_form.html',
                {
                    'projects': project_qs,
                    'selected_project_id': project.pk,
                    'posted_note': note,
                },
                status=400,
            )
        messages.success(
            request,
            f'Thank you. {created} file(s) were uploaded to {project.project_code} — {project.name}.',
        )
        return redirect('projects:public_upload')

    return render(
        request,
        'projects/public_upload_form.html',
        {'projects': project_qs},
    )


class TaskListView(PermissionRequiredMixin, ListView):
    """All tasks across projects with filters."""
    model = Task
    template_name = 'projects/task_list.html'
    context_object_name = 'tasks'
    module_name = 'projects'
    permission_type = 'view'
    paginate_by = 30

    def get_paginate_by(self, queryset):
        if self.request.GET.get('view') == 'kanban':
            return None
        return self.paginate_by

    def get_queryset(self):
        qs = Task.objects.filter(is_active=True).select_related(
            'project', 'customer', 'assigned_to', 'assigned_to__employee_profile'
        ).order_by(
            'due_date', 'start_date', 'project__project_code', 'customer__customer_number', 'name'
        )
        search = self.request.GET.get('search')
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(project__name__icontains=search)
                | Q(project__project_code__icontains=search)
                | Q(customer__name__icontains=search)
                | Q(customer__customer_number__icontains=search)
            )
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        project_id = self.request.GET.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        customer_id = self.request.GET.get('customer')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        assigned = self.request.GET.get('assigned_to')
        if assigned:
            qs = qs.filter(assigned_to_id=assigned)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'All Tasks'
        context['status_choices'] = Task.STATUS_CHOICES
        context['project_filter_list'] = Project.objects.filter(is_active=True).order_by('project_code')
        from django.contrib.auth import get_user_model

        User = get_user_model()
        context['assignable_users'] = User.objects.filter(is_active=True).select_related(
            'employee_profile'
        ).order_by('first_name', 'last_name', 'username')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'projects', 'edit'
        )
        context['view_mode'] = self.request.GET.get('view', 'list')
        q = self.request.GET.copy()
        q.pop('view', None)
        list_q = q.copy()
        list_q['view'] = 'list'
        kanban_q = q.copy()
        kanban_q['view'] = 'kanban'
        context['task_list_url_list'] = '?' + list_q.urlencode()
        context['task_list_url_kanban'] = '?' + kanban_q.urlencode()
        if context['view_mode'] == 'kanban':
            qs = self.get_queryset()
            context['tasks_kanban_pending'] = list(qs.filter(status='pending'))
            context['tasks_kanban_progress'] = list(qs.filter(status='in_progress'))
            context['tasks_kanban_done'] = list(qs.filter(status='completed'))
        return context


class ProjectCreateView(CreatePermissionMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = 'projects/project_form.html'
    success_url = reverse_lazy('projects:project_list')
    module_name = 'projects'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Project'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Project {form.instance.name} created.')
        response = super().form_valid(form)
        project = self.object
        link = reverse('projects:project_detail', kwargs={'pk': project.pk})
        creator = self.request.user
        seen = set()
        recipients = []
        if project.manager_id:
            recipients.append(project.manager)
        recipients.extend(list(project.members.all()))
        recipients.extend(list(project.technicians.all()))
        for u in recipients:
            if not u or u.pk in seen:
                continue
            seen.add(u.pk)
            notify_if_new_assignee(
                u,
                creator,
                f'Project: {project.project_code}',
                f'You were added to {project.name}.',
                link,
            )
        return response


class ProjectUpdateView(UpdatePermissionMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = 'projects/project_form.html'
    success_url = reverse_lazy('projects:project_list')
    module_name = 'projects'

    def get_queryset(self):
        from apps.core.visibility import filter_projects_for_user

        return filter_projects_for_user(Project.objects.filter(is_active=True), self.request.user)

    def form_valid(self, form):
        # form.is_valid() already mutates self.object.status from POST data — read DB for original
        prior = Project.objects.filter(pk=self.object.pk).values(
            'status', 'edit_approval_status'
        ).first() or {}
        old_status = prior.get('status') or form.initial.get('status')
        prior_edit_approval = prior.get('edit_approval_status') or 'none'
        new_status = form.cleaned_data['status']
        completion_requested = new_status == 'completed' and old_status != 'completed'

        from .completion_approval import (
            clear_project_completion_approval,
            completion_approval_required,
            queue_project_completion_approval,
        )

        needs_completion_approval = (
            completion_requested and completion_approval_required(self.request.user, self.object)
        )

        if needs_completion_approval:
            form.instance.status = old_status
        elif completion_requested:
            clear_project_completion_approval(form.instance)
        elif new_status != 'completed' and prior_edit_approval in ('pending', 'rejected'):
            clear_project_completion_approval(form.instance)

        self.object = form.save(commit=False)
        self.object.save()
        form.save_m2m()

        if needs_completion_approval:
            queue_project_completion_approval(self.request.user, self.object)
            messages.info(
                self.request,
                'Completion request submitted for approval. Status will update to Completed once approved.',
            )
        else:
            messages.success(self.request, 'Project saved successfully.')
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Project: {self.object.name}'
        return context


@login_required
def project_approve_completion(request, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    project = get_object_or_404(Project, pk=pk, is_active=True)
    from .approval_rules import user_can_approve_project_completion

    if not user_can_approve_project_completion(request.user, project):
        messages.error(request, 'Permission denied.')
        return redirect('projects:project_detail', pk=pk)
    if project.edit_approval_status != 'pending':
        messages.warning(request, 'This project does not have a pending completion request.')
        return redirect('projects:project_detail', pk=pk)

    submitter = project.edit_approval_submitted_by
    project.status = 'completed'
    project.edit_approval_status = 'none'
    project.edit_approval_submitted_at = None
    project.edit_approval_submitted_by_id = None
    project.save(
        update_fields=[
            'status',
            'edit_approval_status',
            'edit_approval_submitted_at',
            'edit_approval_submitted_by',
            'updated_at',
        ]
    )
    from apps.settings_app.models import ApprovalAuditLog
    from .project_approval_notifications import notify_submitter_project_completion_approved

    ApprovalAuditLog.objects.create(
        module='project',
        reference=project.project_code,
        approver=request.user,
        action='approve',
        comment='Project completion approved',
    )
    if submitter:
        notify_submitter_project_completion_approved(
            project, approver=request.user, submitter=submitter
        )
    messages.success(request, f'{project.project_code} marked as Completed.')
    return redirect('projects:project_detail', pk=pk)


@login_required
def project_reject_completion(request, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    project = get_object_or_404(Project, pk=pk, is_active=True)
    from .approval_rules import user_can_approve_project_completion

    if not user_can_approve_project_completion(request.user, project):
        messages.error(request, 'Permission denied.')
        return redirect('projects:project_detail', pk=pk)
    if project.edit_approval_status != 'pending':
        messages.warning(request, 'This project does not have a pending completion request.')
        return redirect('projects:project_detail', pk=pk)

    comment = (request.POST.get('comment') or '').strip()
    submitter = project.edit_approval_submitted_by
    project.edit_approval_status = 'rejected'
    project.save(update_fields=['edit_approval_status', 'updated_at'])
    from apps.settings_app.models import ApprovalAuditLog
    from .project_approval_notifications import notify_submitter_project_completion_rejected

    ApprovalAuditLog.objects.create(
        module='project',
        reference=project.project_code,
        approver=request.user,
        action='reject',
        comment=comment or 'Project completion rejected',
    )
    if submitter:
        notify_submitter_project_completion_rejected(
            project,
            approver=request.user,
            submitter=submitter,
            comment=comment,
        )
    messages.warning(request, f'Completion request for {project.project_code} was rejected.')
    return redirect('projects:project_detail', pk=pk)


class ProjectDetailView(PermissionRequiredMixin, DetailView):
    model = Project
    template_name = 'projects/project_detail.html'
    context_object_name = 'project'
    module_name = 'projects'
    permission_type = 'view'

    def get_queryset(self):
        item_line_qs = ProjectItemLine.objects.select_related('inventory_item').order_by(
            'sort_order', 'id'
        )
        qs = Project.objects.select_related('customer', 'manager', 'created_by').prefetch_related(
            Prefetch(
                'members',
                queryset=User.objects.select_related(
                    'employee_profile',
                    'employee_profile__designation',
                    'employee_profile__department',
                ).order_by('first_name', 'last_name', 'username'),
            ),
            Prefetch(
                'technicians',
                queryset=User.objects.select_related(
                    'employee_profile',
                    'employee_profile__designation',
                    'employee_profile__department',
                ).order_by('first_name', 'last_name', 'username'),
            ),
            'gatepasses',
            'public_uploads',
            Prefetch('item_lines', queryset=item_line_qs),
        )
        from apps.core.visibility import filter_projects_for_user

        return filter_projects_for_user(qs, self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Project: {self.object.name}'
        context['tasks'] = self.object.tasks.filter(is_active=True).select_related(
            'assigned_to', 'assigned_to__employee_profile'
        )
        item_lines = list(self.object.item_lines.all())
        from apps.inventory.models import Item

        for line in item_lines:
            if line.inventory_item_id:
                item = line.inventory_item
                normalized_qty = Item.normalize_quantity(item, line.quantity)
                if normalized_qty != line.quantity:
                    rate = line.rate or line.unit_price or Decimal('0')
                    ProjectItemLine.objects.filter(pk=line.pk).update(
                        quantity=normalized_qty,
                        line_net=(normalized_qty * rate).quantize(Decimal('0.01')),
                    )
                    line.quantity = normalized_qty
                    line.line_net = (normalized_qty * rate).quantize(Decimal('0.01'))
                delivered = project_item_delivered_qty(self.object, item)
                remaining = project_item_remaining_qty(self.object, item) or Decimal('0')
                returnable = project_item_returnable_qty(self.object, item)
                line.delivered_qty = delivered
                line.remaining_qty = remaining
                line.returnable_qty = returnable
                line.max_deliver_qty = min(remaining, line.quantity)
                line.max_return_qty = min(returnable, line.quantity)
                line.track_by_serial = item.track_by_serial
                line.requires_whole_quantity = item.requires_whole_quantity()
            else:
                line.delivered_qty = None
                line.remaining_qty = None
                line.returnable_qty = None
                line.max_deliver_qty = None
                line.max_return_qty = None
                line.track_by_serial = False
                line.requires_whole_quantity = False
        context['project_item_lines'] = item_lines
        if 'task_form' not in context:
            context['task_form'] = ProjectTaskCreateForm()

        can_edit_gp = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'projects', 'edit'
        )
        if 'gatepass_form' in kwargs:
            context['gatepass_form'] = kwargs['gatepass_form']
            context['editing_gatepass_pk'] = kwargs.get('editing_gatepass_pk')
        else:
            edit_pk = self.request.GET.get('edit_gatepass')
            gp_edit = None
            if edit_pk and str(edit_pk).isdigit() and can_edit_gp:
                gp_edit = ProjectGatepass.objects.filter(
                    pk=int(edit_pk), project=self.object, is_active=True
                ).first()
            if gp_edit:
                context['gatepass_form'] = ProjectGatepassForm(instance=gp_edit, project=self.object)
                context['editing_gatepass_pk'] = gp_edit.pk
            else:
                context['gatepass_form'] = ProjectGatepassForm(project=self.object)
                context['editing_gatepass_pk'] = None
        context['open_gatepass_create'] = (
            self.request.GET.get('open_gatepass') == '1' and context.get('editing_gatepass_pk') is None
        )

        members = list(
            self.object.members.all().order_by('first_name', 'last_name', 'username')
        )
        all_gp = list(
            self.object.gatepasses.filter(is_active=True)
            .select_related('member')
            .order_by('-expiry_date', '-created_at')
        )
        by_member = {}
        for g in all_gp:
            by_member.setdefault(g.member_id, []).append(g)
        today = date.today()
        context['member_gatepass_rows'] = [
            {
                'member': m,
                'gatepass': pick_display_gatepass(by_member.get(m.pk, []), today),
            }
            for m in members
        ]
        context['project_gatepasses'] = all_gp
        context['can_edit'] = self.object.allows_edit_by(self.request.user)
        from .approval_rules import user_can_approve_project_completion

        context['can_approve_project_completion'] = user_can_approve_project_completion(
            self.request.user, self.object
        )
        context['can_create_projects'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'projects', 'create'
        )
        pe = self.object.project_expenses.filter(is_active=True).exclude(
            status='rejected'
        ).exclude(vendor_bill__isnull=False)   # bill-synced rows counted via vendor bills below
        agg = pe.aggregate(s=Sum('total_amount'), c=Count('id'))
        manual_expenses_total = agg['s'] if agg['s'] is not None else Decimal('0.00')
        context['manual_expenses_total'] = manual_expenses_total
        context['has_manual_expenses'] = (agg['c'] or 0) > 0

        # Vendor bills linked to this project (all active statuses — draft counts as committed)
        from apps.purchase.models import VendorBill
        vendor_bills = (
            self.object.vendor_bills
            .filter(is_active=True)
            .exclude(status='cancelled')
            .select_related('vendor')
            .order_by('-bill_date')
        )
        bills_total = vendor_bills.aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')
        context['project_vendor_bills'] = vendor_bills
        context['project_vendor_bills_total'] = bills_total
        context['has_vendor_bills'] = vendor_bills.exists()

        inventory_spend = project_inventory_spend_total(self.object)
        context['inventory_spend_total'] = inventory_spend

        recorded = manual_expenses_total + bills_total + inventory_spend
        context['recorded_expenses_total'] = recorded
        budget_prop = self.object.budget
        context['budget_profit'] = budget_prop - recorded
        # Header “profit” vs expenses: use contract value when set (e.g. from estimate conversion),
        # since budget may hold cost baseline rather than customer revenue.
        cv = self.object.contract_value or Decimal('0.00')
        if cv > 0:
            context['header_profit_vs_expenses'] = cv - recorded
            context['header_profit_label'] = 'Contract value − total expense'
        else:
            context['header_profit_vs_expenses'] = budget_prop - recorded
            context['header_profit_label'] = 'Budget − total expense'
        if budget_prop > 0:
            pct = (recorded / budget_prop * Decimal('100')).quantize(Decimal('0.1'))
            context['budget_pct_used'] = pct
            context['budget_over'] = recorded > budget_prop
            cap = Decimal('100')
            context['budget_bar_width'] = float(pct if pct <= cap else cap)
        else:
            context['budget_pct_used'] = None
            context['budget_bar_width'] = None
            context['budget_over'] = False
        context['has_recorded_expenses'] = recorded > 0
        context['today'] = date.today()
        context['gatepass_alert_horizon'] = date.today() + timedelta(days=10)
        context['public_uploads'] = (
            self.object.public_uploads.filter(is_active=True).order_by('-created_at')
        )
        labour_rows, labour_hours, labour_cost = project_labour_summary(self.object)
        context['labour_rows'] = labour_rows
        context['labour_total_hours'] = labour_hours
        context['labour_total_cost'] = labour_cost
        context['show_labour_card'] = (
            self.object.technicians.exists() or labour_hours > 0 or labour_cost > 0
        )
        from .member_roles import build_project_team_display

        context['project_team'] = build_project_team_display(self.object)
        context['item_delivery_groups'] = project_delivery_summary_groups(self.object)
        context['item_return_rows'] = project_return_history_rows(self.object)
        can_deliver = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'inventory', 'edit'
        )
        context['can_deliver_items'] = can_deliver and self.object.allows_edit_by(self.request.user)
        if 'item_delivery_form' in kwargs:
            context['item_delivery_form'] = kwargs['item_delivery_form']
        else:
            context['item_delivery_form'] = ProjectItemDeliveryForm(
                project=self.object,
                initial={'delivered_date': timezone.now().date()},
            )
        if 'item_return_form' in kwargs:
            context['item_return_form'] = kwargs['item_return_form']
        else:
            context['item_return_form'] = ProjectItemReturnForm(
                project=self.object,
                initial={'returned_date': timezone.now().date()},
            )
        from apps.inventory.models import ConsumableRequest

        context['project_item_requests'] = (
            ConsumableRequest.objects.filter(project=self.object, is_active=True)
            .select_related('requested_by')
            .prefetch_related('items__item')
            .order_by('-created_at')
        )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get('action', 'add_task')

        if action == 'record_item_delivery':
            if not (
                request.user.is_superuser
                or PermissionChecker.has_permission(request.user, 'inventory', 'edit')
            ):
                messages.error(request, 'Permission denied.')
                return redirect('projects:project_detail', pk=self.object.pk)
            form = ProjectItemDeliveryForm(request.POST, project=self.object)
            if form.is_valid():
                try:
                    result = deliver_items_to_project(
                        self.object,
                        form.cleaned_data['item'],
                        form.cleaned_data['quantity'],
                        form.cleaned_data['delivered_date'],
                        request.user,
                    )
                    serials = result.get('serials') or []
                    if serials:
                        nums = ', '.join(s.model_number for s in serials)
                        messages.success(
                            request,
                            f'Delivered {len(serials)} unit(s) of {form.cleaned_data["item"].name} '
                            f'(FIFO: {nums}).',
                        )
                    else:
                        messages.success(
                            request,
                            f'Delivered {form.cleaned_data["quantity"]} × {form.cleaned_data["item"].name}.',
                        )
                except ValidationError as exc:
                    msgs = exc.messages if hasattr(exc, 'messages') else [str(exc)]
                    for msg in msgs:
                        messages.error(request, msg)
                    context = self.get_context_data(item_delivery_form=form)
                    return self.render_to_response(context)
                return redirect('projects:project_detail', pk=self.object.pk)
            messages.error(request, 'Please correct the delivery form errors below.')
            context = self.get_context_data(item_delivery_form=form)
            return self.render_to_response(context)

        if action == 'return_item_stock':
            if not (
                request.user.is_superuser
                or PermissionChecker.has_permission(request.user, 'inventory', 'edit')
            ):
                messages.error(request, 'Permission denied.')
                return redirect('projects:project_detail', pk=self.object.pk)
            form = ProjectItemReturnForm(request.POST, project=self.object)
            if form.is_valid():
                try:
                    result = return_items_from_project(
                        self.object,
                        form.cleaned_data['item'],
                        form.cleaned_data['quantity'],
                        form.cleaned_data['returned_date'],
                        request.user,
                    )
                    serials = result.get('serials') or []
                    if serials:
                        nums = ', '.join(s.model_number for s in serials)
                        messages.success(
                            request,
                            f'Returned {len(serials)} unit(s) of {form.cleaned_data["item"].name} '
                            f'to stock ({nums}).',
                        )
                    else:
                        messages.success(
                            request,
                            f'Returned {form.cleaned_data["quantity"]} × {form.cleaned_data["item"].name} to stock.',
                        )
                except ValidationError as exc:
                    msgs = exc.messages if hasattr(exc, 'messages') else [str(exc)]
                    for msg in msgs:
                        messages.error(request, msg)
                    context = self.get_context_data(item_return_form=form)
                    return self.render_to_response(context)
                return redirect('projects:project_detail', pk=self.object.pk)
            messages.error(request, 'Please correct the return form errors below.')
            context = self.get_context_data(item_return_form=form)
            return self.render_to_response(context)

        if action in ('inline_deliver_item', 'inline_return_item'):
            if not (
                request.user.is_superuser
                or PermissionChecker.has_permission(request.user, 'inventory', 'edit')
            ):
                messages.error(request, 'Permission denied.')
                return redirect('projects:project_detail', pk=self.object.pk)
            if not self.object.allows_edit_by(request.user):
                messages.error(request, 'This project cannot be edited.')
                return redirect('projects:project_detail', pk=self.object.pk)

            item_pk = request.POST.get('item_id', '').strip()
            if not item_pk.isdigit():
                messages.error(request, 'Invalid item.')
                return redirect('projects:project_detail', pk=self.object.pk)

            from apps.inventory.models import Item

            item = get_object_or_404(Item, pk=int(item_pk), is_active=True)
            line_pk = request.POST.get('line_id', '').strip()
            max_qty = None
            if line_pk.isdigit():
                line = ProjectItemLine.objects.filter(
                    pk=int(line_pk),
                    project=self.object,
                    inventory_item=item,
                ).first()
                if line:
                    if action == 'inline_deliver_item':
                        remaining = project_item_remaining_qty(self.object, item) or Decimal('0')
                        max_qty = min(remaining, line.quantity)
                    else:
                        returnable = project_item_returnable_qty(self.object, item)
                        max_qty = min(returnable, line.quantity)

            try:
                qty = Decimal(str(request.POST.get('quantity', ''))).quantize(Decimal('0.01'))
            except Exception:
                messages.error(request, 'Enter a valid quantity.')
                return redirect('projects:project_detail', pk=self.object.pk)

            if qty <= 0:
                messages.error(request, 'Quantity must be greater than zero.')
                return redirect('projects:project_detail', pk=self.object.pk)

            if max_qty is not None and qty > max_qty:
                if action == 'inline_deliver_item':
                    messages.error(
                        request,
                        f'You can deliver at most {max_qty} for this line (listed qty {line.quantity}).',
                    )
                else:
                    messages.error(
                        request,
                        f'You can return at most {max_qty} for this line.',
                    )
                return redirect('projects:project_detail', pk=self.object.pk)

            today = timezone.now().date()
            try:
                if action == 'inline_deliver_item':
                    result = deliver_items_to_project(
                        self.object,
                        item,
                        qty,
                        today,
                        request.user,
                    )
                    serials = result.get('serials') or []
                    if serials:
                        messages.success(
                            request,
                            f'Delivered {len(serials)} unit(s) of {item.name} to the project.',
                        )
                    else:
                        messages.success(
                            request,
                            f'Delivered {qty} × {item.name} to the project.',
                        )
                else:
                    result = return_items_from_project(
                        self.object,
                        item,
                        qty,
                        today,
                        request.user,
                    )
                    serials = result.get('serials') or []
                    if serials:
                        messages.success(
                            request,
                            f'Returned {len(serials)} unit(s) of {item.name} to stock.',
                        )
                    else:
                        messages.success(
                            request,
                            f'Returned {qty} × {item.name} to stock.',
                        )
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if exc.messages else str(exc))
            return redirect('projects:project_detail', pk=self.object.pk)

        if action == 'return_serial_unit':
            if not (
                request.user.is_superuser
                or PermissionChecker.has_permission(request.user, 'inventory', 'edit')
            ):
                messages.error(request, 'Permission denied.')
                return redirect('projects:project_detail', pk=self.object.pk)
            serial_pk = request.POST.get('serial_pk')
            return_date = timezone.now().date()
            try:
                sn = return_serial_unit_from_project(
                    self.object,
                    int(serial_pk),
                    return_date,
                    request.user,
                )
                messages.success(
                    request,
                    f'Returned {sn.model_number} ({sn.item.name}) to inventory stock.',
                )
            except (ValidationError, ValueError, TypeError) as exc:
                msgs = exc.messages if hasattr(exc, 'messages') else [str(exc)]
                for msg in msgs:
                    messages.error(request, msg)
            return redirect('projects:project_detail', pk=self.object.pk)

        if action == 'save_gatepass':
            gatepass_id = request.POST.get('gatepass_id')
            if gatepass_id:
                if not (
                    request.user.is_superuser
                    or PermissionChecker.has_permission(request.user, 'projects', 'edit')
                ):
                    messages.error(request, 'Permission denied.')
                    return redirect('projects:project_detail', pk=self.object.pk)
                gp = get_object_or_404(
                    ProjectGatepass,
                    pk=gatepass_id,
                    project=self.object,
                    is_active=True,
                )
                form = ProjectGatepassForm(request.POST, instance=gp, project=self.object)
            else:
                if not (
                    request.user.is_superuser
                    or PermissionChecker.has_permission(request.user, 'projects', 'create')
                ):
                    messages.error(request, 'Permission denied.')
                    return redirect('projects:project_detail', pk=self.object.pk)
                form = ProjectGatepassForm(request.POST, project=self.object)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.project = self.object
                obj.save()
                who = obj.member.get_full_name() or obj.member.username
                if gatepass_id:
                    messages.success(request, f'Gate pass updated for {who}.')
                else:
                    messages.success(request, f'Gate pass added for {who}.')
                return redirect('projects:project_detail', pk=self.object.pk)
            messages.error(request, 'Please correct the gate pass errors below.')
            edit_pk_val = None
            if gatepass_id and str(gatepass_id).isdigit():
                edit_pk_val = int(gatepass_id)
            context = self.get_context_data(
                gatepass_form=form,
                editing_gatepass_pk=edit_pk_val,
            )
            return self.render_to_response(context)

        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'create')):
            messages.error(request, 'Permission denied.')
            return redirect('projects:project_detail', pk=self.object.pk)

        form = ProjectTaskCreateForm(request.POST)
        if form.is_valid():
            members = list(form.cleaned_data['members'])
            if not members:
                form.add_error('members', 'Select at least one member.')
                context = self.get_context_data(task_form=form)
                return self.render_to_response(context)

            link = reverse('projects:task_list') + f'?project={self.object.pk}'
            customer = self.object.customer if self.object.customer_id else None
            created_count = 0
            for member in members:
                task = Task.objects.create(
                    project=self.object,
                    customer=customer,
                    name=form.cleaned_data['name'],
                    description=form.cleaned_data['description'],
                    start_date=form.cleaned_data['start_date'],
                    due_date=form.cleaned_data['due_date'],
                    assigned_to=member,
                    status=form.cleaned_data['status'],
                    priority=form.cleaned_data['priority'],
                    estimated_hours=form.cleaned_data['estimated_hours'] or Decimal('0.00'),
                )
                created_count += 1
                notify_if_new_assignee(
                    member,
                    request.user,
                    f'Task assigned: {task.name}',
                    f'{self.object.project_code} — {task.name}',
                    link,
                )
            if created_count == 1:
                messages.success(request, f'Task {form.cleaned_data["name"]} created.')
            else:
                messages.success(
                    request,
                    f'{created_count} tasks created for {form.cleaned_data["name"]}.',
                )
            return redirect('projects:project_detail', pk=self.object.pk)
        messages.error(request, 'Please correct the errors below.')
        context = self.get_context_data()
        context['task_form'] = form
        return self.render_to_response(context)


@login_required
def task_set_status(request, pk):
    """POST: update task status from list (inline). Fields: status, next (optional relative URL)."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    task = get_object_or_404(Task, pk=pk, is_active=True)

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('projects:task_list')

    status = request.POST.get('status')
    valid_statuses = [c[0] for c in Task.STATUS_CHOICES]
    if status not in valid_statuses:
        messages.error(request, 'Invalid status.')
        return redirect('projects:task_list')

    if task.status != status:
        task.status = status
        task.save(update_fields=['status'])
        messages.success(request, f'Task status updated to {task.get_status_display()}.')

    next_url = request.POST.get('next', '').strip()
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('projects:task_list')


@login_required
def task_update_status(request, pk, status):
    task = get_object_or_404(Task, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit'):
        task.status = status
        task.save()
        messages.success(request, f'Task status updated to {task.get_status_display()}.')
    if task.project_id:
        return redirect('projects:project_detail', pk=task.project.pk)
    return redirect('projects:task_list')


# ============ PROJECT EXPENSE VIEWS ============

class ProjectExpenseListView(PermissionRequiredMixin, ListView):
    """List all project expenses with filters."""
    model = ProjectExpense
    template_name = 'projects/expense_list.html'
    context_object_name = 'expenses'
    module_name = 'projects'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = ProjectExpense.objects.filter(is_active=True).select_related(
            'project', 'vendor', 'approved_by', 'journal_entry', 'vendor_bill',
        )
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(expense_number__icontains=search) |
                Q(description__icontains=search) |
                Q(project__name__icontains=search)
            )
        
        project = self.request.GET.get('project')
        if project:
            queryset = queryset.filter(project_id=project)
        
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Project Expenses'
        context['projects'] = Project.objects.filter(is_active=True)
        context['status_choices'] = ProjectExpense.STATUS_CHOICES
        context['category_choices'] = ProjectExpense.CATEGORY_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'create')
        context['can_approve'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'edit')
        
        # Metrics
        all_expenses = ProjectExpense.objects.filter(is_active=True)
        context['total_expenses'] = all_expenses.count()
        context['total_amount'] = all_expenses.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
        context['pending_approval'] = all_expenses.filter(status='draft').count()
        context['posted_count'] = all_expenses.filter(status='posted').count()
        
        return context


class ProjectExpenseCreateView(CreatePermissionMixin, CreateView):
    """Create a new project expense."""
    model = ProjectExpense
    form_class = ProjectExpenseForm
    template_name = 'projects/expense_form.html'
    success_url = reverse_lazy('projects:expense_list')
    module_name = 'projects'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Project Expense'
        return context
    
    def get_initial(self):
        initial = super().get_initial()
        project_id = self.request.GET.get('project')
        if project_id:
            initial['project'] = project_id
        initial['expense_date'] = date.today()
        return initial
    
    def form_valid(self, form):
        messages.success(self.request, f'Project expense created: {form.instance.expense_number}')
        response = super().form_valid(form)
        expense = self.object
        link = reverse('projects:expense_detail', kwargs={'pk': expense.pk})
        mgr = expense.project.manager
        if mgr and mgr.pk != self.request.user.pk:
            notify_user(
                mgr,
                f'New project expense {expense.expense_number}',
                f'{expense.description} — AED {expense.total_amount} (pending approval).',
                link,
            )
        return response


class ProjectExpenseUpdateView(UpdatePermissionMixin, UpdateView):
    """Update a project expense."""
    model = ProjectExpense
    form_class = ProjectExpenseForm
    template_name = 'projects/expense_form.html'
    success_url = reverse_lazy('projects:expense_list')
    module_name = 'projects'
    
    def get_queryset(self):
        return ProjectExpense.objects.filter(status='draft')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Expense: {self.object.expense_number}'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Project expense updated: {form.instance.expense_number}')
        return super().form_valid(form)


class ProjectExpenseDetailView(PermissionRequiredMixin, DetailView):
    """View project expense detail."""
    model = ProjectExpense
    template_name = 'projects/expense_detail.html'
    context_object_name = 'expense'
    module_name = 'projects'
    permission_type = 'view'
    
    def get_queryset(self):
        return ProjectExpense.objects.select_related(
            'project', 'vendor', 'approved_by', 'expense_account', 'journal_entry', 'vendor_bill',
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Expense: {self.object.expense_number}'
        context['can_approve'] = (
            self.object.status == 'draft' and 
            (self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'edit'))
        )
        context['can_post'] = (
            self.object.status == 'approved' and 
            not self.object.posted and
            (self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'edit'))
        )
        
        if self.object.journal_entry:
            context['journal_lines'] = self.object.journal_entry.lines.all().select_related('account')
        
        return context


@login_required
def expense_approve(request, pk):
    """Approve a project expense."""
    expense = get_object_or_404(ProjectExpense, pk=pk, status='draft')
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('projects:expense_detail', pk=pk)
    
    expense.status = 'approved'
    expense.approved_by = request.user
    expense.approved_date = timezone.now()
    expense.save(update_fields=['status', 'approved_by', 'approved_date'])
    
    messages.success(request, f'Expense {expense.expense_number} approved.')
    link = reverse('projects:expense_detail', kwargs={'pk': expense.pk})
    if expense.created_by_id and expense.created_by_id != request.user.pk:
        notify_user(
            expense.created_by,
            f'Expense approved: {expense.expense_number}',
            f'Approved by {request.user.get_full_name() or request.user.username}.',
            link,
        )
    return redirect('projects:expense_detail', pk=pk)


@login_required
def expense_reject(request, pk):
    """Reject a project expense."""
    expense = get_object_or_404(ProjectExpense, pk=pk, status='draft')
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('projects:expense_detail', pk=pk)
    
    expense.status = 'rejected'
    expense.save(update_fields=['status'])
    
    messages.warning(request, f'Expense {expense.expense_number} rejected.')
    link = reverse('projects:expense_detail', kwargs={'pk': expense.pk})
    if expense.created_by_id and expense.created_by_id != request.user.pk:
        notify_user(
            expense.created_by,
            f'Expense rejected: {expense.expense_number}',
            f'Rejected by {request.user.get_full_name() or request.user.username}.',
            link,
        )
    return redirect('projects:expense_detail', pk=pk)


@login_required
def project_gatepass_delete(request, project_pk, pk):
    project = get_object_or_404(Project, pk=project_pk, is_active=True)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('projects:project_detail', pk=project_pk)
    gp = get_object_or_404(ProjectGatepass, pk=pk, project=project, is_active=True)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    gp.is_active = False
    gp.save()
    messages.success(request, 'Gate pass removed.')
    return redirect('projects:project_detail', pk=project_pk)


@login_required
def project_report_pdf(request, pk):
    """Printable project report (HTML for print/PDF), layout aligned with estimate PDF."""
    from apps.settings_app.models import CompanySettings

    project = get_object_or_404(
        Project.objects.select_related('customer', 'manager'),
        pk=pk,
        is_active=True,
    )
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('projects:project_detail', pk=pk)

    company = CompanySettings.get_settings()
    logo_absolute_url = ''
    if company.logo:
        logo_absolute_url = request.build_absolute_uri(company.logo.url)

    tasks = project.tasks.filter(is_active=True).select_related('assigned_to').order_by(
        'due_date', 'start_date', 'priority', 'name'
    )

    return render(
        request,
        'projects/project_report_pdf.html',
        {
            'project': project,
            'company': company,
            'logo_absolute_url': logo_absolute_url,
            'tasks': tasks,
            'page_title': f'Project report — {project.project_code}',
            'print_button_label': 'Print report',
        },
    )


@login_required
def expense_post_to_accounting(request, pk):
    """Post approved expense to accounting."""
    expense = get_object_or_404(ProjectExpense, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('projects:expense_detail', pk=pk)
    
    if expense.status != 'approved':
        messages.error(request, 'Only approved expenses can be posted to accounting.')
        return redirect('projects:expense_detail', pk=pk)
    
    if expense.posted:
        messages.warning(request, f'Expense {expense.expense_number} already posted.')
        return redirect('projects:expense_detail', pk=pk)
    
    try:
        journal = expense.post_to_accounting(user=request.user)
        messages.success(request, f'Expense {expense.expense_number} posted to accounting. Journal: {journal.entry_number}')
    except Exception as e:
        messages.error(request, f'Error posting to accounting: {str(e)}')
    
    return redirect('projects:expense_detail', pk=pk)

