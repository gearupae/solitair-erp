"""Two-step approval: department manager → HR."""
from __future__ import annotations

from django.utils import timezone

from apps.core.utils import PermissionChecker
from apps.hr import hr_notifications
from apps.hr.leave_balance_service import sync_leave_balances_for_employee


def _is_department_manager(user, employee) -> bool:
    dept = getattr(employee, 'department', None)
    if not dept or not dept.manager_id:
        return False
    return dept.manager_id == user.pk


def approve_leave_request(request, leave) -> tuple[bool, str]:
    """Return (success, message)."""
    user = request.user
    emp = leave.employee

    if leave.status == 'pending_manager':
        if not (_is_department_manager(user, emp) or user.is_superuser):
            return False, 'Only the department manager can approve at this step.'
        leave.status = 'pending_hr'
        leave.save(update_fields=['status', 'updated_at'])
        hr_notifications.notify_hr_leave_pending(leave)
        sync_leave_balances_for_employee(emp.pk)
        return True, 'Forwarded to HR for final approval.'

    if leave.status == 'pending_hr':
        if not (user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'approve')):
            return False, 'You do not have HR approval permission.'
        leave.status = 'approved'
        leave.approved_by = user
        leave.approved_at = timezone.now()
        leave.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        hr_notifications.send_leave_decision(leave, approved=True)
        sync_leave_balances_for_employee(emp.pk)
        return True, 'Leave approved.'

    return False, 'This request cannot be approved in its current status.'


def reject_leave_request(request, leave, reason: str = '') -> tuple[bool, str]:
    user = request.user
    emp = leave.employee
    reason = (reason or '').strip()

    if leave.status not in ('pending_manager', 'pending_hr'):
        return False, 'Only pending requests can be rejected.'

    if leave.status == 'pending_manager':
        if not (_is_department_manager(user, emp) or user.is_superuser):
            return False, 'Only the department manager can reject at this step.'
    elif leave.status == 'pending_hr':
        if not (user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'approve')):
            return False, 'HR approval permission required.'

    leave.status = 'rejected'
    leave.rejection_reason = reason or 'Rejected.'
    leave.approved_by = user
    leave.approved_at = timezone.now()
    leave.save(
        update_fields=['status', 'rejection_reason', 'approved_by', 'approved_at', 'updated_at']
    )
    hr_notifications.send_leave_decision(leave, approved=False)
    sync_leave_balances_for_employee(emp.pk)
    return True, 'Leave request rejected.'


def cancel_leave_request(request, leave) -> tuple[bool, str]:
    if leave.status != 'pending_manager':
        return False, 'Only requests awaiting manager approval can be cancelled by the employee.'
    emp = leave.employee
    if emp.user_id != request.user.id and not request.user.is_superuser:
        return False, 'You cannot cancel this request.'
    leave.status = 'cancelled'
    leave.save(update_fields=['status', 'updated_at'])
    sync_leave_balances_for_employee(emp.pk)
    return True, 'Leave request cancelled.'
