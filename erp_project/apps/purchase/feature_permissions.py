"""Purchase submenu feature permissions."""

PURCHASE_FEATURES = [
    ('vendors', 'Vendors'),
    ('pr', 'Purchase Requests'),
    ('po', 'Purchase Orders'),
    ('grn', 'Goods Receipt Notes'),
    ('rfq', 'RFQ / Competitive Analysis'),
    ('bills', 'Vendor Bills'),
    ('expense_claims', 'Expense Claims'),
    ('recurring_expenses', 'Recurring Expenses'),
]

PURCHASE_FEATURE_CODES = frozenset(code for code, _ in PURCHASE_FEATURES)

# Longest prefix first when matching URLs.
PURCHASE_PATH_FEATURES = [
    ('/purchase/vendors', 'vendors'),
    ('/purchase/requests', 'pr'),
    ('/purchase/orders', 'po'),
    ('/purchase/grn', 'grn'),
    ('/purchase/rfq', 'rfq'),
    ('/purchase/bills', 'bills'),
    ('/purchase/expense-claims', 'expense_claims'),
    ('/purchase/recurring-expenses', 'recurring_expenses'),
    ('/purchase/dashboard', 'dashboard'),
]


def purchase_feature_for_path(path: str) -> str | None:
    for prefix, feature in PURCHASE_PATH_FEATURES:
        if path.startswith(prefix):
            return feature
    return None


def permission_type_for_request(method: str, path: str) -> str:
    # Read-only analysis endpoints use view permission (e.g. approvers without edit).
    if '/ai-evaluate/' in path or '/vendor-quotes/analyze/' in path:
        return 'view'
    if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if '/create/' in path or path.endswith('/create'):
            return 'create'
        if any(token in path for token in ('/delete/', '/cancel/')):
            return 'delete'
        if '/edit/' in path:
            return 'edit'
        if any(
            token in path
            for token in (
                '/approve/', '/reject/', '/submit/', '/confirm/', '/post/',
                '/pay/', '/receive/', '/convert/', '/award/', '/return/',
                '/execute/', '/pause/', '/resume/', '/send-email/',
            )
        ):
            return 'edit'
        return 'edit'
    if '/create/' in path:
        return 'create'
    if '/edit/' in path:
        return 'edit'
    return 'view'


def get_user_purchase_feature_access(user) -> dict:
    """Feature code -> {view, create, edit, delete} for templates."""
    from apps.core.utils import PermissionChecker

    access = {}
    for code, _ in PURCHASE_FEATURES:
        access[code] = {
            'view': PermissionChecker.has_feature_permission(user, 'purchase', code, 'view'),
            'create': PermissionChecker.has_feature_permission(user, 'purchase', code, 'create'),
            'edit': PermissionChecker.has_feature_permission(user, 'purchase', code, 'edit'),
            'delete': PermissionChecker.has_feature_permission(user, 'purchase', code, 'delete'),
        }
    return access
