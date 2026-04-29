"""Cron-friendly: auto-mark absent for active employees on a working day with no attendance row."""
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.hr.attendance_utils import auto_mark_absent_for_date


class Command(BaseCommand):
    help = 'Mark absent for missing attendance on a UAE working day (default: yesterday).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='',
            help='YYYY-MM-DD (default: yesterday)',
        )

    def handle(self, *args, **options):
        raw = (options.get('date') or '').strip()
        if raw:
            target = date.fromisoformat(raw[:10])
        else:
            target = date.today() - timedelta(days=1)

        n = auto_mark_absent_for_date(target)
        self.stdout.write(self.style.SUCCESS(f'{target}: absent rows created = {n}'))
