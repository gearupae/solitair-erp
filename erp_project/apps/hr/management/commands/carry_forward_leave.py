"""Year-end carry-forward for annual leave (cap 30 days) — extend with business rules."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Calculate annual leave carry-forward into next year (stub — implement caps per policy).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('carry_forward_leave: logic placeholder — no DB changes yet.'))
