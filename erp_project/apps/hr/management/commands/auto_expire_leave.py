"""Expire unused non–carry-forward balances — stub."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Expire balances that do not roll forward (stub).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('auto_expire_leave: stub — no changes.'))
