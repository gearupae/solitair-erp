from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0036_invoiceitem_inventory_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='contract_body',
            field=models.TextField(
                blank=True,
                help_text='Rich-text contract body (HTML); shown on quotation/estimate and sales order.',
            ),
        ),
    ]
