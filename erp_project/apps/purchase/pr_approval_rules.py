"""Purchase request approval routing and post-approval workflow rules."""
from __future__ import annotations

from apps.core.utils import PermissionChecker
from apps.settings_app.models import ApprovalConfiguration


def user_is_any_pr_approver(user) -> bool:
    """True if user is a configured purchase-request approver (any level)."""
    if not user or not user.is_authenticated:
        return False
    config = ApprovalConfiguration.objects.filter(module='purchase_request', is_active=True).first()
    if not config:
        return False
    if config.default_approver_id == user.pk:
        return True
    return config.levels.filter(is_active=True, approver_id=user.pk).exists()


def user_is_pr_approver_portal(user) -> bool:
    """
    Approval-only PR access: configured approver without full purchase module view.
    Superusers keep the full purchase workspace.
    """
    if not user_is_any_pr_approver(user):
        return False
    if user.is_superuser:
        return False
    return not PermissionChecker.has_permission(user, 'purchase', 'view')


def user_can_view_purchase_requests(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if PermissionChecker.has_permission(user, 'purchase', 'view'):
        return True
    return user_is_any_pr_approver(user)


def get_configured_pr_approver(pr):
    """Configured approver for this PR amount — no superuser fallback."""
    config = ApprovalConfiguration.objects.filter(module='purchase_request', is_active=True).first()
    if not config:
        return None
    amount = pr.total_amount or 0
    if config.approval_type == 'single':
        return config.default_approver
    level = (
        config.levels.filter(is_active=True)
        .order_by('amount_threshold')
        .filter(amount_threshold__gte=amount)
        .first()
    )
    if not level:
        level = config.levels.filter(is_active=True).order_by('-amount_threshold').first()
    return (level.approver if level else None) or config.default_approver


def user_is_pr_requester(user, pr) -> bool:
    return bool(user and user.is_authenticated and pr.requested_by_id == user.id)


PROCUREMENT_DEPT_KEYWORDS = ('procurement', 'procure', 'proc')


def user_is_procurement_department_member(user) -> bool:
    """True when the user's employee profile is in the procurement department."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    emp = getattr(user, 'employee_profile', None)
    dept = getattr(emp, 'department', None) if emp else None
    if not dept:
        return False
    blob = f'{(dept.name or "").lower()} {(dept.code or "").lower()}'
    return any(k in blob for k in PROCUREMENT_DEPT_KEYWORDS)


def _get_procurement_department():
    from apps.hr.models import Department
    from django.db.models import Q

    return (
        Department.objects.filter(is_active=True)
        .filter(
            Q(code__iexact='PROC')
            | Q(name__icontains='procurement')
            | Q(code__icontains='proc')
        )
        .first()
    )


def user_is_procurement_department_admin(user) -> bool:
    """Manager of the procurement department (HR → Departments)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    dept = _get_procurement_department()
    return bool(dept and dept.manager_id == user.pk)


def user_is_procurement_staff(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return PermissionChecker.has_permission(user, 'purchase', 'edit')


def user_can_edit_pr(user, pr) -> bool:
    """Edit PR — requester while draft/returned; procurement department admin may assist."""
    if not user or not user.is_authenticated:
        return False
    if pr.status not in ('draft', 'returned'):
        return False
    if user_is_procurement_department_admin(user):
        return True
    if user_is_pr_requester(user, pr):
        return True
    return False


def user_can_delete_pr(user, pr) -> bool:
    """Cancel/delete — blocked once approved or in procurement workflow."""
    if not user or not user.is_authenticated:
        return False
    if pr.status in ('approved', 'converted', 'pending'):
        return False
    if user_is_procurement_staff(user):
        return PermissionChecker.has_permission(user, 'purchase', 'delete')
    if user_is_pr_requester(user, pr):
        return pr.status in ('draft', 'returned')
    return user.is_superuser and pr.status in ('draft', 'returned', 'rejected')


def user_can_procurement_return_pr(user, pr) -> bool:
    """Only procurement department may send an approved PR back to the requester."""
    return pr.status == 'approved' and user_is_procurement_department_member(user)


def user_can_convert_pr_to_po(user, pr) -> bool:
    """Procurement converts approved PRs to PO after entering vendor, prices, and quotes."""
    if not user or not pr or pr.status != 'approved':
        return False
    if user.is_superuser:
        return True
    if not user_is_procurement_department_member(user):
        return False
    return PermissionChecker.has_permission(user, 'purchase', 'create')


def user_can_act_on_purchase_request(user, pr) -> bool:
    """True when user may approve, reject, or return this pending PR."""
    if not user or not user.is_authenticated:
        return False
    if pr.status != 'pending':
        return False
    approver = get_configured_pr_approver(pr)
    if approver is not None:
        return approver.pk == user.pk
    return user.is_superuser


def annotate_pr_approval_actions(user, purchase_requests):
    for pr in purchase_requests:
        pr.show_approve_actions = user_can_act_on_purchase_request(user, pr)
        pr.user_can_edit = user_can_edit_pr(user, pr)
        pr.user_can_delete = user_can_delete_pr(user, pr)
    return purchase_requests
