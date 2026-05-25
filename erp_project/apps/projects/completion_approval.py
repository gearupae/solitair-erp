"""Project completion (status → Completed) approval workflow."""
from django.utils import timezone


def completion_approval_required(user, project) -> bool:
    """
    Completing via the edit form always queues approval.
    Only the Approve completion action on the project page finalizes Completed.
    """
    return True


def queue_project_completion_approval(user, project):
    project.edit_approval_status = 'pending'
    project.edit_approval_submitted_at = timezone.now()
    project.edit_approval_submitted_by = user
    project.save(
        update_fields=[
            'edit_approval_status',
            'edit_approval_submitted_at',
            'edit_approval_submitted_by',
            'updated_at',
        ]
    )
    from .project_approval_notifications import notify_approver_project_completion_pending

    notify_approver_project_completion_pending(project)


def clear_project_completion_approval(project):
    project.edit_approval_status = 'none'
    project.edit_approval_submitted_at = None
    project.edit_approval_submitted_by_id = None
