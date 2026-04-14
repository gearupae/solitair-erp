"""Helpers for outbound email using Company Settings SMTP or Django defaults."""
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import get_connection
from django.core.validators import validate_email


def split_email_addresses(raw):
    if not (raw or '').strip():
        return []
    parts = re.split(r'[\s,;]+', str(raw).strip())
    return [p for p in parts if p]


def validate_to_addresses(raw):
    emails = split_email_addresses(raw)
    if not emails:
        raise ValueError('Enter at least one recipient in To.')
    for e in emails:
        try:
            validate_email(e)
        except ValidationError as exc:
            raise ValueError(f'Invalid email in To: {e}') from exc
    return emails


def validate_cc_addresses(raw):
    emails = split_email_addresses(raw)
    for e in emails:
        try:
            validate_email(e)
        except ValidationError as exc:
            raise ValueError(f'Invalid email in Cc: {e}') from exc
    return emails


def company_outgoing_from_email(company):
    if (company.smtp_from_email or '').strip():
        return company.smtp_from_email.strip()
    if (company.email or '').strip():
        return company.email.strip()
    return getattr(settings, 'DEFAULT_FROM_EMAIL', 'webmaster@localhost')


def get_smtp_connection_or_default(company):
    host = (company.smtp_host or '').strip()
    if host:
        return get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=host,
            port=int(company.smtp_port or 587),
            username=(company.smtp_username or '').strip(),
            password=company.smtp_password or '',
            use_tls=bool(company.smtp_use_tls),
        )
    return get_connection()


def outgoing_mail_hint(company):
    """Human hint when company SMTP is not filled in."""
    if (company.smtp_host or '').strip():
        return None
    if getattr(settings, 'EMAIL_HOST', None):
        return None
    return (
        'Add SMTP details under Settings → Company, or configure EMAIL_HOST in your environment.'
    )
