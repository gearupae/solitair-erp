"""Projects Views"""
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseNotAllowed
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse, reverse_lazy
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import date
from decimal import Decimal
from .models import Project, Task, Timesheet, ProjectExpense
from .forms import ProjectForm, TaskForm, TimesheetForm, ProjectExpenseForm
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.notification_utils import notify_if_new_assignee, notify_user
from apps.core.utils import PermissionChecker


class ProjectListView(PermissionRequiredMixin, ListView):
    model = Project
    template_name = 'projects/project_list.html'
    context_object_name = 'projects'
    module_name = 'projects'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = Project.objects.filter(is_active=True).select_related('customer', 'manager')
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(project_code__icontains=search))
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Projects'
        context['status_choices'] = Project.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'edit')
        
        # Calculate metrics
        all_projects = Project.objects.filter(is_active=True)
        context['total_projects'] = all_projects.count()
        context['in_progress_projects'] = all_projects.filter(status='in_progress').count()
        context['completed_projects'] = all_projects.filter(status='completed').count()
        
        return context


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
        qs = Task.objects.filter(is_active=True).select_related('project', 'assigned_to').order_by(
            'due_date', 'start_date', 'project__project_code', 'name'
        )
        search = self.request.GET.get('search')
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(project__name__icontains=search)
                | Q(project__project_code__icontains=search)
            )
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        project_id = self.request.GET.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
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
        context['assignable_users'] = User.objects.filter(is_active=True).order_by(
            'first_name', 'last_name', 'username'
        )
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
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Project: {self.object.name}'
        return context


class ProjectDetailView(PermissionRequiredMixin, DetailView):
    model = Project
    template_name = 'projects/project_detail.html'
    context_object_name = 'project'
    module_name = 'projects'
    permission_type = 'view'

    def get_queryset(self):
        return Project.objects.select_related('customer', 'manager').prefetch_related('members')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Project: {self.object.name}'
        context['tasks'] = self.object.tasks.filter(is_active=True).select_related('assigned_to')
        # Initialize form if not already in context (from POST with errors)
        if 'task_form' not in context:
            context['task_form'] = TaskForm()
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'edit')
        pe = self.object.project_expenses.filter(is_active=True).exclude(status='rejected')
        agg = pe.aggregate(s=Sum('total_amount'), c=Count('id'))
        context['recorded_expenses_total'] = agg['s'] if agg['s'] is not None else Decimal('0.00')
        context['has_recorded_expenses'] = (agg['c'] or 0) > 0
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'create')):
            messages.error(request, 'Permission denied.')
            return redirect('projects:project_detail', pk=self.object.pk)
        
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.project = self.object
            task.save()
            messages.success(request, f'Task {task.name} created.')
            link = reverse('projects:project_detail', kwargs={'pk': self.object.pk})
            notify_if_new_assignee(
                task.assigned_to,
                request.user,
                f'Task assigned: {task.name}',
                f'{self.object.project_code} — {task.name}',
                link,
            )
            return redirect('projects:project_detail', pk=self.object.pk)
        else:
            # Form has errors, re-render with errors
            messages.error(request, 'Please correct the errors below.')
            context = self.get_context_data()
            context['task_form'] = form
            return self.render_to_response(context)


class TimesheetListView(PermissionRequiredMixin, ListView):
    model = Timesheet
    template_name = 'projects/timesheet_list.html'
    context_object_name = 'timesheets'
    module_name = 'projects'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Timesheet.objects.filter(is_active=True).select_related('task', 'task__project', 'user')
        if not self.request.user.is_superuser:
            queryset = queryset.filter(user=self.request.user)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Timesheets'
        context['form'] = TimesheetForm()
        context['total_hours'] = self.get_queryset().aggregate(Sum('hours'))['hours__sum'] or 0
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'projects', 'create')
        return context
    
    def post(self, request, *args, **kwargs):
        form = TimesheetForm(request.POST)
        if form.is_valid():
            timesheet = form.save(commit=False)
            timesheet.user = request.user
            timesheet.save()
            messages.success(request, 'Timesheet entry added.')
        return redirect('projects:timesheet_list')


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
    return redirect('projects:project_detail', pk=task.project.pk)


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
            'project', 'vendor', 'approved_by', 'journal_entry'
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
            'project', 'vendor', 'approved_by', 'expense_account', 'journal_entry'
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

