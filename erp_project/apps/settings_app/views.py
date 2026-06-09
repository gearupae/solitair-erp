"""
Settings app views.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, View, TemplateView
from django.urls import reverse, reverse_lazy
from django.http import JsonResponse
from django.db.models import Prefetch

from .models import (
    Role,
    Permission,
    RolePermission,
    UserRole,
    UserProfile,
    CompanySettings,
    AuditLog,
    ModulePermission,
    ApprovalConfiguration,
    ApprovalConfigurationLevel,
    Company,
    EstimateTextTemplate,
    ItemSubGroupExpenseType,
)
from .forms import UserForm, RoleForm, CompanySettingsForm, CompanyForm
from apps.core.mixins import PermissionRequiredMixin
from apps.hr.models import Employee


class UserListView(PermissionRequiredMixin, ListView):
    """List all users."""
    model = User
    template_name = 'settings/user_list.html'
    context_object_name = 'users'
    module_name = 'settings'
    permission_type = 'view'
    
    def get_queryset(self):
        from apps.hr.user_provisioning import sync_pending_employees_to_users

        sync_pending_employees_to_users()
        return (
            User.objects.all()
            .prefetch_related(
                Prefetch(
                    'employee_profile',
                    queryset=Employee.objects.filter(is_active=True),
                ),
                'user_roles__role',
            )
            .order_by('-date_joined')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'User Management'
        context['roles'] = Role.objects.filter(is_active=True)
        return context


class UserCreateView(PermissionRequiredMixin, CreateView):
    """Create a new user."""
    model = User
    form_class = UserForm
    template_name = 'settings/user_form.html'
    success_url = reverse_lazy('settings:user_list')
    module_name = 'settings'
    permission_type = 'create'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create User'
        context['roles'] = Role.objects.filter(is_active=True)
        return context
    
    def form_valid(self, form):
        response = super().form_valid(form)
        # Create user profile
        UserProfile.objects.create(user=self.object)
        
        # Assign roles
        role_ids = self.request.POST.getlist('roles')
        for role_id in role_ids:
            UserRole.objects.create(user=self.object, role_id=role_id)
        
        messages.success(self.request, f'User {self.object.username} created successfully.')
        return response


class UserUpdateView(PermissionRequiredMixin, UpdateView):
    """Update an existing user."""
    model = User
    form_class = UserForm
    template_name = 'settings/user_form.html'
    success_url = reverse_lazy('settings:user_list')
    module_name = 'settings'
    permission_type = 'edit'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edit User'
        context['roles'] = Role.objects.filter(is_active=True)
        context['user_roles'] = self.object.user_roles.filter(is_active=True).values_list('role_id', flat=True)
        return context
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # Update roles
        UserRole.objects.filter(user=self.object).delete()
        role_ids = self.request.POST.getlist('roles')
        for role_id in role_ids:
            UserRole.objects.create(user=self.object, role_id=role_id)
        
        messages.success(self.request, f'User {self.object.username} updated successfully.')
        return response


@login_required
def toggle_user_status(request, pk):
    """Toggle user active status."""
    user = get_object_or_404(User, pk=pk)
    user.is_active = not user.is_active
    user.save()
    status = 'activated' if user.is_active else 'deactivated'
    messages.success(request, f'User {user.username} has been {status}.')
    return redirect('settings:user_list')


class RoleListView(PermissionRequiredMixin, ListView):
    """List all roles."""
    model = Role
    template_name = 'settings/role_list.html'
    context_object_name = 'roles'
    module_name = 'settings'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Role Management'
        return context


class RoleCreateView(PermissionRequiredMixin, CreateView):
    """Create a new role."""
    model = Role
    form_class = RoleForm
    template_name = 'settings/role_form.html'
    success_url = reverse_lazy('settings:role_list')
    module_name = 'settings'
    permission_type = 'create'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Role'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Role {form.instance.name} created successfully.')
        return super().form_valid(form)


class RoleUpdateView(PermissionRequiredMixin, UpdateView):
    """Update an existing role."""
    model = Role
    form_class = RoleForm
    template_name = 'settings/role_form.html'
    success_url = reverse_lazy('settings:role_list')
    module_name = 'settings'
    permission_type = 'edit'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edit Role'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Role {form.instance.name} updated successfully.')
        return super().form_valid(form)


class RolePermissionView(PermissionRequiredMixin, TemplateView):
    """Manage role permissions with module-based matrix."""
    template_name = 'settings/role_permissions.html'
    module_name = 'settings'
    permission_type = 'edit'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = get_object_or_404(Role, pk=self.kwargs['pk'])
        context['role'] = role
        context['title'] = f'Permissions for {role.name}'
        
        # Get all available modules
        context['modules'] = ModulePermission.MODULE_CHOICES
        
        # Get current permissions for this role
        current_permissions = {}
        for mp in role.module_permissions.all():
            current_permissions[mp.module] = {
                'view': mp.can_view,
                'create': mp.can_create,
                'edit': mp.can_edit,
                'delete': mp.can_delete,
            }
        context['current_permissions'] = current_permissions
        
        return context
    
    def post(self, request, *args, **kwargs):
        role = get_object_or_404(Role, pk=self.kwargs['pk'])
        
        # Clear existing module permissions
        ModulePermission.objects.filter(role=role).delete()
        
        # Add new permissions based on form data
        for module_code, module_name in ModulePermission.MODULE_CHOICES:
            can_view = request.POST.get(f'{module_code}_view') == 'on'
            can_create = request.POST.get(f'{module_code}_create') == 'on'
            can_edit = request.POST.get(f'{module_code}_edit') == 'on'
            can_delete = request.POST.get(f'{module_code}_delete') == 'on'
            
            # Only create if at least one permission is granted
            if any([can_view, can_create, can_edit, can_delete]):
                ModulePermission.objects.create(
                    role=role,
                    module=module_code,
                    can_view=can_view,
                    can_create=can_create,
                    can_edit=can_edit,
                    can_delete=can_delete,
                )
        
        messages.success(request, f'Permissions for {role.name} updated successfully.')
        return redirect('settings:role_list')


class CompanySettingsView(PermissionRequiredMixin, UpdateView):
    """Company settings view."""
    model = CompanySettings
    form_class = CompanySettingsForm
    template_name = 'settings/company_settings.html'
    success_url = reverse_lazy('settings:company')
    module_name = 'settings'
    permission_type = 'edit'
    
    def get_object(self):
        return CompanySettings.get_settings()
    
    def get_context_data(self, **kwargs):
        import json

        from django.core.serializers.json import DjangoJSONEncoder

        context = super().get_context_data(**kwargs)
        context['title'] = 'Company Settings'
        client_note_templates = list(
            EstimateTextTemplate.objects.filter(
                template_type=EstimateTextTemplate.CLIENT_NOTE,
            ).order_by('sort_order', 'name')
        )
        terms_templates = list(
            EstimateTextTemplate.objects.filter(
                template_type=EstimateTextTemplate.TERMS,
            ).order_by('sort_order', 'name')
        )
        context['client_note_templates'] = client_note_templates
        context['terms_templates'] = terms_templates
        context['client_note_templates_json'] = json.dumps(
            [
                {
                    'id': t.pk,
                    'name': t.name,
                    'body': t.body,
                    'is_default': t.is_default,
                    'is_active': t.is_active,
                    'sort_order': t.sort_order,
                }
                for t in client_note_templates
            ],
            cls=DjangoJSONEncoder,
        )
        context['terms_templates_json'] = json.dumps(
            [
                {
                    'id': t.pk,
                    'name': t.name,
                    'body': t.body,
                    'is_default': t.is_default,
                    'is_active': t.is_active,
                    'sort_order': t.sort_order,
                }
                for t in terms_templates
            ],
            cls=DjangoJSONEncoder,
        )
        from apps.inventory.utils import openai_key_status

        context['openai_key_status'] = openai_key_status()
        try:
            context['openai_key_masked'] = self.get_object().openai_api_key_masked()
        except Exception:
            context['openai_key_masked'] = ''
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('openai_key_action'):
            return self._handle_openai_key_post(request)
        if request.POST.get('estimate_template_action'):
            return self._handle_estimate_template_post(request)
        return super().post(request, *args, **kwargs)

    def _handle_openai_key_post(self, request):
        from django.core.exceptions import ImproperlyConfigured

        action = request.POST.get('openai_key_action')
        cs = CompanySettings.get_settings()
        redirect_url = f'{reverse("settings:company")}#openai-key-settings'

        if action == 'clear':
            cs.openai_api_key = ''
            cs.save(update_fields=['openai_api_key'])
            messages.success(request, 'OpenAI API key removed.')
            return redirect(redirect_url)

        raw_key = (request.POST.get('openai_api_key') or '').strip()
        if not raw_key:
            messages.warning(request, 'Enter an OpenAI API key, then click Save API Key.')
            return redirect(redirect_url)

        try:
            cs.set_openai_api_key(raw_key)
            cs.save(update_fields=['openai_api_key'])
        except ImproperlyConfigured as exc:
            messages.error(
                request,
                f'OpenAI key could not be saved: {exc} '
                'Ask your administrator to run pip install -r requirements.txt on the server.',
            )
            return redirect(redirect_url)
        except Exception as exc:
            messages.error(request, f'OpenAI API key could not be saved: {exc}')
            return redirect(redirect_url)

        messages.success(request, 'OpenAI API key saved for AI forecasting.')
        return redirect(redirect_url)

    def _handle_estimate_template_post(self, request):
        action = request.POST.get('estimate_template_action')
        template_type = request.POST.get('template_type')

        if template_type not in dict(EstimateTextTemplate.TEMPLATE_TYPE_CHOICES):
            messages.error(request, 'Invalid template type.')
            return redirect('settings:company')

        type_label = dict(EstimateTextTemplate.TEMPLATE_TYPE_CHOICES)[template_type]
        query_key = 'cn' if template_type == EstimateTextTemplate.CLIENT_NOTE else 'terms'

        if action == 'save':
            name = (request.POST.get('name') or '').strip()[:120]
            body = request.POST.get('body') or ''
            if not name:
                messages.error(request, f'Template name is required for {type_label.lower()}.')
                return redirect('settings:company')
            is_default = request.POST.get('is_default') == 'on'
            is_active = request.POST.get('is_active') == 'on'
            sort_order = int(request.POST.get('sort_order') or 0)
            template_id = request.POST.get('template_id') or ''
            if template_id:
                template = get_object_or_404(
                    EstimateTextTemplate,
                    pk=int(template_id),
                    template_type=template_type,
                )
                template.name = name
                template.body = body
                template.sort_order = sort_order
                template.is_active = is_active
                template.is_default = is_default
                template.save()
                messages.success(request, f'{type_label} template “{name}” saved.')
            else:
                if not sort_order:
                    sort_order = (
                        EstimateTextTemplate.objects.filter(template_type=template_type)
                        .order_by('-sort_order')
                        .values_list('sort_order', flat=True)
                        .first()
                        or 0
                    ) + 1
                template = EstimateTextTemplate.objects.create(
                    template_type=template_type,
                    name=name,
                    body=body,
                    is_default=is_default,
                    sort_order=sort_order,
                    is_active=is_active,
                )
                messages.success(request, f'{type_label} template “{name}” created.')
            return redirect(f'{reverse("settings:company")}?{query_key}={template.pk}#estimate-templates')
        elif action == 'delete' and request.POST.get('template_id'):
            template = get_object_or_404(
                EstimateTextTemplate,
                pk=int(request.POST['template_id']),
                template_type=template_type,
            )
            name = template.name
            template.delete()
            messages.success(request, f'{type_label} template “{name}” deleted.')
            return redirect(f'{reverse("settings:company")}#estimate-templates')
        else:
            messages.error(request, 'Invalid template request.')
        return redirect('settings:company')
    
    def form_valid(self, form):
        messages.success(self.request, 'Company settings updated successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Could not save company settings. Please check the form and try again.')
        return super().form_invalid(form)


class CompanyListView(PermissionRequiredMixin, ListView):
    model = Company
    template_name = 'settings/company_list.html'
    context_object_name = 'companies'
    module_name = 'settings'
    permission_type = 'view'

    def get_queryset(self):
        return Company.objects.all().order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Companies'
        return ctx


class CompanyCreateView(PermissionRequiredMixin, CreateView):
    model = Company
    form_class = CompanyForm
    template_name = 'settings/company_form.html'
    success_url = reverse_lazy('settings:company_list')
    module_name = 'settings'
    permission_type = 'create'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add Company'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Company created.')
        return super().form_valid(form)


class CompanyUpdateView(PermissionRequiredMixin, UpdateView):
    model = Company
    form_class = CompanyForm
    template_name = 'settings/company_form.html'
    success_url = reverse_lazy('settings:company_list')
    module_name = 'settings'
    permission_type = 'edit'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit Company: {self.object.name}'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Company updated.')
        return super().form_valid(form)


class AuditLogListView(PermissionRequiredMixin, ListView):
    """Audit log viewer - IFRS & UAE audit compliant."""
    model = AuditLog
    template_name = 'settings/audit_log.html'
    context_object_name = 'logs'
    paginate_by = 50
    module_name = 'settings'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = AuditLog.objects.all().select_related('user')
        
        # Filters
        action = self.request.GET.get('action')
        if action:
            queryset = queryset.filter(action=action)
        
        model = self.request.GET.get('model')
        if model:
            queryset = queryset.filter(model__icontains=model)
        
        user = self.request.GET.get('user')
        if user:
            queryset = queryset.filter(user__username__icontains=user)
        
        # Module filter (for Finance)
        module = self.request.GET.get('module')
        if module:
            if module == 'finance':
                queryset = queryset.filter(model__startswith='Finance.')
            else:
                queryset = queryset.filter(model__icontains=module)
        
        # Date range filters
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            queryset = queryset.filter(timestamp__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__date__lte=date_to)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Audit Log'
        context['action_choices'] = AuditLog.ACTION_CHOICES
        context['module_choices'] = [
            ('finance', 'Finance'),
            ('sales', 'Sales'),
            ('purchase', 'Purchase'),
            ('inventory', 'Inventory'),
            ('hr', 'HR'),
            ('settings', 'Settings'),
        ]
        return context


class ApprovalConfigurationView(PermissionRequiredMixin, TemplateView):
    """
    Configure approval workflows for Purchase Request, Inventory Request, Service Request,
    optional per-edit review for Sales Estimates and Projects.
    Single Level: one approver regardless of amount.
    Multi Level: sequential approvers based on value (AED).
    """
    template_name = 'settings/approval_configuration.html'
    module_name = 'settings'
    permission_type = 'edit'
    
    def get_context_data(self, **kwargs):
        from django.contrib.auth import get_user_model
        from apps.hr.user_provisioning import sync_pending_employees_to_users

        User = get_user_model()
        sync_pending_employees_to_users()

        context = super().get_context_data(**kwargs)
        context['title'] = 'Approval Configuration'
        context['module_choices'] = ApprovalConfiguration.MODULE_CHOICES
        context['approval_type_choices'] = ApprovalConfiguration.APPROVAL_TYPE_CHOICES
        context['users'] = (
            User.objects.filter(is_active=True)
            .order_by('first_name', 'last_name', 'username')
        )
        
        config_list = []
        for module_code, module_name in ApprovalConfiguration.MODULE_CHOICES:
            config = ApprovalConfiguration.objects.filter(module=module_code, is_active=True).first()
            levels = list(config.levels.all().order_by('order', 'amount_threshold')) if config else []
            config_list.append({
                'module_code': module_code,
                'module_name': module_name,
                'config': config,
                'levels': levels,
            })
        context['config_list'] = config_list
        
        return context
    
    def post(self, request, *args, **kwargs):
        module = request.POST.get('module')
        approval_type = request.POST.get('approval_type')
        default_approver_id = request.POST.get('default_approver') or None
        manager_approver_id = request.POST.get('manager_approver') or None
        
        if module not in dict(ApprovalConfiguration.MODULE_CHOICES):
            messages.error(request, 'Invalid module selected.')
            return redirect('settings:approval_configuration')

        if module == 'leave':
            approval_type = 'multi'
        
        defaults = {
            'approval_type': approval_type or 'single',
            'default_approver_id': default_approver_id if default_approver_id else None,
        }
        if module == 'leave':
            defaults['manager_approver_id'] = manager_approver_id if manager_approver_id else None

        config, _ = ApprovalConfiguration.objects.update_or_create(
            module=module,
            defaults=defaults,
        )
        
        # Multi-level: save levels (amount-based modules only; leave uses manager_approver + default_approver)
        if approval_type == 'multi' and module != 'leave':
            # Remove existing levels
            config.levels.all().delete()
            
            # Parse level data from POST (levels-0-amount, levels-0-approver, etc.)
            level_idx = 0
            while True:
                amount = request.POST.get(f'levels-{level_idx}-amount')
                approver_id = request.POST.get(f'levels-{level_idx}-approver')
                if amount is None:
                    break
                try:
                    amount_val = float(amount) if amount else 0
                    if amount_val > 0 and approver_id:
                        ApprovalConfigurationLevel.objects.create(
                            configuration=config,
                            amount_threshold=amount_val,
                            approver_id=approver_id,
                            order=level_idx
                        )
                except (ValueError, TypeError):
                    pass
                level_idx += 1
        
        messages.success(request, f'Approval configuration for {dict(ApprovalConfiguration.MODULE_CHOICES).get(module, module)} saved.')
        return redirect('settings:approval_configuration')


class CrmKanbanSettingsView(PermissionRequiredMixin, TemplateView):
    """Configure CRM lead pipeline columns (hot / warm / cold / won, etc.)."""

    template_name = 'settings/crm_kanban_stages.html'
    module_name = 'settings'
    permission_type = 'edit'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.crm.models import CrmLeadKanbanStage

        ctx['title'] = 'CRM lead pipeline (Kanban)'
        ctx['stages'] = CrmLeadKanbanStage.objects.all().order_by('sort_order', 'id')
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.crm.models import CrmLeadKanbanStage

        action = request.POST.get('action')
        if action == 'add':
            name = (request.POST.get('name') or '').strip()[:80]
            if not name:
                messages.error(request, 'Stage name is required.')
                return redirect('settings:crm_kanban')
            sort_order = int(request.POST.get('sort_order') or 0)
            CrmLeadKanbanStage.objects.create(name=name, sort_order=sort_order)
            messages.success(request, 'Stage added.')
        elif action == 'save' and request.POST.get('stage_id'):
            s = get_object_or_404(CrmLeadKanbanStage, pk=int(request.POST['stage_id']))
            s.name = (request.POST.get('name') or '').strip()[:80] or s.name
            s.sort_order = int(request.POST.get('sort_order') or 0)
            s.is_active = request.POST.get('is_active') == 'on'
            s.converts_to_customer = request.POST.get('converts_to_customer') == 'on'
            s.save()
            messages.success(request, f'Stage “{s.name}” saved.')
        elif action == 'delete' and request.POST.get('stage_id'):
            s = get_object_or_404(CrmLeadKanbanStage, pk=int(request.POST['stage_id']))
            nm = s.name
            s.delete()
            messages.success(request, f'Stage “{nm}” deleted.')
        else:
            messages.error(request, 'Invalid request.')
        return redirect('settings:crm_kanban')


class SubGroupExpenseTypeSettingsView(PermissionRequiredMixin, TemplateView):
    """Configure expense type options used on inventory sub-groups."""

    template_name = 'settings/sub_group_expense_types.html'
    module_name = 'settings'
    permission_type = 'edit'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Expense types'
        ctx['expense_types'] = ItemSubGroupExpenseType.objects.all().order_by('sort_order', 'name')
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')

        if action == 'add':
            name = (request.POST.get('name') or '').strip()[:120]
            if not name:
                messages.error(request, 'Expense type name is required.')
                return redirect('settings:sub_group_expense_types')
            if ItemSubGroupExpenseType.objects.filter(name__iexact=name).exists():
                messages.error(request, 'An expense type with that name already exists.')
                return redirect('settings:sub_group_expense_types')
            sort_order = int(request.POST.get('sort_order') or 0)
            if not sort_order:
                sort_order = (
                    ItemSubGroupExpenseType.objects.order_by('-sort_order')
                    .values_list('sort_order', flat=True)
                    .first()
                    or 0
                ) + 1
            ItemSubGroupExpenseType.objects.create(name=name, sort_order=sort_order)
            messages.success(request, f'Expense type “{name}” added.')

        elif action == 'save' and request.POST.get('type_id'):
            row = get_object_or_404(ItemSubGroupExpenseType, pk=int(request.POST['type_id']))
            name = (request.POST.get('name') or '').strip()[:120]
            if not name:
                messages.error(request, 'Expense type name is required.')
                return redirect('settings:sub_group_expense_types')
            if ItemSubGroupExpenseType.objects.filter(name__iexact=name).exclude(pk=row.pk).exists():
                messages.error(request, 'Another expense type already uses that name.')
                return redirect('settings:sub_group_expense_types')
            row.name = name
            row.sort_order = int(request.POST.get('sort_order') or 0)
            row.is_active = request.POST.get('is_active') == 'on'
            row.save()
            messages.success(request, f'Expense type “{row.name}” saved.')

        elif action == 'delete' and request.POST.get('type_id'):
            row = get_object_or_404(ItemSubGroupExpenseType, pk=int(request.POST['type_id']))
            name = row.name
            row.delete()
            messages.success(request, f'Expense type “{name}” deleted.')

        else:
            messages.error(request, 'Invalid request.')

        return redirect('settings:sub_group_expense_types')

