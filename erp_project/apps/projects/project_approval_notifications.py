"""In-app notifications for project completion approval."""
from apps.settings_app.models import Notification


def _user_display(user):
    if not user:
        return 'Someone'
    return (user.get_full_name() or '').strip() or user.username


def notify_approver_project_completion_pending(project):
    from django.contrib.auth import get_user_model

    from .approval_rules import get_configured_project_approver

    approver = get_configured_project_approver(project)
    if not approver:
        approver = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not approver:
        return
    submitter = _user_display(project.edit_approval_submitted_by)
    Notification.create(
        user=approver,
        title=f'Completion approval: {project.project_code}',
        message=f'{submitter} requested to mark {project.name} as Completed.',
        link=f'/projects/{project.pk}/',
    )


def notify_submitter_project_completion_approved(project, *, approver, submitter):
    if not submitter:
        return
    Notification.create(
        user=submitter,
        title=f'Project completed — {project.project_code}',
        message=f'{_user_display(approver)} approved completion for {project.name}.',
        link=f'/projects/{project.pk}/',
    )


def notify_approver_project_conversion_pending(project):
    from django.contrib.auth import get_user_model

    from .approval_rules import get_configured_project_conversion_approver

    approver = get_configured_project_conversion_approver(project)
    if not approver:
        approver = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not approver:
        return
    submitter = _user_display(project.conversion_approval_submitted_by)
    Notification.create(
        user=approver,
        title=f'Project conversion approval: {project.project_code}',
        message=f'{submitter} created {project.name} from a quotation (Draft). Approve to activate the project.',
        link=f'/projects/{project.pk}/',
    )


def notify_submitter_project_conversion_approved(project, *, approver, submitter):
    if not submitter:
        return
    Notification.create(
        user=submitter,
        title=f'Project approved — {project.project_code}',
        message=f'{_user_display(approver)} approved conversion from quotation. Project is now Planning.',
        link=f'/projects/{project.pk}/',
    )


def notify_submitter_project_conversion_rejected(project, *, approver, submitter):
    if not submitter:
        return
    Notification.create(
        user=submitter,
        title=f'Project conversion rejected — {project.project_code}',
        message=f'{_user_display(approver)} rejected the project created from the quotation.',
        link=f'/projects/{project.pk}/',
    )


def notify_submitter_project_completion_rejected(project, *, approver, submitter, comment=''):
    if not submitter:
        return
    msg = f'{_user_display(approver)} rejected the completion request for {project.name}.'
    if comment:
        msg = f'{msg} Reason: {comment}'
    Notification.create(
        user=submitter,
        title=f'Completion rejected — {project.project_code}',
        message=msg,
        link=f'/projects/{project.pk}/',
    )
