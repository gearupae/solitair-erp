"""Audit logging helpers for estimate lifecycle events."""
from __future__ import annotations

from apps.sales.estimate_activity import log_estimate_activity
from apps.sales.models import Estimate


def log_estimate_created(user, estimate: Estimate, *, request=None, duplicated_from: str = '') -> None:
    changes = {'estimate_number': estimate.display_estimate_number}
    if duplicated_from:
        changes.update({'field': 'duplicate', 'source_number': duplicated_from})
    log_estimate_activity(user, 'create', estimate, changes=changes, request=request)


def log_estimate_status_change(
    user,
    estimate: Estimate,
    *,
    old_status: str,
    new_status: str,
    rejection_reason: str = '',
    request=None,
) -> None:
    labels = dict(Estimate.STATUS_CHOICES)
    changes = {
        'field': 'status',
        'from': old_status,
        'to': new_status,
        'from_display': labels.get(old_status, old_status),
        'to_display': labels.get(new_status, new_status),
    }
    if rejection_reason:
        changes['rejection_reason'] = rejection_reason.strip()[:500]
    action = 'approve' if new_status == 'approved' else 'reject' if new_status == 'rejected' else 'update'
    log_estimate_activity(user, action, estimate, changes=changes, request=request)


def log_estimate_revision_bump(user, estimate: Estimate, *, pre_status: str, request=None) -> None:
    label = estimate.revision_label or f'R{estimate.revision_count or 0}'
    log_estimate_activity(
        user,
        'update',
        estimate,
        changes={
            'field': 'revision',
            'revision': estimate.revision_count,
            'revision_label': label,
            'from_status': pre_status,
            'to_status': estimate.status,
            'note': f'Quotation edited ({label}); sent for re-approval',
        },
        request=request,
    )


def log_estimate_edit_review(user, estimate: Estimate, *, approved: bool, comment: str = '', request=None) -> None:
    log_estimate_activity(
        user,
        'approve' if approved else 'reject',
        estimate,
        changes={
            'field': 'edit_approval',
            'title': 'Edit changes approved' if approved else 'Edit changes rejected',
            'detail': comment or ('Edit review cleared' if approved else 'Editor must correct and resubmit'),
        },
        request=request,
    )


def log_estimate_project_conversion(user, estimate: Estimate, project, *, request=None) -> None:
    log_estimate_activity(
        user,
        'update',
        estimate,
        changes={
            'field': 'project',
            'project_code': project.project_code,
            'project_name': project.name,
        },
        request=request,
    )


def log_estimate_invoice_conversion(user, estimate: Estimate, invoice, *, request=None) -> None:
    log_estimate_activity(
        user,
        'update',
        estimate,
        changes={
            'field': 'invoice',
            'invoice_number': invoice.invoice_number,
        },
        request=request,
    )
