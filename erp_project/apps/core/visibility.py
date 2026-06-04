"""Record-level data visibility for scoped modules."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.settings_app.models import UserRole

User = get_user_model()

SCOPED_MODULES = frozenset({'crm', 'sales', 'projects', 'purchase'})
ELEVATED_ROLE_CODES = frozenset({'super_admin', 'admin', 'manager'})


def get_user_role_codes(user):
    if not user or not user.is_authenticated:
        return frozenset()
    if user.is_superuser:
        return frozenset({'superuser'})
    return frozenset(
        UserRole.objects.filter(user=user, is_active=True).values_list('role__code', flat=True)
    )


def user_has_elevated_data_access(user):
    """Superusers and admin roles see all records in scoped modules."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    codes = get_user_role_codes(user)
    if ELEVATED_ROLE_CODES & codes:
        return True
    from apps.settings_app.models import Role

    return Role.objects.filter(
        code__in=codes,
        is_active=True,
        is_system_role=True,
    ).exists()


def crm_show_my_leads_label(user):
    """Sales users with scoped CRM access see 'My Leads' instead of 'CRM' in the nav."""
    if not user_data_scope_restricted(user, 'crm'):
        return False
    return 'sales' in get_user_role_codes(user)


def user_data_scope_restricted(user, module):
    """True when the user should only see own/assigned records in this module."""
    if not user or not user.is_authenticated:
        return True
    if module not in SCOPED_MODULES:
        return False
    return not user_has_elevated_data_access(user)


def filter_customers_for_user(queryset, user):
    if not user_data_scope_restricted(user, 'crm'):
        return queryset
    return queryset.filter(Q(created_by=user) | Q(assigned_salesperson__user=user))


def user_can_access_customer(user, customer):
    if not customer:
        return False
    if not user_data_scope_restricted(user, 'crm'):
        return True
    if customer.created_by_id == user.id:
        return True
    sp = customer.assigned_salesperson
    return sp is not None and sp.user_id == user.id


def filter_estimates_for_user(queryset, user):
    if not user_data_scope_restricted(user, 'sales'):
        return queryset
    from apps.core.approval_visibility import estimate_approver_records_q

    own_q = Q(created_by=user) | Q(assigned_to=user)
    return queryset.filter(own_q | estimate_approver_records_q(user))


def user_can_access_estimate(user, estimate):
    if not estimate:
        return False
    if not user_data_scope_restricted(user, 'sales'):
        return True
    if estimate.created_by_id == user.id or estimate.assigned_to_id == user.id:
        return True
    from apps.core.approval_visibility import user_is_estimate_approver_for

    return user_is_estimate_approver_for(user, estimate)


def filter_projects_for_user(queryset, user):
    if not user_data_scope_restricted(user, 'projects'):
        return queryset
    from apps.core.approval_visibility import (
        annotate_project_approval_amount,
        project_approver_records_q,
        project_conversion_approver_records_q,
    )

    own_q = Q(created_by=user) | Q(manager=user) | Q(members=user) | Q(technicians=user)
    qs = annotate_project_approval_amount(queryset)
    return qs.filter(
        own_q | project_approver_records_q(user) | project_conversion_approver_records_q(user)
    ).distinct()


def user_can_access_project(user, project):
    if not project:
        return False
    if not user_data_scope_restricted(user, 'projects'):
        return True
    if project.created_by_id == user.id or project.manager_id == user.id:
        return True
    if project.members.filter(pk=user.pk).exists() or project.technicians.filter(pk=user.pk).exists():
        return True
    from apps.core.approval_visibility import (
        user_is_project_approver_for,
        user_is_project_conversion_approver_for,
    )

    return (
        user_is_project_approver_for(user, project)
        or user_is_project_conversion_approver_for(user, project)
    )


def filter_purchase_requests_for_user(queryset, user):
    if not user_data_scope_restricted(user, 'purchase'):
        return queryset
    from apps.core.approval_visibility import purchase_request_approver_records_q

    own_q = Q(created_by=user) | Q(requested_by=user)
    return queryset.filter(own_q | purchase_request_approver_records_q(user))


def user_can_access_purchase_request(user, purchase_request):
    if not purchase_request:
        return False
    if not user_data_scope_restricted(user, 'purchase'):
        return True
    if purchase_request.created_by_id == user.id or purchase_request.requested_by_id == user.id:
        return True
    from apps.core.approval_visibility import user_is_purchase_request_approver_for

    return user_is_purchase_request_approver_for(user, purchase_request)


def filter_purchase_orders_for_user(queryset, user):
    if not user_data_scope_restricted(user, 'purchase'):
        return queryset
    return queryset.filter(
        Q(created_by=user) | Q(purchase_request__requested_by=user)
    )


def user_can_access_purchase_order(user, purchase_order):
    if not purchase_order:
        return False
    if not user_data_scope_restricted(user, 'purchase'):
        return True
    if purchase_order.created_by_id == user.id:
        return True
    pr = purchase_order.purchase_request
    return pr is not None and pr.requested_by_id == user.id
