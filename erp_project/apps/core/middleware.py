"""
Core middleware for the ERP system.
"""
import threading
from django.utils.deprecation import MiddlewareMixin

# Thread local storage for current user
_thread_locals = threading.local()


def get_current_user():
    """Get the current user from thread local storage."""
    return getattr(_thread_locals, 'user', None)


def get_current_request():
    """Get the current request from thread local storage."""
    return getattr(_thread_locals, 'request', None)


class AuditMiddleware(MiddlewareMixin):
    """
    Middleware to store the current user and request in thread local storage.
    This allows models to automatically track created_by and updated_by.
    """
    
    def process_request(self, request):
        _thread_locals.user = getattr(request, 'user', None)
        _thread_locals.request = request
    
    def process_response(self, request, response):
        # Clean up thread local storage
        if hasattr(_thread_locals, 'user'):
            del _thread_locals.user
        if hasattr(_thread_locals, 'request'):
            del _thread_locals.request
        return response


class MinimalNavMiddleware(MiddlewareMixin):
    """Restrict URLs when APP_MINIMAL_NAV is enabled."""

    def process_request(self, request):
        from django.conf import settings
        from django.contrib import messages
        from django.shortcuts import redirect

        from apps.core.nav_config import get_user_home_url, minimal_nav_enabled, path_allowed_in_minimal_nav

        if not minimal_nav_enabled():
            return None

        path = request.path
        user = getattr(request, 'user', None)
        is_superuser = bool(user and user.is_authenticated and user.is_superuser)

        if path_allowed_in_minimal_nav(path, is_superuser=is_superuser):
            return None

        if not user or not user.is_authenticated:
            return None

        messages.warning(request, 'This section is not available in the current app mode.')
        return redirect(get_user_home_url(request.user))


class PurchaseFeatureMiddleware(MiddlewareMixin):
    """Enforce Purchase submenu permissions when configured for a role."""

    def process_request(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect

        from apps.core.nav_config import get_user_home_url
        from apps.core.utils import PermissionChecker
        from apps.purchase.feature_permissions import (
            permission_type_for_request,
            purchase_feature_for_path,
        )

        path = request.path
        if not path.startswith('/purchase/'):
            return None

        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or user.is_superuser:
            return None

        feature = purchase_feature_for_path(path)
        if not feature or feature == 'dashboard':
            return None

        perm_type = permission_type_for_request(request.method, path)
        if PermissionChecker.has_feature_permission(user, 'purchase', feature, perm_type):
            return None

        messages.warning(request, 'You do not have permission to access this Purchase section.')
        return redirect(get_user_home_url(request.user))





