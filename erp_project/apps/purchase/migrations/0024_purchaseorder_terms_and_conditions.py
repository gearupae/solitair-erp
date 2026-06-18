from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0023_po_vendor_retention'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseorder',
            name='terms_and_conditions',
            field=models.TextField(blank=True),
        ),
    ]
