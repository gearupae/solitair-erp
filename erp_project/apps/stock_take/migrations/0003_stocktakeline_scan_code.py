from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock_take', '0002_stocktakesession_public_scan_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='stocktakeline',
            name='scan_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Barcode / QR / label value scanned at the shelf. If empty, scans match SKU.',
                max_length=200,
            ),
        ),
    ]
