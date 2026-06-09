"""Visibility for records pending approval by a configured approver."""
from decimal import Decimal

from django.db.models import Q, Value
from django.db.models.functions import Coalesce

from apps.settings_app.models import ApprovalConfiguration


def _user_in_approval_config(config, user):
    if not config or not user or not user.is_authenticated:
        return False
    if config.default_approver_id == user.pk:
        return True
    return config.levels.filter(is_active=True, approver_id=user.pk).exists()


def _build_amount_tier_q(config, user, amount_field):
    """Q for rows where `user` is the configured approver for the row amount."""
    if not _user_in_approval_config(config, user):
        return Q(pk__in=[])

    if config.approval_type == 'single':
        if config.default_approver_id != user.pk:
            return Q(pk__in=[])
        return Q(pk__isnull=False)

    levels = list(config.levels.filter(is_active=True).order_by('amount_threshold'))
    if not levels:
        if config.default_approver_id == user.pk:
            return Q(pk__isnull=False)
        return Q(pk__in=[])

    tier_q = Q(pk__in=[])
    for idx, level in enumerate(levels):
        if level.approver_id != user.pk:
            continue
        prev = levels[idx - 1].amount_threshold if idx > 0 else Decimal('0')
        tier_q |= Q(**{
            f'{amount_field}__gt': prev,
            f'{amount_field}__lte': level.amount_threshold,
        })
        if idx == len(levels) - 1:
            tier_q |= Q(**{f'{amount_field}__gt': level.amount_threshold})

    if tier_q == Q(pk__in=[]) and config.default_approver_id == user.pk:
        return Q(pk__isnull=False)
    return tier_q


ESTIMATE_APPROVER_VISIBLE_STATUSES = frozenset({
    'sent', 'approved', 'rejected', 'under_negotiation', 'quotation_won', 'quotation_lost',
})


def _estimate_approver_status_q():
    """Statuses where configured approvers retain read access."""
    return Q(status__in=ESTIMATE_APPROVER_VISIBLE_STATUSES) | Q(edit_approval_status='pending')


def estimate_approver_records_q(user):
    """Estimates the user may see as configured approver."""
    config = ApprovalConfiguration.objects.filter(module='estimate', is_active=True).first()
    if not config:
        return Q(pk__in=[])
    amount_q = _build_amount_tier_q(config, user, 'total_amount')
    return _estimate_approver_status_q() & amount_q


def purchase_request_approver_records_q(user):
    """PRs the user may see as configured approver."""
    config = ApprovalConfiguration.objects.filter(module='purchase_request', is_active=True).first()
    if not config:
        return Q(pk__in=[])
    pending = Q(status='pending')
    amount_q = _build_amount_tier_q(config, user, 'total_amount')
    return pending & amount_q


def project_approver_records_q(user):
    """Projects the user may see as configured completion approver (pending or completed)."""
    config = ApprovalConfiguration.objects.filter(module='project', is_active=True).first()
    if not config:
        return Q(pk__in=[])
    amount_q = _build_amount_tier_q(config, user, '_approval_amount')
    pending = Q(edit_approval_status='pending') & amount_q
    # Keep completed projects visible after approval (avoid 404 on redirect).
    completed = Q(status='completed') & amount_q
    return pending | completed


def project_conversion_approver_records_q(user):
    """Projects the conversion approver may view (pending queue + quotation-sourced)."""
    config = ApprovalConfiguration.objects.filter(
        module='project_conversion', is_active=True
    ).first()
    if not config:
        return Q(pk__in=[])
    amount_q = _build_amount_tier_q(config, user, '_approval_amount')
    pending = Q(status='draft', conversion_approval_status='pending') & amount_q
    # Quotation-sourced projects stay visible after approval (notification links, review).
    from_estimate = Q(estimates__isnull=False) & amount_q
    return pending | from_estimate


def annotate_project_approval_amount(queryset):
    """Annotate Coalesce(contract_value, budget) for approval tier matching."""
    return queryset.annotate(
        _approval_amount=Coalesce('contract_value', 'budget', Value(Decimal('0.00')))
    )

def user_is_estimate_approver_for(user, estimate):
    from apps.sales.approval_rules import user_is_configured_estimate_approver

    if not estimate:
        return False
    if estimate.status not in ESTIMATE_APPROVER_VISIBLE_STATUSES and estimate.edit_approval_status != 'pending':
        return False
    return user_is_configured_estimate_approver(user, estimate)


def user_is_purchase_request_approver_for(user, purchase_request):
    from apps.purchase.pr_approval_rules import user_can_act_on_purchase_request

    if not purchase_request or purchase_request.status != 'pending':
        return False
    return user_can_act_on_purchase_request(user, purchase_request)


def user_is_project_approver_for(user, project):
    from apps.projects.approval_rules import (
        get_configured_project_approver,
        user_can_approve_project_completion,
    )

    if not project:
        return False
    if project.edit_approval_status == 'pending':
        return user_can_approve_project_completion(user, project)
    if project.status == 'completed':
        approver = get_configured_project_approver(project)
        if approver is not None:
            return approver.pk == user.pk
        return bool(user.is_superuser)
    return False


def user_is_project_conversion_approver_for(user, project):
    from apps.projects.approval_rules import (
        user_can_approve_project_conversion,
        user_is_configured_project_conversion_approver,
    )

    if not project:
        return False
    if not user_is_configured_project_conversion_approver(user, project):
        return False
    if user_can_approve_project_conversion(user, project):
        return True
    if project.estimates.exists():
        return True
    if project.conversion_approval_submitted_at:
        return True
    if project.conversion_approval_status == 'rejected':
        return True
    return False
