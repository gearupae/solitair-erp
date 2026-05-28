from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0014_item_selling_price_bounds'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemgroup',
            name='hide_items_on_pdf',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When on, quotation PDFs show only this group name and consolidated '
                    'price (no individual line items) for estimate lines using this group name.'
                ),
            ),
        ),
    ]
