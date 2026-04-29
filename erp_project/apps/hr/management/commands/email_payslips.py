"""Cron-friendly: email payslip PDFs for paid payrolls in a month (idempotent per run; use sparingly)."""
from datetime import date

from django.core.management.base import BaseCommand

from apps.hr.models import Payroll
from apps.hr.hr_notifications import send_payslip_email_for_payroll


class Command(BaseCommand):
    help = 'Send payslip PDF emails for paid payroll rows in a calendar month.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            default='',
            help='YYYY-MM (default: current month)',
        )

    def handle(self, *args, **options):
        raw = (options.get('month') or '').strip()
        if raw:
            y, m = [int(x) for x in raw.split('-')[:2]]
        else:
            t = date.today()
            y, m = t.year, t.month
        mf = date(y, m, 1)

        qs = Payroll.objects.filter(month=mf, status='paid', is_active=True).select_related('employee')
        ok = 0
        for pr in qs:
            if send_payslip_email_for_payroll(pr):
                ok += 1

        self.stdout.write(self.style.SUCCESS(f'Month {mf}: payslip emails attempted for {ok}/{qs.count()} payrolls'))
