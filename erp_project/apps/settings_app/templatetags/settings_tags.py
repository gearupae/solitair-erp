"""
Custom template tags for settings app.
"""
from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a variable key."""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def has_perm(user, perm_string):
    """
    Check if user has a specific permission.
    Usage: {% if user|has_perm:'crm:view' %}
    """
    if not user or not user.is_authenticated:
        return False
    
    if user.is_superuser:
        return True
    
    from apps.core.utils import PermissionChecker
    
    if ':' in perm_string:
        module, perm_type = perm_string.split(':')
        return PermissionChecker.has_permission(user, module, perm_type)
    
    return False


@register.simple_tag
def user_can(user, module, permission_type):
    """
    Check if user has permission.
    Usage: {% user_can user 'crm' 'view' as can_view %}
    """
    if not user or not user.is_authenticated:
        return False
    
    if user.is_superuser:
        return True
    
    from apps.core.utils import PermissionChecker
    return PermissionChecker.has_permission(user, module, permission_type)





