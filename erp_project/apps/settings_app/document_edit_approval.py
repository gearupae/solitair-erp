"""
Shared helpers for optional per-edit approval (sales estimates).

When Approval Configuration exists for the estimate module, non-approver saves set
edit_approval_status to pending and notify the configured approver.
Superusers and the configured approver clear pending on their own saves.

Project edits apply immediately except status → Completed, which requires approver sign-off.
"""
from django.utils import timezone

from .models import ApprovalConfiguration


def approval_config_active(module: str) -> bool:
    return ApprovalConfiguration.objects.filter(module=module, is_active=True).exists()


def _approver_for(module: str, amount):
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        amt = 0
    return ApprovalConfiguration.get_approver_for_amount(module, amt)


def should_skip_pending_for_user(user, module: str, amount) -> bool:
    """Superuser or the module's configured approver does not enqueue a pending review."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    ap = _approver_for(module, amount)
    return ap is not None and ap.pk == user.pk


def apply_after_document_edit(request, *, module: str, obj, amount_accessor):
    """
    Update obj.edit_* fields after a successful edit save (not used on initial create).

    Caller should refresh computed totals on obj before calling (e.g. calculate_totals()).
    """
    if module == 'project':
        return

    if not approval_config_active(module):
        return

    amount = amount_accessor(obj)
    fields = [
        'edit_approval_status',
        'edit_approval_submitted_at',
        'edit_approval_submitted_by',
        'updated_at',
    ]
    previous_status = obj.edit_approval_status

    if should_skip_pending_for_user(request.user, module, amount):
        obj.edit_approval_status = 'none'
        obj.edit_approval_submitted_at = None
        obj.edit_approval_submitted_by_id = None
        obj.save(update_fields=fields)
        return

    obj.edit_approval_status = 'pending'
    obj.edit_approval_submitted_at = timezone.now()
    obj.edit_approval_submitted_by = request.user

    if module == 'estimate' and previous_status == 'rejected':
        from apps.sales.estimate_revision import bump_revision_on_resubmit

        if bump_revision_on_resubmit(obj, via_edit_resubmit=True):
            fields.append('revision_count')

    obj.save(update_fields=fields)
    if module == 'estimate':
        from apps.sales.estimate_approval_notifications import notify_approver_estimate_edit_pending

        notify_approver_estimate_edit_pending(obj)
    else:
        ApprovalConfiguration.notify_approver(obj, module)
