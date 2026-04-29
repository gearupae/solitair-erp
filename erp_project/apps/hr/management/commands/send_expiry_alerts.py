"""Daily consolidated email for HR document expiry (cron)."""
from datetime import date

from django.core.management.base import BaseCommand

from apps.hr.expiry_alerts import _build_raw_alerts, build_daily_email_body, recipient_emails
from apps.hr.hr_notifications import _company
from apps.purchase.email_outbound import company_outgoing_from_email, get_smtp_connection_or_default
from django.core.mail import EmailMessage


class Command(BaseCommand):
    help = 'Send one consolidated daily email for document expiry (amber/red/expired only).'

    def handle(self, *args, **options):
        rows = _build_raw_alerts()
        if not rows:
            self.stdout.write(self.style.SUCCESS('No documents require attention; email skipped.'))
            return

        recipients = recipient_emails()
        if not recipients:
            self.stdout.write(self.style.WARNING('No HR recipients configured (Payroll HR email / ADMINS); skipped.'))
            return

        subject = f'📋 Daily Document Expiry Report — {date.today():%Y-%m-%d}'
        body = build_daily_email_body(rows)

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
            self.stderr.write(self.style.ERROR(f'Email failed: {exc}'))
            raise

        self.stdout.write(self.style.SUCCESS(f'Sent daily expiry report to {len(recipients)} recipient(s).'))
