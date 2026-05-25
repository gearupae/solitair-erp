"""Estimate edit access, status transitions, and approval permissions."""
from apps.core.utils import PermissionChecker
from apps.settings_app.models import ApprovalConfiguration


def user_can_edit_estimate(user, estimate) -> bool:
    """
    Who may open the estimate edit form.

    Quotations marked **Quot Won** may only be edited by superusers (admin).
    Everyone else with sales edit permission can edit other statuses.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if getattr(estimate, 'status', None) == 'quotation_won':
        return False
    return PermissionChecker.has_permission(user, 'sales', 'edit')


def user_is_assigned_to_estimate(user, estimate) -> bool:
    """True when the user is the estimate's assigned salesperson."""
    if not user or not user.is_authenticated:
        return False
    assignee_id = getattr(estimate, 'assigned_to_id', None)
    return assignee_id is not None and assignee_id == user.pk


def user_can_mark_estimate_won_lost(user, estimate) -> bool:
    """Only the assigned salesperson may mark an approved estimate won or lost."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user_is_assigned_to_estimate(user, estimate)


def user_can_recall_sent_to_draft(user, estimate) -> bool:
    """Sales may pull back a sent quotation to draft; approvers cannot (approve/reject only)."""
    if not user_can_edit_estimate(user, estimate):
        return False
    if user.is_superuser:
        return True
    if user_is_configured_estimate_approver(user, estimate):
        return False
    return True


def get_configured_estimate_approver(estimate):
    """
    Explicit approver from Settings → Approval Configuration (estimate module).
    Does not fall back to superuser when unset.
    """
    config = ApprovalConfiguration.objects.filter(module='estimate', is_active=True).first()
    if not config:
        return None

    amount = estimate.total_amount or 0
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
    return level.approver if level else config.default_approver


def user_is_any_estimate_approver(user) -> bool:
    """True if user is the configured approver for estimates (any level)."""
    if not user or not user.is_authenticated:
        return False
    config = ApprovalConfiguration.objects.filter(module='estimate', is_active=True).first()
    if not config:
        return False
    if config.default_approver_id == user.pk:
        return True
    return config.levels.filter(is_active=True, approver_id=user.pk).exists()


def user_is_estimate_approver_portal(user) -> bool:
    """
    Simplified estimates list for configured estimate approvers.
    Superusers keep the full estimates workspace.
    """
    if not user_is_any_estimate_approver(user):
        return False
    if user.is_superuser:
        return False
    return PermissionChecker.has_permission(user, 'sales', 'view')


def user_is_configured_estimate_approver(user, estimate) -> bool:
    """Only the configured estimate approver — not superuser unless assigned as approver."""
    if not user or not user.is_authenticated:
        return False
    ap = get_configured_estimate_approver(estimate)
    return ap is not None and ap.pk == user.pk


def user_can_approve_estimate_edit(user, estimate) -> bool:
    """Configured estimate approver may approve/reject pending edit review."""
    return user_is_configured_estimate_approver(user, estimate)


def estimate_status_change_allowed(current_status, new_status, *, user=None, estimate=None) -> bool:
    """Validate estimate status transitions for the sales approval workflow."""
    if current_status == new_status:
        return True

    if user and user.is_superuser:
        if current_status == 'quotation_won' and new_status == 'draft':
            return False
        return True

    if current_status == 'quotation_won':
        return False

    if new_status in ('quotation_won', 'quotation_lost'):
        return (
            current_status == 'approved'
            and user is not None
            and estimate is not None
            and user_can_mark_estimate_won_lost(user, estimate)
        )

    if new_status in ('approved', 'rejected'):
        return (
            current_status == 'sent'
            and user is not None
            and estimate is not None
            and user_is_configured_estimate_approver(user, estimate)
        )

    if new_status == 'sent':
        return current_status in ('draft', 'rejected', 'quotation_lost')

    if new_status == 'draft':
        if current_status in ('rejected', 'quotation_lost'):
            return user is not None and estimate is not None and user_can_edit_estimate(user, estimate)
        if current_status == 'sent':
            return (
                user is not None
                and estimate is not None
                and user_can_recall_sent_to_draft(user, estimate)
            )
        return False

    return False


def get_estimate_status_actions(estimate, user):
    """
    Status buttons for estimate detail / list.
    Each item: {'status', 'label', 'btn_class', 'icon'}.
    """
    if not user or not user.is_authenticated:
        return []

    can_edit = user_can_edit_estimate(user, estimate)
    is_approver = user_is_configured_estimate_approver(user, estimate)
    can_mark_won_lost = user_can_mark_estimate_won_lost(user, estimate)
    current = estimate.status
    actions = []

    if is_approver and current == 'sent':
        actions.extend([
            {
                'status': 'approved',
                'label': 'Approve',
                'btn_class': 'btn-outline-success',
                'icon': 'fa-check',
            },
            {
                'status': 'rejected',
                'label': 'Reject',
                'btn_class': 'btn-outline-danger',
                'icon': 'fa-times',
            },
        ])
        return actions

    if can_edit:
        if current == 'draft':
            actions.append({
                'status': 'sent',
                'label': 'Send for approval',
                'btn_class': 'btn-outline-primary',
                'icon': 'fa-paper-plane',
            })
        elif current == 'sent':
            actions.append({
                'status': 'draft',
                'label': 'Revert to Draft',
                'btn_class': 'btn-outline-secondary',
                'icon': 'fa-undo',
            })
        elif current == 'approved' and can_mark_won_lost:
            actions.extend([
                {
                    'status': 'quotation_won',
                    'label': 'Mark estimate won',
                    'btn_class': 'btn-outline-success',
                    'icon': 'fa-trophy',
                },
                {
                    'status': 'quotation_lost',
                    'label': 'Mark estimate lost',
                    'btn_class': 'btn-outline-secondary',
                    'icon': 'fa-times-circle',
                },
            ])
        elif current in ('rejected', 'quotation_lost'):
            actions.append({
                'status': 'draft',
                'label': 'Revert to Draft',
                'btn_class': 'btn-outline-secondary',
                'icon': 'fa-undo',
            })
            actions.append({
                'status': 'sent',
                'label': 'Send for approval',
                'btn_class': 'btn-outline-primary',
                'icon': 'fa-paper-plane',
            })

    return actions


def allowed_status_choices_for_estimate(estimate, user):
    """Dropdown options: current status plus allowed transitions."""
    labels = dict(type(estimate).STATUS_CHOICES)
    current = estimate.status
    choices = [(current, labels.get(current, current))]
    for action in get_estimate_status_actions(estimate, user):
        code = action['status']
        if code != current:
            choices.append((code, labels.get(code, action['label'])))
    return choices
