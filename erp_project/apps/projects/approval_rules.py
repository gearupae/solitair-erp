"""Project edit access and completion approval permissions."""
from apps.core.utils import PermissionChecker
from apps.settings_app.models import ApprovalConfiguration


def user_can_edit_project(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'edit')


def get_configured_project_approver(project):
    """Explicit project approver from Settings — never falls back to superuser."""
    config = ApprovalConfiguration.objects.filter(module='project', is_active=True).first()
    if not config:
        return None
    if config.approval_type == 'single':
        return config.default_approver
    amount = project.contract_value or project.budget or 0
    level = (
        config.levels.filter(is_active=True)
        .order_by('amount_threshold')
        .filter(amount_threshold__gte=amount)
        .first()
    )
    if not level:
        level = config.levels.filter(is_active=True).order_by('-amount_threshold').first()
    return (level.approver if level else None) or config.default_approver


def user_is_project_completion_approver(user) -> bool:
    """True if this user may approve project completion requests (any project)."""
    if not user or not user.is_authenticated:
        return False
    config = ApprovalConfiguration.objects.filter(module='project', is_active=True).first()
    if not config:
        return user.is_superuser
    if config.default_approver_id == user.pk:
        return True
    if config.approval_type == 'single':
        return config.default_approver_id == user.pk
    return config.levels.filter(is_active=True, approver_id=user.pk).exists()


def pending_completion_projects_for_user(user):
    """Projects awaiting completion approval that this user can action."""
    from .models import Project

    if not user_is_project_completion_approver(user):
        return []
    qs = (
        Project.objects.filter(is_active=True, edit_approval_status='pending')
        .select_related('customer', 'manager', 'edit_approval_submitted_by')
        .order_by('-edit_approval_submitted_at', '-pk')
    )
    return [p for p in qs if user_can_approve_project_completion(user, p)]


def user_is_project_conversion_approver(user) -> bool:
    """True if this user may approve quotation → project conversions (any project)."""
    if not user or not user.is_authenticated:
        return False
    config = ApprovalConfiguration.objects.filter(
        module='project_conversion', is_active=True
    ).first()
    if not config:
        return user.is_superuser
    if config.default_approver_id == user.pk:
        return True
    if config.approval_type == 'single':
        return config.default_approver_id == user.pk
    return config.levels.filter(is_active=True, approver_id=user.pk).exists()


def pending_conversion_projects_for_user(user):
    """Draft projects awaiting conversion approval that this user can action."""
    from apps.core.approval_visibility import annotate_project_approval_amount
    from apps.core.visibility import filter_projects_for_user
    from .models import Project

    if not user_is_project_conversion_approver(user):
        return []
    qs = annotate_project_approval_amount(
        Project.objects.filter(
            is_active=True,
            status='draft',
            conversion_approval_status='pending',
        )
    ).select_related(
        'customer', 'manager', 'conversion_approval_submitted_by'
    ).order_by('-conversion_approval_submitted_at', '-pk')
    qs = filter_projects_for_user(qs, user)
    return [p for p in qs if user_can_approve_project_conversion(user, p)]


def user_can_approve_project_completion(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    approver = get_configured_project_approver(project)
    if approver is not None:
        return approver.pk == user.pk
    # No approver configured — allow superuser to approve on project page
    return user.is_superuser


def user_is_configured_project_conversion_approver(user, project) -> bool:
    if not user or not user.is_authenticated or not project:
        return False
    approver = get_configured_project_conversion_approver(project)
    if approver is not None:
        return approver.pk == user.pk
    return user.is_superuser


def get_configured_project_conversion_approver(project):
    """Approver for estimate → project (Draft) from Settings."""
    config = ApprovalConfiguration.objects.filter(
        module='project_conversion', is_active=True
    ).first()
    if not config:
        return None
    if config.approval_type == 'single':
        return config.default_approver
    amount = project.contract_value or project.budget or 0
    level = (
        config.levels.filter(is_active=True)
        .order_by('amount_threshold')
        .filter(amount_threshold__gte=amount)
        .first()
    )
    if not level:
        level = config.levels.filter(is_active=True).order_by('-amount_threshold').first()
    return (level.approver if level else None) or config.default_approver


def user_can_approve_project_conversion(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    if project.conversion_approval_status != 'pending' or project.status != 'draft':
        return False
    approver = get_configured_project_conversion_approver(project)
    if approver is not None:
        return approver.pk == user.pk
    return user.is_superuser
