"""Estimate revision (R1, R2, …) helpers."""


def bump_revision_on_resubmit(estimate, *, via_edit_resubmit: bool = False) -> bool:
    """
    Increment revision_count when resubmitting after rejection.
    Returns True if revision was bumped.
    """
    if via_edit_resubmit:
        estimate.revision_count = (estimate.revision_count or 0) + 1
        return True
    return False


def apply_revision_on_status_sent(estimate, old_status: str) -> list[str]:
    """
    When estimate is marked Sent again after a status rejection, bump revision.
    Returns extra model fields to save alongside status.
    """
    extra_fields = []
    should_bump = old_status == 'rejected' or getattr(estimate, 'awaiting_resubmit_revision', False)
    if should_bump and old_status != 'sent':
        estimate.revision_count = (estimate.revision_count or 0) + 1
        extra_fields.append('revision_count')
    if getattr(estimate, 'awaiting_resubmit_revision', False):
        estimate.awaiting_resubmit_revision = False
        extra_fields.append('awaiting_resubmit_revision')
    return extra_fields


def clear_awaiting_revision(estimate) -> list[str]:
    if getattr(estimate, 'awaiting_resubmit_revision', False):
        estimate.awaiting_resubmit_revision = False
        return ['awaiting_resubmit_revision']
    return []


def mark_awaiting_revision_after_status_reject(estimate) -> list[str]:
    if not getattr(estimate, 'awaiting_resubmit_revision', False):
        estimate.awaiting_resubmit_revision = True
        return ['awaiting_resubmit_revision']
    return []
