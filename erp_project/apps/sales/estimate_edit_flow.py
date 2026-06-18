"""Post-save estimate edit workflow: re-approval and revision bumps."""
from dataclasses import dataclass

# Editing in these statuses requires re-approval and bumps R1, R2, …
REVISION_RESUBMIT_STATUSES = frozenset({
    'approved',
    'rejected',
    'under_negotiation',
    'quotation_won',
    'quotation_lost',
    'sent',
})

# Backwards-compatible alias
RESUBMIT_AFTER_EDIT_STATUSES = REVISION_RESUBMIT_STATUSES


@dataclass
class EstimateEditApplyResult:
    changed: bool = True
    resubmitted_for_approval: bool = False
    revision_bumped: bool = False
    edit_pending: bool = False


def apply_after_estimate_save(request, estimate, *, pre_status: str) -> EstimateEditApplyResult:
    """
    After a successful estimate save with detected changes:
    - approved / under negotiation / quot won / quot lost / sent / rejected → sent + revision bump
    - draft → no approval action
    """
    result = EstimateEditApplyResult(changed=True)

    if pre_status in REVISION_RESUBMIT_STATUSES:
        estimate.revision_count = (estimate.revision_count or 0) + 1
        estimate.status = 'sent'
        estimate.approval_requested_by = request.user
        estimate.awaiting_resubmit_revision = False
        estimate.edit_approval_status = 'none'
        estimate.edit_approval_submitted_at = None
        estimate.edit_approval_submitted_by_id = None
        estimate.save(
            update_fields=[
                'revision_count',
                'status',
                'approval_requested_by',
                'awaiting_resubmit_revision',
                'edit_approval_status',
                'edit_approval_submitted_at',
                'edit_approval_submitted_by',
                'updated_at',
            ]
        )
        from .estimate_approval_notifications import notify_approver_estimate_sent

        notify_approver_estimate_sent(estimate, requested_by=request.user)
        result.resubmitted_for_approval = True
        result.revision_bumped = True
        from .estimate_audit import log_estimate_revision_bump

        log_estimate_revision_bump(request.user, estimate, pre_status=pre_status, request=request)
        return result

    return result
