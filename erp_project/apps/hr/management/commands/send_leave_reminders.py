"""Email reminders for manager approvals older than N days."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.hr.models import LeaveRequest


class Command(BaseCommand):
    help = 'Notify department managers about stale pending_manager leave requests.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=2)
        qs = LeaveRequest.objects.filter(status='pending_manager', created_at__lt=cutoff, is_active=True)
        n = qs.count()
        self.stdout.write(self.style.WARNING(f'{n} stale pending_manager requests (email integration TODO).'))
