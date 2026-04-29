"""HR outbound notifications (payslip, alerts — uses Company SMTP when configured)."""
from __future__ import annotations

import logging

from django.core.mail import EmailMessage

from apps.purchase.email_outbound import company_outgoing_from_email, get_smtp_connection_or_default
from apps.settings_app.models import CompanySettings

logger = logging.getLogger(__name__)


def _company():
    return CompanySettings.get_settings()


def hr_recipient_list():
    from apps.hr.models_extended import PayrollSettings

    ps = PayrollSettings.objects.filter(pk=1).first()
    company = _company()
    addr = (ps.hr_notification_email if ps else '') or (company.email if company else '') or ''
    return [addr.strip()] if addr.strip() else []


def sync_wps_record_for_payroll(payroll):
    from apps.hr.models_extended import WPSRecord

    WPSRecord.objects.update_or_create(
        payroll=payroll,
        defaults={
            'employee': payroll.employee,
            'amount': payroll.net_salary,
            'payment_date': payroll.paid_date,
            'bank_account': payroll.paid_from_bank,
            'status': 'pending',
        },
    )


def send_payslip_email_for_payroll(payroll):
    """Email payslip PDF (paid payrolls only)."""
    from apps.hr.payslip_pdf import build_payslip_pdf, payslip_number

    company = _company()
    to = (payroll.employee.email or '').strip()
    if not to:
        return False

    try:
        pdf = build_payslip_pdf(payroll)
    except Exception as exc:
        logger.exception('Payslip PDF failed: %s', exc)
        return False

    subject = f'Payslip {payslip_number(payroll)} — {company.company_name if company else "Gearup"}'
    body = (
        f'Dear {payroll.employee.full_name},\n\n'
        f'Please find your payslip attached for {payroll.month.strftime("%B %Y")}.\n\n'
        'This is an automated message.'
    )

    try:
        connection = get_smtp_connection_or_default(company)
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=[to],
            connection=connection,
        )
        msg.attach(f'{payslip_number(payroll)}.pdf', pdf, 'application/pdf')
        msg.send(fail_silently=False)
        payroll.payslip_email_sent = True
        payroll.save(update_fields=['payslip_email_sent'])
        return True
    except Exception as exc:
        logger.warning('Could not email payslip: %s', exc)
        return False


def on_payroll_paid(payroll, request=None):
    """After salary paid: WPS row + payslip email to employee."""
    sync_wps_record_for_payroll(payroll)
    send_payslip_email_for_payroll(payroll)


def notify_department_manager(leave_request):
    dept = getattr(leave_request.employee, 'department', None)
    mgr = getattr(dept, 'manager', None) if dept else None
    to = (getattr(mgr, 'email', None) or '').strip() if mgr else ''
    if not to:
        notify_hr_leave_pending(leave_request)
        return
    company = _company()
    subject = f'Leave approval needed — {leave_request.employee.full_name}'
    body = (
        f'A leave request was submitted by {leave_request.employee.full_name} '
        f'({leave_request.employee.employee_code}).\n'
        f'Type: {leave_request.leave_type.name}\n'
        f'Dates: {leave_request.start_date} → {leave_request.end_date}\n'
        f'Please review in HR → Leave.\n'
    )
    try:
        connection = get_smtp_connection_or_default(company)
        EmailMessage(
            subject=f'{subject} — {company.company_name if company else "Gearup"}',
            body=body,
            from_email=company_outgoing_from_email(company),
            to=[to],
            connection=connection,
        ).send(fail_silently=False)
    except Exception as exc:
        logger.warning('Manager leave email failed: %s', exc)


def notify_hr_public_leave_submitted(leave_request):
    """Email HR inbox when an employee submits via the public leave form (no department manager step)."""
    recipients = hr_recipient_list()
    if not recipients:
        logger.info('No HR email — skip public leave notify.')
        return
    company = _company()
    emp = leave_request.employee
    ref = (leave_request.reference_number or str(leave_request.pk)).strip()
    subject = f'Public leave request — {emp.full_name} ({ref})'
    body = (
        f'A leave request was submitted via the public link.\n'
        f'Employee: {emp.full_name} ({emp.employee_code})\n'
        f'Type: {leave_request.leave_type.name}\n'
        f'Dates: {leave_request.start_date} → {leave_request.end_date}\n'
        f'Reference: {ref}\n'
    )
    try:
        connection = get_smtp_connection_or_default(company)
        EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=recipients,
            connection=connection,
        ).send(fail_silently=False)
    except Exception as exc:
        logger.warning('Public leave HR email failed: %s', exc)


def notify_hr_leave_pending(leave_request):
    recipients = hr_recipient_list()
    if not recipients:
        logger.info('No HR email — skip HR leave notify.')
        return
    company = _company()
    emp = leave_request.employee
    subject = f'Leave awaiting HR — {emp.full_name}'
    body = (
        f'Employee: {emp.full_name} ({emp.employee_code})\n'
        f'Type: {leave_request.leave_type.name}\n'
        f'Dates: {leave_request.start_date} → {leave_request.end_date}\n'
        f'Status: Pending HR final approval.\n'
    )
    try:
        connection = get_smtp_connection_or_default(company)
        EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=recipients,
            connection=connection,
        ).send(fail_silently=False)
    except Exception as exc:
        logger.warning('HR leave email failed: %s', exc)


def send_leave_decision(leave_request, approved: bool):
    emp = leave_request.employee
    to = (emp.email or '').strip()
    if not to:
        return
    company = _company()
    status_txt = 'approved' if approved else 'rejected'
    subject = f'Leave request {status_txt}'
    reason = (getattr(leave_request, 'rejection_reason', None) or '').strip()
    extra = f'\nReason: {reason}\n' if reason and not approved else ''
    body = (
        f'Dear {emp.full_name},\n\nYour leave request ({leave_request.leave_type}) '
        f'from {leave_request.start_date} to {leave_request.end_date} has been {status_txt}.{extra}'
    )
    try:
        connection = get_smtp_connection_or_default(company)
        EmailMessage(
            subject=f'{subject} — {company.company_name if company else "Gearup"}',
            body=body,
            from_email=company_outgoing_from_email(company),
            to=[to],
            connection=connection,
        ).send(fail_silently=False)
    except Exception as exc:
        logger.warning('Leave notification email failed: %s', exc)


def send_document_expiry_alert(*, employee_name: str, doc_label: str, expiry_date, days_left: int) -> None:
    """Single-document alert to HR (cron). Subject includes employee name."""
    recipients = hr_recipient_list()
    if not recipients:
        logger.info('No HR notification email configured; skip expiry alert.')
        return
    company = _company()
    tier = 'Critical (≤7 days)' if days_left <= 7 else 'Amber (8–30 days)'
    subject = f'⚠️ Document Expiry Alert — {employee_name}'
    body = (
        f'Employee: {employee_name}\n'
        f'Document: {doc_label}\n'
        f'Expiry date: {expiry_date}\n'
        f'Days remaining: {days_left}\n'
        f'Tier: {tier}\n'
    )
    try:
        connection = get_smtp_connection_or_default(company)
        EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=recipients,
            connection=connection,
        ).send(fail_silently=False)
    except Exception as exc:
        logger.warning('Expiry alert email failed: %s', exc)


def send_document_expiry_digest(subject: str, body: str):
    recipients = hr_recipient_list()
    if not recipients:
        logger.info('No HR notification email configured; skip expiry digest.')
        return
    company = _company()
    try:
        connection = get_smtp_connection_or_default(company)
        EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=recipients,
            connection=connection,
        ).send(fail_silently=False)
    except Exception as exc:
        logger.warning('Expiry digest email failed: %s', exc)


def send_monthly_attendance_digest(subject: str, body: str):
    send_document_expiry_digest(subject, body)


def send_monthly_attendance_report_email(
    subject: str,
    body: str,
    *,
    csv_bytes: bytes,
    attachment_filename: str,
) -> bool:
    """Email HR with monthly attendance summary CSV (cron)."""
    recipients = hr_recipient_list()
    if not recipients:
        logger.info('No HR notification email configured; skip attendance report email.')
        return False
    company = _company()
    try:
        connection = get_smtp_connection_or_default(company)
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=company_outgoing_from_email(company),
            to=recipients,
            connection=connection,
        )
        msg.attach(attachment_filename, csv_bytes, 'text/csv')
        msg.send(fail_silently=False)
        return True
    except Exception as exc:
        logger.warning('Monthly attendance report email failed: %s', exc)
        return False

