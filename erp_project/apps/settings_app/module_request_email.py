"""Email notification when a user requests ERP module access."""
from __future__ import annotations

import logging

from django.core.mail import EmailMessage
from django.utils import timezone

from apps.purchase.email_outbound import company_outgoing_from_email, get_smtp_connection_or_default
from apps.settings_app.models import CompanySettings

logger = logging.getLogger(__name__)

MODULE_REQUEST_INBOX = 'erp@gear-up.ae'


def send_module_access_request_email(request_obj) -> bool:
    """Notify ERP team that a user requested module access."""
    user = request_obj.user
    module_label = request_obj.get_module_display()
    requester_name = user.get_full_name() or user.username
    requester_email = (user.email or '').strip()
    reason = (request_obj.reason or '').strip()

    subject = f'ERP module access request — {module_label} ({requester_name})'
    lines = [
        'A user requested access to an ERP module.',
        '',
        f'Module: {module_label}',
        f'User: {requester_name}',
        f'Username: {user.username}',
    ]
    if requester_email:
        lines.append(f'Email: {requester_email}')
    lines.append(f'Submitted: {timezone.localtime(request_obj.created_at).strftime("%d/%m/%Y %H:%M")}')
    if reason:
        lines.extend(['', 'Reason:', reason])
    lines.extend([
        '',
        'Review users and roles in ERP → Settings → Users.',
    ])
    body = '\n'.join(lines)

    company = CompanySettings.get_settings()
    try:
        connection = get_smtp_connection_or_default(company)
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=[MODULE_REQUEST_INBOX],
            connection=connection,
        )
        if requester_email:
            msg.reply_to = [requester_email]
        msg.send(fail_silently=False)
        return True
    except Exception as exc:
        logger.warning('Module access request email to %s failed: %s', MODULE_REQUEST_INBOX, exc)
        return False
