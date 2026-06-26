"""Add structured quote JSON cache on PR attachments."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0026_purchaserequestattachment_extracted_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaserequestattachment',
            name='structured_quote_json',
            field=models.JSONField(
                blank=True,
                help_text='Stage-1 AI extraction (schema fill) cached per attachment text.',
                null=True,
            ),
        ),
    ]
