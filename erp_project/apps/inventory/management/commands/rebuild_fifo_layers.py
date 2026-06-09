"""Management command to rebuild FIFO cost layers from stock movements."""
from django.core.management.base import BaseCommand

from apps.inventory.services.fifo_service import rebuild_fifo_layers


class Command(BaseCommand):
    help = 'Rebuild InventoryCostLayer rows from stock movement history (FIFO).'

    def add_arguments(self, parser):
        parser.add_argument('--item-id', type=int, default=None)
        parser.add_argument('--warehouse-id', type=int, default=None)

    def handle(self, *args, **options):
        n = rebuild_fifo_layers(
            item_id=options.get('item_id'),
            warehouse_id=options.get('warehouse_id'),
        )
        self.stdout.write(self.style.SUCCESS(f'FIFO rebuild complete: {n} layers created.'))
