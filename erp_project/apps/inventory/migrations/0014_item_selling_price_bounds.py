from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0013_serial_model_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='minimum_selling_price',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Lowest allowed selling price for this item',
                max_digits=15,
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='maximum_selling_price',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Highest allowed selling price for this item (0 = no cap)',
                max_digits=15,
            ),
        ),
    ]
