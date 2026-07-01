"""Remove Oracle-imported ORC-* production orders from the database."""

from django.db import migrations


def purge_oracle_orders(apps, schema_editor):
    ProductionOrder = apps.get_model('mes', 'ProductionOrder')
    ProductionOrder.objects.filter(po_number__startswith='ORC-').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mes', '0006_routing_operations'),
    ]

    operations = [
        migrations.RunPython(purge_oracle_orders, migrations.RunPython.noop),
    ]
