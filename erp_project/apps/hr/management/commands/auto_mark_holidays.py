"""Cron-friendly: stamp holiday attendance rows for employees on configured holidays."""
from datetime import date

from django.core.management.base import BaseCommand

from apps.hr.attendance_utils import auto_mark_holidays_for_date


class Command(BaseCommand):
    help = 'Create/update holiday attendance rows for a calendar date (default: today).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='',
            help='YYYY-MM-DD (default: today)',
        )

    def handle(self, *args, **options):
        raw = (options.get('date') or '').strip()
        target = date.fromisoformat(raw[:10]) if raw else date.today()
        n = auto_mark_holidays_for_date(target)
        self.stdout.write(self.style.SUCCESS(f'{target}: holiday rows touched = {n}'))
