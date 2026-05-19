"""B2B/B2C segment and mandatory B2B TRN + trade license uploads."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0007_customer_public_upload'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='business_segment',
            field=models.CharField(
                blank=True,
                choices=[('', '—'), ('b2b', 'B2B'), ('b2c', 'B2C')],
                default='',
                help_text='Required for accounts with type Customer: B2B or B2C.',
                max_length=10,
                verbose_name='Business type',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='trn_document',
            field=models.FileField(
                blank=True,
                help_text='B2B: upload VAT/TRN certificate (PDF or image).',
                max_length=500,
                upload_to='crm/customer_documents/%Y/%m/',
                verbose_name='TRN document',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='trade_license_document',
            field=models.FileField(
                blank=True,
                help_text='B2B: upload trade license (PDF or image).',
                max_length=500,
                upload_to='crm/customer_documents/%Y/%m/',
                verbose_name='Trade license',
            ),
        ),
    ]
