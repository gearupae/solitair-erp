"""Send automated birthday emails to employees (daily cron)."""
from django.core.management.base import BaseCommand

from apps.hr.birthday_email import send_todays_birthday_emails
from apps.hr.payroll_processing import get_payroll_settings


class Command(BaseCommand):
    help = 'Email active employees whose birthday is today (configure message in HR → Payroll settings).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Send even if disabled in settings or already sent this year.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List recipients only; do not send email.',
        )

    def handle(self, *args, **options):
        settings = get_payroll_settings()
        force = options['force']
        dry_run = options['dry_run']

        if not settings.birthday_email_enabled and not force and not dry_run:
            self.stdout.write(self.style.WARNING('Birthday emails are disabled in HR settings; skipped.'))
            return

        if dry_run:
            from apps.hr.birthday_email import employees_with_birthday_on

            for emp in employees_with_birthday_on():
                email = (emp.email or '').strip() or '(no email)'
                self.stdout.write(f'  {emp.employee_code} — {emp.full_name} — {email}')
            self.stdout.write(self.style.SUCCESS('Dry run complete.'))
            return

        result = send_todays_birthday_emails(force=force)
        if not result['enabled']:
            self.stdout.write(self.style.WARNING('Birthday emails disabled; skipped.'))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Birthday mail: {result['sent']} sent, {result['skipped']} skipped, "
                f"{result['failed']} failed ({result['candidates']} birthday(s) today)."
            )
        )
