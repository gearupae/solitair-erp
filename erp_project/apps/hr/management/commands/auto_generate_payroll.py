"""Cron-friendly: create draft Payroll rows for active employees for a calendar month."""
from django.core.management.base import BaseCommand

from apps.hr.payroll_generation_service import generate_draft_payrolls_for_month


class Command(BaseCommand):
    help = 'Create draft payroll entries for employees for one month (skips existing employee+month).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            default='',
            help='YYYY-MM (default: current calendar month)',
        )
        parser.add_argument(
            '--company',
            type=int,
            default=None,
            help='Only employees of this Company entity ID',
        )
        parser.add_argument(
            '--location',
            type=str,
            default='',
            help='UAE or KSA — filter employees by Employee.location',
        )

    def handle(self, *args, **options):
        raw = (options.get('month') or '').strip()
        if raw:
            y, m = [int(x) for x in raw.split('-')[:2]]
        else:
            from datetime import date

            t = date.today()
            y, m = t.year, t.month

        company_id = options.get('company')
        loc = (options.get('location') or '').strip().upper()
        location = loc if loc in ('UAE', 'KSA') else None

        created, suffix = generate_draft_payrolls_for_month(y, m, company_id=company_id, location=location)
        self.stdout.write(self.style.SUCCESS(f'Generated {created} payroll drafts for {suffix}'))
