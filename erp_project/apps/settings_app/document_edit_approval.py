"""
Shared helpers for optional per-edit approval (estimates, projects).

When Approval Configuration exists for a module, non-approver saves set
edit_approval_status to pending and notify the configured approver.
Superusers and the configured approver clear pending on their own saves.
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
    if not approval_config_active(module):
        return

    amount = amount_accessor(obj)
    fields = [
        'edit_approval_status',
        'edit_approval_submitted_at',
        'edit_approval_submitted_by',
        'updated_at',
    ]

    if should_skip_pending_for_user(request.user, module, amount):
        obj.edit_approval_status = 'none'
        obj.edit_approval_submitted_at = None
        obj.edit_approval_submitted_by_id = None
        obj.save(update_fields=fields)
        return

    obj.edit_approval_status = 'pending'
    obj.edit_approval_submitted_at = timezone.now()
    obj.edit_approval_submitted_by = request.user
    obj.save(update_fields=fields)
    ApprovalConfiguration.notify_approver(obj, module)
