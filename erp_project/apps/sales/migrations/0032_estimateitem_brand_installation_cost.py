from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0031_estimate_reference_sales_engineer'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimateitem',
            name='brand',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='estimateitem',
            name='installation_cost',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Installation cost per unit (added to line net: qty × installation cost).',
                max_digits=15,
            ),
        ),
    ]
