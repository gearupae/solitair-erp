"""Cron-friendly: generate WPS SIF text for paid payrolls and store WPSMonthlyFile."""
from datetime import date

from django.core.management.base import BaseCommand

from apps.hr.wps_service import generate_and_store_wps_for_month


class Command(BaseCommand):
    help = 'Generate and store UAE WPS SIF content for a paid payroll month.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            default='',
            help='YYYY-MM (default: current month)',
        )
        parser.add_argument(
            '--output',
            type=str,
            default='',
            help='Optional path to write .txt file',
        )

    def handle(self, *args, **options):
        raw = (options.get('month') or '').strip()
        if raw:
            y, m = [int(x) for x in raw.split('-')[:2]]
        else:
            t = date.today()
            y, m = t.year, t.month
        mf = date(y, m, 1)

        content = generate_and_store_wps_for_month(mf)
        out = (options.get('output') or '').strip()
        if out:
            with open(out, 'w', encoding='utf-8') as fp:
                fp.write(content)
            self.stdout.write(self.style.SUCCESS(f'Wrote {out}'))
        self.stdout.write(self.style.SUCCESS(f'WPS SIF generated for {mf} ({len(content)} chars)'))
