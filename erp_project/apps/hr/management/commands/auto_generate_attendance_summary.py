"""Cron-friendly: recalculate AttendanceSummary for all active employees for a month."""
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.hr import hr_notifications
from apps.hr.attendance_utils import recalculate_summary_for_employee_month
from apps.hr.models import Employee
from apps.hr.models_extended import AttendanceSummary


class Command(BaseCommand):
    help = 'Rebuild attendance summary aggregates for a calendar month.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            default='',
            help='YYYY-MM (default: current month)',
        )
        parser.add_argument(
            '--email-hr',
            action='store_true',
            help='Email HR a digest of aggregate totals after refresh (requires HR notification email)',
        )

    def handle(self, *args, **options):
        raw = (options.get('month') or '').strip()
        if raw:
            y, m = [int(x) for x in raw.split('-')[:2]]
        else:
            t = date.today()
            y, m = t.year, t.month

        mf = date(y, m, 1)

        n = 0
        for emp in Employee.objects.filter(is_active=True, status='active'):
            recalculate_summary_for_employee_month(emp, y, m, skip_if_finalized=True)
            n += 1

        self.stdout.write(self.style.SUCCESS(f'{y}-{m:02d}: summaries refreshed for {n} employees'))

        if options.get('email_hr'):
            agg = AttendanceSummary.objects.filter(month=mf, is_active=True).aggregate(
                tp=Sum('total_present'),
                ta=Sum('total_absent'),
                tl=Sum('total_late'),
                th=Sum('total_half_day'),
            )
            body = (
                f'Aggregated attendance summary counts for {mf:%B %Y} (after refresh):\n\n'
                f"Sum of employees' present days: {agg['tp'] or 0}\n"
                f"Sum of absent days: {agg['ta'] or 0}\n"
                f"Sum of late counts: {agg['tl'] or 0}\n"
                f"Sum of half-day counts: {agg['th'] or 0}\n"
            )
            hr_notifications.send_monthly_attendance_digest(
                subject=f'[Al Najah HR] Attendance summary {mf:%Y-%m}',
                body=body,
            )
            self.stdout.write(self.style.SUCCESS('HR digest email queued (if SMTP/recipients configured).'))
