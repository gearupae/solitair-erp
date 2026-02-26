"""
Utility functions for the ERP system.
"""
from django.conf import settings
from datetime import datetime


def generate_number(document_type, model_class, number_field='number', year=None):
    """
    Generate a sequential number for documents.
    Format: PREFIX-YEAR-NUMBER (e.g., INV-2025-0001)
    
    Fiscal integrity: When year is provided (e.g. from entry date), use it so
    document number matches the transaction period. Never use current year for
    backdated entries.
    
    Args:
        document_type: Key from NUMBER_SERIES settings (e.g., 'INVOICE')
        model_class: The model class to query for existing numbers
        number_field: The field name that stores the number
        year: Optional year for the number (e.g. from entry date). If None, uses current year.
    
    Returns:
        str: Generated number
    """
    config = settings.NUMBER_SERIES.get(document_type, {})
    prefix = config.get('prefix', 'DOC')
    padding = config.get('padding', 4)
    
    year = year if year is not None else datetime.now().year
    year_prefix = f"{prefix}-{year}-"
    
    # Get the last number for this year
    filter_kwargs = {f'{number_field}__startswith': year_prefix}
    last_record = model_class.objects.filter(**filter_kwargs).order_by(f'-{number_field}').first()
    
    if last_record:
        last_number = getattr(last_record, number_field)
        try:
            last_seq = int(last_number.split('-')[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0
    
    new_seq = last_seq + 1
    return f"{year_prefix}{str(new_seq).zfill(padding)}"


def get_client_ip(request):
    """Get the client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


class PermissionChecker:
    """
    Utility class to check user permissions.
    Uses the new ModulePermission model for cleaner permission management.
    """
    
    @staticmethod
    def has_permission(user, module, permission_type):
        """
        Check if user has a specific permission.
        
        Args:
            user: User object
            module: Module name (e.g., 'crm', 'sales')
            permission_type: Permission type (view, create, edit, delete)
        
        Returns:
            bool: True if user has permission
        """
        if not user or not user.is_authenticated:
            return False
        
        if user.is_superuser:
            return True
        
        # Check user roles and module permissions
        from apps.settings_app.models import UserRole, ModulePermission
        
        user_roles = UserRole.objects.filter(user=user, is_active=True).values_list('role_id', flat=True)
        
        # Map permission types to model fields
        permission_field = f'can_{permission_type}'
        
        return ModulePermission.objects.filter(
            role_id__in=user_roles,
            module__iexact=module,
            **{permission_field: True}
        ).exists()
    
    @staticmethod
    def get_user_permissions(user):
        """
        Get all permissions for a user.
        
        Returns:
            dict: Dictionary of module -> permission_types list
        """
        if not user or not user.is_authenticated:
            return {}
        
        if user.is_superuser:
            return {'all': ['view', 'create', 'edit', 'delete']}
        
        from apps.settings_app.models import UserRole, ModulePermission
        
        user_roles = UserRole.objects.filter(user=user, is_active=True).values_list('role_id', flat=True)
        
        module_permissions = ModulePermission.objects.filter(role_id__in=user_roles)
        
        permissions = {}
        for mp in module_permissions:
            module = mp.module.lower()
            if module not in permissions:
                permissions[module] = []
            
            if mp.can_view and 'view' not in permissions[module]:
                permissions[module].append('view')
            if mp.can_create and 'create' not in permissions[module]:
                permissions[module].append('create')
            if mp.can_edit and 'edit' not in permissions[module]:
                permissions[module].append('edit')
            if mp.can_delete and 'delete' not in permissions[module]:
                permissions[module].append('delete')
        
        return permissions
    
    @staticmethod
    def get_module_permissions(user, module):
        """
        Get specific module permissions for a user.
        
        Returns:
            dict: Dictionary with view, create, edit, delete boolean values
        """
        if not user or not user.is_authenticated:
            return {'view': False, 'create': False, 'edit': False, 'delete': False}
        
        if user.is_superuser:
            return {'view': True, 'create': True, 'edit': True, 'delete': True}
        
        from apps.settings_app.models import UserRole, ModulePermission
        
        user_roles = UserRole.objects.filter(user=user, is_active=True).values_list('role_id', flat=True)
        
        permissions = {'view': False, 'create': False, 'edit': False, 'delete': False}
        
        module_perms = ModulePermission.objects.filter(
            role_id__in=user_roles,
            module__iexact=module
        )
        
        for mp in module_perms:
            if mp.can_view:
                permissions['view'] = True
            if mp.can_create:
                permissions['create'] = True
            if mp.can_edit:
                permissions['edit'] = True
            if mp.can_delete:
                permissions['delete'] = True
        
        return permissions

