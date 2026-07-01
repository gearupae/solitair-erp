"""Recruitment request approval routing from Settings → Approval Configuration."""
from __future__ import annotations

from apps.recruitment.models import RecruitmentRequest
from apps.settings_app.models import ApprovalConfiguration


def get_configured_recruitment_approver(recruitment_request):
    """Configured approver for this request (uses openings count as amount threshold)."""
    config = ApprovalConfiguration.objects.filter(module='recruitment_request', is_active=True).first()
    if not config:
        return None
    amount = recruitment_request.openings or 1
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


def user_can_act_on_recruitment_request(user, recruitment_request) -> bool:
    """True when user may approve or reject a pending recruitment request."""
    if not user or not user.is_authenticated:
        return False
    if recruitment_request.status != RecruitmentRequest.STATUS_PENDING:
        return False
    approver = get_configured_recruitment_approver(recruitment_request)
    if approver is not None:
        return approver.pk == user.pk
    return user.is_superuser


def annotate_recruitment_approval_actions(user, requests):
    for req in requests:
        req.show_approve_actions = user_can_act_on_recruitment_request(user, req)
    return requests
