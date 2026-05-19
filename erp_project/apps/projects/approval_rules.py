"""Project edit access and edit-approval permissions."""
from apps.core.utils import PermissionChecker
from apps.settings_app.models import ApprovalConfiguration


def user_can_edit_project(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'edit')


def user_can_approve_project_edit(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    ap = ApprovalConfiguration.get_approver_for_amount('project', project.contract_value or 0)
    return ap is not None and ap.pk == user.pk
