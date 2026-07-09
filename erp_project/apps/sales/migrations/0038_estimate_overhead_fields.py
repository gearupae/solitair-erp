from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0037_estimate_contract_body'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='overhead_percent',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('10.00'),
                help_text='Default overhead % applied to line total cost when Apply OH is checked.',
                max_digits=5,
            ),
        ),
        migrations.AddField(
            model_name='estimateitem',
            name='uom',
            field=models.CharField(
                blank=True,
                choices=[
                    ('units', 'Units'),
                    ('ls', 'LS'),
                    ('rm', 'RM'),
                    ('litre', 'Litre'),
                    ('set', 'Set'),
                    ('mtr', 'Mtr'),
                ],
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='estimateitem',
            name='apply_overhead',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='estimateitem',
            name='installation_selling_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15),
        ),
        migrations.AddField(
            model_name='estimateitem',
            name='installation_profit_type',
            field=models.CharField(
                choices=[('none', 'None'), ('percent', 'Percent'), ('amount', 'Amount')],
                default='none',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='estimateitem',
            name='installation_profit_value',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15),
        ),
    ]
