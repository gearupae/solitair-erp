"""Add cached extracted text on PR vendor quote attachments."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0025_purchaserequest_vendor_quote_analysis'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaserequestattachment',
            name='extracted_text',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Cached plain text from PDF/Excel for faster AI quote analysis.',
            ),
        ),
    ]
