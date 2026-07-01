"""Remove Oracle-imported production orders (ORC-* po_number prefix)."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.mes.models import ProductionOrder


def purge_oracle_import_orders() -> int:
    """Hard-delete production orders pulled from Oracle mock (ORC-* prefix)."""
    qs = ProductionOrder.objects.filter(po_number__startswith='ORC-')
    count, _ = qs.delete()
    return count


class Command(BaseCommand):
    help = 'Delete Oracle-imported production orders (po_number starting with ORC-).'

    def handle(self, *args, **options):
        with transaction.atomic():
            deleted = purge_oracle_import_orders()
        if deleted:
            self.stdout.write(self.style.SUCCESS(f'Removed {deleted} Oracle-import row(s) (ORC-* orders).'))
        else:
            self.stdout.write('No ORC-* production orders found.')
