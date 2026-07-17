"""Purchase order approval routing from Settings → Approval Configuration."""
from __future__ import annotations

from apps.settings_app.models import ApprovalConfiguration


def purchase_order_approval_enabled() -> bool:
    return ApprovalConfiguration.objects.filter(module='purchase_order', is_active=True).exists()


def get_configured_po_approver(po):
    """Configured approver for this PO amount — no superuser fallback."""
    config = ApprovalConfiguration.objects.filter(module='purchase_order', is_active=True).first()
    if not config:
        return None
    amount = po.total_amount or 0
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


def user_can_act_on_purchase_order(user, po) -> bool:
    """True when user may approve, reject, or return this pending PO."""
    if not user or not user.is_authenticated:
        return False
    if po.status != 'pending_approval':
        return False
    approver = get_configured_po_approver(po)
    if approver is None:
        return False
    return approver.pk == user.pk


def user_can_confirm_purchase_order(user, po) -> bool:
    """Direct confirm (no approval workflow) — only when PO approval is not configured."""
    if not user or not user.is_authenticated:
        return False
    if purchase_order_approval_enabled():
        return False
    if po.status != 'draft' or not po.items.exists():
        return False
    from apps.core.utils import PermissionChecker

    return user.is_superuser or PermissionChecker.has_permission(user, 'purchase', 'edit')


def po_status_allows_edit(po) -> bool:
    if not purchase_order_approval_enabled():
        return po.status == 'draft'
    return po.status in ('draft', 'returned')
