"""Automated employee birthday emails."""
from __future__ import annotations

import logging
import re
from datetime import date

from django.core.mail import EmailMessage
from django.db.models.functions import ExtractDay, ExtractMonth
from django.utils import timezone

from apps.hr.models import Employee
from apps.hr.models_extended import EmployeeBirthdayEmailLog, PayrollSettings
from apps.hr.payroll_processing import get_payroll_settings
from apps.purchase.email_outbound import company_outgoing_from_email, get_smtp_connection_or_default
from apps.settings_app.models import CompanySettings

logger = logging.getLogger(__name__)

PLACEHOLDER_HELP = (
    '{first_name}, {last_name}, {full_name}, {employee_code}, '
    '{company_name}, {department}, {designation}, {age}'
)


def birthday_template_context(employee, *, company_name: str) -> dict[str, str]:
    age = ''
    if employee.date_of_birth:
        today = timezone.localdate()
        years = today.year - employee.date_of_birth.year
        if (today.month, today.day) < (employee.date_of_birth.month, employee.date_of_birth.day):
            years -= 1
        if years >= 0:
            age = str(years)
    return {
        'first_name': employee.first_name or '',
        'last_name': employee.last_name or '',
        'full_name': employee.full_name,
        'employee_code': employee.employee_code or '',
        'company_name': company_name,
        'department': employee.department.name if employee.department_id else '',
        'designation': employee.designation.name if employee.designation_id else '',
        'age': age,
    }


def render_birthday_template(template: str, employee, *, company_name: str) -> str:
    text = template or ''
    ctx = birthday_template_context(employee, company_name=company_name)

    def _replace(match):
        key = match.group(1)
        return ctx.get(key, match.group(0))

    return re.sub(r'\{(\w+)\}', _replace, text)


def employees_with_birthday_on(day: date | None = None):
    """Active employees whose birthday falls on the given calendar day."""
    day = day or timezone.localdate()
    return (
        Employee.objects.filter(
            is_active=True,
            status='active',
            date_of_birth__isnull=False,
        )
        .annotate(birth_month=ExtractMonth('date_of_birth'), birth_day=ExtractDay('date_of_birth'))
        .filter(birth_month=day.month, birth_day=day.day)
        .select_related('department', 'designation', 'company')
        .order_by('employee_code')
    )


def already_sent_this_year(employee_id: int, year: int) -> bool:
    return EmployeeBirthdayEmailLog.objects.filter(
        employee_id=employee_id,
        calendar_year=year,
    ).exists()


def send_birthday_email(employee, *, settings: PayrollSettings | None = None, force: bool = False) -> bool:
    """Send birthday email to one employee. Returns True if sent."""
    settings = settings or get_payroll_settings()
    if not settings.birthday_email_enabled and not force:
        return False

    to = (employee.email or '').strip()
    if not to:
        logger.info('Skip birthday email — no address for %s', employee.employee_code)
        return False

    today = timezone.localdate()
    if not force and already_sent_this_year(employee.pk, today.year):
        logger.info('Birthday email already sent for %s in %s', employee.employee_code, today.year)
        return False

    company = CompanySettings.get_settings()
    company_name = (company.company_name if company else '') or 'Gearup ERP'

    subject = render_birthday_template(
        settings.birthday_email_subject or 'Happy Birthday, {first_name}!',
        employee,
        company_name=company_name,
    )
    body = render_birthday_template(
        settings.birthday_email_body or '',
        employee,
        company_name=company_name,
    )

    try:
        connection = get_smtp_connection_or_default(company)
        EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=[to],
            connection=connection,
        ).send(fail_silently=False)
    except Exception as exc:
        logger.warning('Birthday email to %s failed: %s', to, exc)
        return False

    EmployeeBirthdayEmailLog.objects.get_or_create(
        employee=employee,
        calendar_year=today.year,
    )
    return True


def send_todays_birthday_emails(*, force: bool = False) -> dict:
    """Send birthday emails for all eligible employees today."""
    settings = get_payroll_settings()
    if not settings.birthday_email_enabled and not force:
        return {'enabled': False, 'sent': 0, 'skipped': 0, 'failed': 0, 'candidates': 0}

    today = timezone.localdate()
    candidates = list(employees_with_birthday_on(today))
    sent = skipped = failed = 0

    for employee in candidates:
        if not force and already_sent_this_year(employee.pk, today.year):
            skipped += 1
            continue
        if send_birthday_email(employee, settings=settings, force=force):
            sent += 1
        else:
            failed += 1

    return {
        'enabled': True,
        'sent': sent,
        'skipped': skipped,
        'failed': failed,
        'candidates': len(candidates),
    }
