"""Project created from estimate: Draft status until conversion approver confirms."""
from django.utils import timezone

from apps.settings_app.models import ApprovalConfiguration


def project_awaiting_conversion_approval(project) -> bool:
    """Project was created from a quotation and must be approved before status changes."""
    return (
        getattr(project, 'conversion_approval_status', None) == 'pending'
        and getattr(project, 'status', None) == 'draft'
    )


def project_conversion_approval_configured() -> bool:
    return ApprovalConfiguration.objects.filter(
        module='project_conversion', is_active=True
    ).exists()


def queue_project_conversion_approval(user, project):
    project.status = 'draft'
    project.conversion_approval_status = 'pending'
    project.conversion_approval_submitted_at = timezone.now()
    project.conversion_approval_submitted_by = user
    project.save(
        update_fields=[
            'status',
            'conversion_approval_status',
            'conversion_approval_submitted_at',
            'conversion_approval_submitted_by',
            'updated_at',
        ]
    )
    from .project_approval_notifications import notify_approver_project_conversion_pending

    notify_approver_project_conversion_pending(project)


def approve_project_conversion(project):
    project.status = 'planning'
    project.conversion_approval_status = 'none'
    project.save(
        update_fields=[
            'status',
            'conversion_approval_status',
            'updated_at',
        ]
    )


def reject_project_conversion(project):
    from apps.sales.models import Estimate

    project.status = 'cancelled'
    project.conversion_approval_status = 'rejected'
    project.save(update_fields=['status', 'conversion_approval_status', 'updated_at'])
    Estimate.objects.filter(project=project).update(project=None)
