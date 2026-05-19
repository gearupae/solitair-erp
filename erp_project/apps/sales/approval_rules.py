"""Estimate edit access and edit-approval permissions."""
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


def user_can_approve_estimate_edit(user, estimate) -> bool:
    """Configured approver (or superuser) may clear pending edit review."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    ap = ApprovalConfiguration.get_approver_for_amount('estimate', estimate.total_amount or 0)
    return ap is not None and ap.pk == user.pk
