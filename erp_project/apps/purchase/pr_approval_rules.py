"""Purchase request approval routing from Settings → Approval Configuration."""
from __future__ import annotations

from apps.settings_app.models import ApprovalConfiguration


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
    return purchase_requests
