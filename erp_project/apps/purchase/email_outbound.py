"""Helpers for outbound email using Company Settings SMTP or Django defaults."""
import re
import socket

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
    default = (getattr(settings, 'DEFAULT_FROM_EMAIL', None) or '').strip()
    if default:
        return default
    return 'webmaster@localhost'


def _smtp_host_is_valid(hostname: str) -> bool:
    host = (hostname or '').strip()
    if not host:
        return False
    if '.' not in host:
        return False
    return host.lower() not in ('smtp', 'mail', 'imap', 'pop')


def _company_smtp_configured(company) -> bool:
    return _smtp_host_is_valid(company.smtp_host or '')


def _env_smtp_configured() -> bool:
    host = (getattr(settings, 'EMAIL_HOST', None) or '').strip()
    if not host or host == 'localhost':
        return False
    return True


def _console_email_backend() -> bool:
    backend = getattr(settings, 'EMAIL_BACKEND', '') or ''
    return 'console' in backend


def outgoing_mail_configured(company) -> bool:
    """True when send is expected to work (company SMTP, env SMTP, or dev console)."""
    if _company_smtp_configured(company):
        return True
    if _env_smtp_configured():
        return True
    if _console_email_backend():
        return True
    return False


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


def email_sent_via_console(company) -> bool:
    """True when send uses the development console backend (no real SMTP)."""
    return _console_email_backend() and not _company_smtp_configured(company) and not _env_smtp_configured()


def smtp_host_configuration_error(company, exc: Exception | None = None) -> str | None:
    """User-facing hint when SMTP host is missing or not a valid hostname."""
    host = (company.smtp_host or '').strip()
    if not host:
        return None
    if '.' not in host or host.lower() in ('smtp', 'mail', 'imap', 'pop'):
        guess = suggested_smtp_host_for_username((company.smtp_username or '').strip())
        extra = f' For {company.smtp_username}, try: {guess}.' if guess else ''
        return (
            f'SMTP host "{host}" is not a valid server name. Open Settings → Company and set '
            f'the full hostname (e.g. smtp.office365.com).{extra}'
        )
    if isinstance(exc, socket.gaierror):
        guess = suggested_smtp_host_for_username((company.smtp_username or '').strip())
        extra = f' For {company.smtp_username}, try: {guess}.' if guess else ''
        return (
            f'Cannot resolve mail server "{host}" (DNS error). Check Settings → Company → '
            f'SMTP host spelling and your network.{extra}'
        )
    return None


def suggested_smtp_host_for_username(username: str) -> str | None:
    """Common SMTP hosts from mailbox domain (best-effort hint only)."""
    if '@' not in username:
        return None
    domain = username.split('@', 1)[1].lower()
    if domain in ('gmail.com', 'googlemail.com'):
        return 'smtp.gmail.com'
    if domain in ('outlook.com', 'hotmail.com', 'live.com'):
        return 'smtp.office365.com'
    # Microsoft 365 custom domains often use Office 365 SMTP
    return 'smtp.office365.com'


def outgoing_mail_hint(company):
    """Human hint when outbound email is not configured."""
    bad_host = smtp_host_configuration_error(company)
    if bad_host:
        return bad_host
    if outgoing_mail_configured(company):
        if _console_email_backend() and not _company_smtp_configured(company) and not _env_smtp_configured():
            return (
                'Development mode: emails are printed in the terminal where '
                'runserver is running (no SMTP). For real delivery, add SMTP under Settings → Company.'
            )
        return None
    return (
        'Add SMTP under Settings → Company (host, port, username, password), '
        'or set EMAIL_HOST in your server environment.'
    )
