"""
View mixins for the ERP system.
"""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.shortcuts import redirect
from apps.core.utils import PermissionChecker


class PermissionRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin to check module-level permissions.
    
    Usage:
        class MyView(PermissionRequiredMixin, ListView):
            module_name = 'crm'
            permission_type = 'view'
    """
    module_name = None
    permission_type = 'view'
    
    def test_func(self):
        if self.request.user.is_superuser:
            return True
        
        if not self.module_name:
            return True
            
        return PermissionChecker.has_permission(
            self.request.user,
            self.module_name,
            self.permission_type
        )
    
    def handle_no_permission(self):
        messages.error(self.request, 'You do not have permission to access this page.')
        return redirect('dashboard')


class CreatePermissionMixin(PermissionRequiredMixin):
    """Mixin for create views."""
    permission_type = 'create'


class UpdatePermissionMixin(PermissionRequiredMixin):
    """Mixin for update views."""
    permission_type = 'edit'


class DeletePermissionMixin(PermissionRequiredMixin):
    """Mixin for delete views."""
    permission_type = 'delete'


class ApprovePermissionMixin(PermissionRequiredMixin):
    """Mixin for approve views."""
    permission_type = 'approve'





