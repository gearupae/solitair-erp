"""Email HR a CSV of attendance summaries for a calendar month (default: previous month)."""
import csv
from datetime import date, timedelta
from io import StringIO

from django.core.management.base import BaseCommand

from apps.hr import hr_notifications
from apps.hr.models import AttendanceSummary


class Command(BaseCommand):
    help = 'Email HR the monthly attendance summary export as CSV (requires HR notification email).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            default='',
            help='YYYY-MM (default: previous calendar month)',
        )

    def handle(self, *args, **options):
        raw = (options.get('month') or '').strip()
        if raw:
            y, m = [int(x) for x in raw.split('-')[:2]]
        else:
            today = date.today()
            first_this = date(today.year, today.month, 1)
            prev_end = first_this - timedelta(days=1)
            y, m = prev_end.year, prev_end.month

        mf = date(y, m, 1)
        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                'employee_code',
                'name',
                'present',
                'absent',
                'late',
                'half_day',
                'holiday',
                'overtime_hrs',
                'total_hrs',
                'absent_deduction_days',
                'finalized',
            ]
        )
        qs = AttendanceSummary.objects.filter(month=mf, is_active=True).select_related('employee').order_by(
            'employee__employee_code'
        )
        rows = list(qs)
        row_count = len(rows)
        for summ in rows:
            w.writerow(
                [
                    summ.employee.employee_code,
                    summ.employee.full_name,
                    summ.total_present,
                    summ.total_absent,
                    summ.total_late,
                    summ.total_half_day,
                    summ.total_holidays,
                    summ.total_overtime_hours,
                    summ.total_working_hours,
                    summ.absent_deduction_days,
                    'yes' if summ.is_finalized else 'no',
                ]
            )
        csv_bytes = buf.getvalue().encode('utf-8')
        subject = f'[Gearup HR] Attendance summary CSV {mf:%Y-%m}'
        body = (
            f'Monthly attendance summary export for {mf:%B %Y}.\n'
            f'Rows: {row_count}.\n'
            'See attached CSV.'
        )
        fn = f'attendance_summary_{y}_{m:02d}.csv'
        ok = hr_notifications.send_monthly_attendance_report_email(subject, body, csv_bytes=csv_bytes, attachment_filename=fn)
        if ok:
            self.stdout.write(self.style.SUCCESS(f'Emailed HR: {fn}'))
        else:
            self.stdout.write(self.style.WARNING('No HR email configured or send failed — CSV not emailed.'))
