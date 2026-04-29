"""Cron-friendly: export KSA GOSI contribution CSV for a payroll month."""
import csv
from datetime import date
from io import StringIO

from django.core.management.base import BaseCommand

from apps.hr.models_extended import GOSIRecord


class Command(BaseCommand):
    help = 'Export GOSI records for a month to CSV (stdout or --output path).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            default='',
            help='YYYY-MM (default: current month)',
        )
        parser.add_argument('--output', type=str, default='', help='File path (optional)')

    def handle(self, *args, **options):
        raw = (options.get('month') or '').strip()
        if raw:
            y, m = [int(x) for x in raw.split('-')[:2]]
        else:
            t = date.today()
            y, m = t.year, t.month
        mf = date(y, m, 1)

        qs = GOSIRecord.objects.filter(payroll__month=mf).select_related('payroll__employee')
        buffer = StringIO()
        w = csv.writer(buffer)
        w.writerow(['employee_code', 'employee_name', 'month', 'employee_contribution', 'employer_contribution'])
        for g in qs:
            e = g.payroll.employee
            w.writerow([e.employee_code, e.full_name, mf.isoformat(), g.employee_contribution, g.employer_contribution])
        text = buffer.getvalue()

        out_path = (options.get('output') or '').strip()
        if out_path:
            with open(out_path, 'w', encoding='utf-8', newline='') as fp:
                fp.write(text)
            self.stdout.write(self.style.SUCCESS(f'Wrote {out_path} ({qs.count()} rows)'))
        else:
            self.stdout.write(text)
