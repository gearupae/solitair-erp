"""
Settings app views.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, View, TemplateView
from django.urls import reverse_lazy
from django.http import JsonResponse
from .models import (
    Role, Permission, RolePermission, UserRole, UserProfile, CompanySettings, AuditLog, ModulePermission,
    ApprovalConfiguration, ApprovalConfigurationLevel
)
from .forms import UserForm, RoleForm, CompanySettingsForm
from apps.core.mixins import PermissionRequiredMixin


class UserListView(PermissionRequiredMixin, ListView):
    """List all users."""
    model = User
    template_name = 'settings/user_list.html'
    context_object_name = 'users'
    module_name = 'settings'
    permission_type = 'view'
    
    def get_queryset(self):
        return User.objects.all().order_by('-date_joined')
    
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
        context = super().get_context_data(**kwargs)
        context['title'] = 'Company Settings'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, 'Company settings updated successfully.')
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
    Configure approval workflows for Purchase Request, Inventory Request, Service Request.
    Single Level: one approver regardless of amount.
    Multi Level: sequential approvers based on value (AED).
    """
    template_name = 'settings/approval_configuration.html'
    module_name = 'settings'
    permission_type = 'edit'
    
    def get_context_data(self, **kwargs):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        context = super().get_context_data(**kwargs)
        context['title'] = 'Approval Configuration'
        context['module_choices'] = ApprovalConfiguration.MODULE_CHOICES
        context['approval_type_choices'] = ApprovalConfiguration.APPROVAL_TYPE_CHOICES
        context['users'] = User.objects.filter(is_active=True).order_by('username')
        
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
        
        if module not in dict(ApprovalConfiguration.MODULE_CHOICES):
            messages.error(request, 'Invalid module selected.')
            return redirect('settings:approval_configuration')
        
        config, _ = ApprovalConfiguration.objects.update_or_create(
            module=module,
            defaults={
                'approval_type': approval_type or 'single',
                'default_approver_id': default_approver_id if default_approver_id else None,
            }
        )
        
        # Multi-level: save levels
        if approval_type == 'multi':
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

