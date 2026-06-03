"""Seed VAT treatment codes and map legacy consumable statuses."""
from django.db import migrations


def seed_vat_treatments(apps, schema_editor):
    InterEntityVatTreatment = apps.get_model('inventory', 'InterEntityVatTreatment')
    codes = [
        ('intra_emirate', 'Intra-emirate'),
        ('inter_emirate', 'Inter-emirate'),
        ('designated_zone', 'Designated Zone'),
        ('gcc_cross_border', 'GCC Cross-border'),
        ('out_of_scope', 'Out of Scope'),
    ]
    for code, name in codes:
        InterEntityVatTreatment.objects.get_or_create(code=code, defaults={'name': name})


def map_consumable_statuses(apps, schema_editor):
    ConsumableRequest = apps.get_model('inventory', 'ConsumableRequest')
    ConsumableRequestItem = apps.get_model('inventory', 'ConsumableRequestItem')
    for req in ConsumableRequest.objects.filter(status='dispensed'):
        req.status = 'issued'
        req.save(update_fields=['status'])
    for req in ConsumableRequest.objects.filter(status='pending'):
        if not req.submitted_at:
            req.status = 'submitted'
            req.save(update_fields=['status'])
    for line in ConsumableRequestItem.objects.filter(qty_issued__gt=0):
        if line.qty_approved is None:
            line.qty_approved = line.quantity
            line.save(update_fields=['qty_approved'])


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0019_procurement_models'),
    ]

    operations = [
        migrations.RunPython(seed_vat_treatments, migrations.RunPython.noop),
        migrations.RunPython(map_consumable_statuses, migrations.RunPython.noop),
    ]
