"""Shared logic for estimate status transitions (detail + list)."""
from __future__ import annotations


def validate_status_rejection_reason(new_status: str, old_status: str, rejection_reason: str) -> str | None:
    if new_status == 'rejected' and old_status != 'rejected':
        if not (rejection_reason or '').strip():
            return 'Please provide a reason for rejection.'
    return None


def apply_estimate_status_fields(
    estimate,
    *,
    new_status: str,
    old_status: str,
    user,
    rejection_reason: str = '',
) -> list[str]:
    """Mutate estimate for a status change; return fields to save."""
    from .estimate_revision import (
        apply_revision_on_status_sent,
        clear_awaiting_revision,
        mark_awaiting_revision_after_status_reject,
    )

    reason = (rejection_reason or '').strip()
    update_fields = ['status', 'updated_at']

    if new_status == 'sent' and old_status != 'sent':
        estimate.approval_requested_by = user
        update_fields.append('approval_requested_by')
        update_fields.extend(apply_revision_on_status_sent(estimate, old_status))
        estimate.rejection_reason = ''
        update_fields.append('rejection_reason')
    elif new_status == 'rejected' and old_status != 'rejected':
        estimate.rejection_reason = reason[:2000]
        update_fields.append('rejection_reason')
        update_fields.extend(mark_awaiting_revision_after_status_reject(estimate))
    elif new_status == 'approved' and old_status != 'approved':
        estimate.rejection_reason = ''
        update_fields.append('rejection_reason')
        update_fields.extend(clear_awaiting_revision(estimate))
    elif new_status == 'draft':
        estimate.rejection_reason = ''
        update_fields.append('rejection_reason')
        if old_status == 'sent':
            estimate.approval_requested_by_id = None
            estimate.edit_approval_status = 'none'
            estimate.edit_approval_submitted_at = None
            estimate.edit_approval_submitted_by_id = None
            update_fields.extend([
                'approval_requested_by',
                'edit_approval_status',
                'edit_approval_submitted_at',
                'edit_approval_submitted_by',
            ])

    if new_status == 'quotation_won' and old_status != 'quotation_won':
        from .sales_order import allocate_sales_order_number

        if not (estimate.sales_order_number or '').strip():
            estimate.sales_order_number = allocate_sales_order_number()
            update_fields.append('sales_order_number')

    estimate.status = new_status
    return list(dict.fromkeys(update_fields))


def after_estimate_status_saved(
    estimate,
    *,
    new_status: str,
    old_status: str,
    user,
    rejection_reason: str = '',
) -> None:
    """Notifications and audit log after status save."""
    from apps.settings_app.models import ApprovalAuditLog

    from .estimate_approval_notifications import (
        notify_approver_estimate_sent,
        notify_submitter_estimate_status_approved,
        notify_submitter_estimate_status_rejected,
    )

    reason = (rejection_reason or '').strip()

    if new_status == 'sent' and old_status != 'sent':
        notify_approver_estimate_sent(estimate, requested_by=user)
    elif new_status == 'approved' and old_status != 'approved':
        notify_submitter_estimate_status_approved(estimate, approver=user)
    elif new_status == 'rejected' and old_status != 'rejected':
        ApprovalAuditLog.objects.create(
            module='estimate',
            reference=estimate.estimate_number,
            approver=user,
            action='reject',
            comment=reason[:2000],
        )
        notify_submitter_estimate_status_rejected(
            estimate, approver=user, reason=reason
        )

    if old_status != new_status:
        from .estimate_audit import log_estimate_status_change

        log_estimate_status_change(
            user,
            estimate,
            old_status=old_status,
            new_status=new_status,
            rejection_reason=reason if new_status == 'rejected' else '',
        )
