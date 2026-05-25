"""In-app + email notifications for estimate approval workflow."""
from __future__ import annotations

import logging

from django.core.mail import EmailMessage
from django.urls import reverse

from apps.core.notification_utils import notify_user
from apps.purchase.email_outbound import company_outgoing_from_email, get_smtp_connection_or_default
from apps.settings_app.models import CompanySettings

logger = logging.getLogger(__name__)


def _estimate_link(estimate) -> str:
    return reverse('sales:estimate_detail', kwargs={'pk': estimate.pk})


def _estimate_ref(estimate) -> str:
    return getattr(estimate, 'display_estimate_number', None) or estimate.estimate_number


def _user_display(user) -> str:
    if not user:
        return 'User'
    return user.get_full_name() or user.username


def _send_email(user, subject: str, body: str) -> bool:
    to = (getattr(user, 'email', None) or '').strip()
    if not to:
        return False
    company = CompanySettings.get_settings()
    try:
        connection = get_smtp_connection_or_default(company)
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=[to],
            connection=connection,
        )
        msg.send(fail_silently=False)
        return True
    except Exception as exc:
        logger.warning('Estimate approval email to %s failed: %s', to, exc)
        return False


def _notify(user, *, title: str, message: str, link: str, email_body: str | None = None):
    if not user:
        return
    notify_user(user, title, message, link)
    body = email_body if email_body is not None else f'{message}\n\nOpen in ERP: {link}'
    _send_email(user, title, body)


def notify_approver_estimate_edit_pending(estimate):
    """Salesperson saved edits — notify configured approver."""
    from .approval_rules import get_configured_estimate_approver

    approver = get_configured_estimate_approver(estimate)
    if not approver:
        return

    ref = _estimate_ref(estimate)
    link = _estimate_link(estimate)
    submitter = _user_display(estimate.edit_approval_submitted_by)
    title = f'Estimate edit approval required — {ref}'
    message = (
        f'{submitter} updated estimate {ref}. '
        f'Please review and approve or reject the changes.'
    )
    _notify(approver, title=title, message=message, link=link)


def notify_approver_estimate_sent(estimate, *, requested_by):
    """Estimate marked Sent — notify configured approver to approve/reject status."""
    from .approval_rules import get_configured_estimate_approver

    approver = get_configured_estimate_approver(estimate)
    if not approver:
        return

    ref = _estimate_ref(estimate)
    link = _estimate_link(estimate)
    submitter = _user_display(requested_by)
    title = f'Estimate approval required — {ref}'
    message = (
        f'{submitter} sent estimate {ref} for your approval. '
        f'Please approve or reject it in Sales → Estimates.'
    )
    _notify(approver, title=title, message=message, link=link)


def notify_submitter_estimate_edit_approved(estimate, *, approver, submitter=None):
    """Approver accepted pending edits."""
    user = submitter or estimate.edit_approval_submitted_by or estimate.assigned_to
    if not user:
        return

    ref = _estimate_ref(estimate)
    link = _estimate_link(estimate)
    title = f'Estimate edit approved — {ref}'
    message = (
        f'{_user_display(approver)} approved your changes to estimate {ref}.'
    )
    _notify(user, title=title, message=message, link=link)


def notify_submitter_estimate_edit_rejected(estimate, *, approver, comment: str = ''):
    """Approver rejected pending edits."""
    user = estimate.edit_approval_submitted_by or estimate.assigned_to
    if not user:
        return

    ref = _estimate_ref(estimate)
    link = _estimate_link(estimate)
    title = f'Estimate edit rejected — {ref}'
    extra = f' Comment: {comment}' if comment else ''
    message = (
        f'{_user_display(approver)} rejected your changes to estimate {ref}.{extra} '
        f'Please update the estimate and save again to resubmit.'
    )
    _notify(user, title=title, message=message, link=link)


def notify_submitter_estimate_status_approved(estimate, *, approver):
    """Approver set estimate status to Approved."""
    user = estimate.approval_requested_by or estimate.assigned_to
    if not user:
        return

    ref = _estimate_ref(estimate)
    link = _estimate_link(estimate)
    title = f'Estimate approved — {ref}'
    message = f'{_user_display(approver)} approved estimate {ref}.'
    _notify(user, title=title, message=message, link=link)


def notify_submitter_estimate_status_rejected(estimate, *, approver, reason: str = ''):
    """Approver set estimate status to Rejected."""
    user = estimate.approval_requested_by or estimate.assigned_to
    if not user:
        return

    ref = _estimate_ref(estimate)
    link = _estimate_link(estimate)
    title = f'Estimate rejected — {ref}'
    extra = f' Reason: {reason}' if reason else ''
    message = (
        f'{_user_display(approver)} rejected estimate {ref}.{extra} '
        f'You may revise it and send again for approval.'
    )
    _notify(user, title=title, message=message, link=link)
