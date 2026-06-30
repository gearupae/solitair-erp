# Generated manually

from decimal import Decimal

from django.db import migrations, models


def backfill_selling_cost(apps, schema_editor):
    EstimateItem = apps.get_model('sales', 'EstimateItem')
    for item in EstimateItem.objects.all().only('pk', 'rate', 'unit_price', 'selling_cost'):
        selling = item.rate if item.rate and item.rate > 0 else (item.unit_price or Decimal('0'))
        EstimateItem.objects.filter(pk=item.pk).update(selling_cost=selling)


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0033_estimate_show_installation_cost_on_pdf'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimateitem',
            name='selling_cost',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Unit selling price entered by user; profit is derived from unit cost.',
                max_digits=15,
            ),
        ),
        migrations.AlterField(
            model_name='estimateitem',
            name='installation_cost',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Unit installation cost per unit (not included in line net; consolidated in expenses).',
                max_digits=15,
            ),
        ),
        migrations.AlterField(
            model_name='estimateitem',
            name='profit_value',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Auto-calculated from selling cost vs unit cost (% or AED/u).',
                max_digits=15,
            ),
        ),
        migrations.AlterField(
            model_name='estimateitem',
            name='rate',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Legacy mirror of selling cost (per unit).',
                max_digits=15,
            ),
        ),
        migrations.AlterField(
            model_name='estimateitem',
            name='unit_price',
            field=models.DecimalField(
                decimal_places=2,
                help_text='Unit cost per unit (before profit).',
                max_digits=15,
            ),
        ),
        migrations.RunPython(backfill_selling_cost, migrations.RunPython.noop),
    ]
