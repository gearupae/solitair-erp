"""Navigation visibility for minimal deployment mode."""
from django.conf import settings
from django.urls import reverse


def minimal_nav_enabled() -> bool:
    return bool(getattr(settings, 'APP_MINIMAL_NAV', False))


MINIMAL_NAV_ALLOWED_PREFIXES = (
    '/purchase/',
    '/service-request/',
    '/hr/employees/',
    '/hr/departments/',
    '/hr/designations/',
    '/account/',
    '/notifications/',
)

MINIMAL_NAV_ALLOWED_PATHS = (
    '/',
    '/login/',
    '/logout/',
)

# Modules shown in Settings → Roles → Permissions when APP_MINIMAL_NAV is on.
MINIMAL_NAV_MODULE_CODES = frozenset({
    'purchase',
    'service_request',
    'hr',
    'settings',
})


def minimal_nav_module_choices(module_choices):
    """Limit module pickers to the modules used in minimal deployment mode."""
    if not minimal_nav_enabled():
        return list(module_choices)
    return [(code, label) for code, label in module_choices if code in MINIMAL_NAV_MODULE_CODES]


def path_allowed_in_minimal_nav(path: str, *, is_superuser: bool = False) -> bool:
    if path.startswith('/static/') or path.startswith('/media/'):
        return True
    if path in MINIMAL_NAV_ALLOWED_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in MINIMAL_NAV_ALLOWED_PREFIXES):
        return True
    if is_superuser and path.startswith('/settings/'):
        return True
    if is_superuser and path.startswith('/admin/'):
        return True
    return False


def get_user_home_url(user) -> str:
    """First accessible page after login in minimal (or any) deployment."""
    if not user or not user.is_authenticated:
        return reverse('login')

    from apps.core.utils import PermissionChecker

    if user.is_superuser:
        return reverse('purchase:pr_list')

    purchase_destinations = [
        ('pr', 'purchase:pr_list'),
        ('po', 'purchase:po_list'),
        ('vendors', 'purchase:vendor_list'),
        ('grn', 'purchase:grn_list'),
        ('rfq', 'purchase:rfq_list'),
        ('bills', 'purchase:bill_list'),
        ('expense_claims', 'purchase:expenseclaim_list'),
        ('recurring_expenses', 'purchase:recurringexpense_list'),
    ]
    if PermissionChecker.has_permission(user, 'purchase', 'view'):
        for feature, url_name in purchase_destinations:
            if PermissionChecker.has_feature_permission(user, 'purchase', feature, 'view'):
                return reverse(url_name)

    if PermissionChecker.has_permission(user, 'service_request', 'view'):
        return reverse('service_request:sr_list')

    if PermissionChecker.has_permission(user, 'hr', 'view'):
        return reverse('hr:employee_list')

    if PermissionChecker.has_permission(user, 'settings', 'view'):
        return reverse('settings:user_list')

    return reverse('account:my_profile')
