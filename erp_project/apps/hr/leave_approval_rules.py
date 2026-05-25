"""Leave approval routing from Settings → Approval Configuration."""
from __future__ import annotations

from apps.core.utils import PermissionChecker
from apps.settings_app.models import ApprovalConfiguration


def get_leave_config():
    return ApprovalConfiguration.objects.filter(module='leave', is_active=True).first()


def manager_approver_for_employee(employee):
    """Department manager, or configured fallback when department has no manager."""
    dept = getattr(employee, 'department', None)
    if dept and dept.manager_id:
        return dept.manager
    config = get_leave_config()
    if config and config.manager_approver_id:
        return config.manager_approver
    return None


def hr_approver_user():
    """Final HR approver from configuration."""
    config = get_leave_config()
    if config and config.default_approver_id:
        return config.default_approver
    return None


def user_can_manager_approve(user, employee) -> bool:
    mgr = manager_approver_for_employee(employee)
    return bool(mgr and mgr.pk == user.pk)


def user_can_hr_approve(user) -> bool:
    configured = hr_approver_user()
    if configured and configured.pk == user.pk:
        return True
    if configured:
        return False
    return PermissionChecker.has_permission(user, 'hr', 'approve')


def user_can_act_on_leave_request(user, leave) -> bool:
    """True when user may approve/reject this request at its current workflow step."""
    if leave.status == 'pending_manager':
        return user_can_manager_approve(user, leave.employee)
    if leave.status == 'pending_hr':
        return user_can_hr_approve(user)
    return False


def annotate_leave_approval_actions(user, leave_requests):
    for leave in leave_requests:
        leave.show_approve_actions = user_can_act_on_leave_request(user, leave)
    return leave_requests
