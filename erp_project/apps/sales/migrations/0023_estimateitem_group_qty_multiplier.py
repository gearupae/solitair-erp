from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0022_estimate_show_brand_name_on_pdf'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimateitem',
            name='group_qty_multiplier',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('1.00'),
                help_text='Multiplied with line qty for all items sharing this group name.',
                max_digits=10,
            ),
        ),
    ]
