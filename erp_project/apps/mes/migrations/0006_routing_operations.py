"""Routing operations — rename fields, add rate_per_hour and status."""

from decimal import Decimal

from django.db import migrations, models


def copy_work_center_rates(apps, schema_editor):
    RoutingOperation = apps.get_model('mes', 'RoutingOperation')
    for op in RoutingOperation.objects.select_related('work_center').iterator():
        if op.rate_per_hour == Decimal('0.00') and op.work_center_id:
            op.rate_per_hour = op.work_center.cost_per_hour
            op.save(update_fields=['rate_per_hour'])


class Migration(migrations.Migration):

    dependencies = [
        ('mes', '0005_manufacturing_costing'),
    ]

    operations = [
        migrations.RenameField(
            model_name='routingoperation',
            old_name='sequence_order',
            new_name='sequence',
        ),
        migrations.RenameField(
            model_name='routingoperation',
            old_name='standard_minutes',
            new_name='std_time_minutes',
        ),
        migrations.AddField(
            model_name='routingoperation',
            name='rate_per_hour',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Labour/machine rate (AED/hr); defaults from work center, editable per operation.',
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name='routingoperation',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('in_progress', 'In Progress'),
                    ('done', 'Done'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name='routingoperation',
            options={
                'ordering': ['production_order', 'sequence', 'id'],
                'verbose_name': 'Routing operation',
            },
        ),
        migrations.RunPython(copy_work_center_rates, migrations.RunPython.noop),
    ]
