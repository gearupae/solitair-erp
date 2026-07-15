from pathlib import Path

from django.db import migrations, models

QUOTE_EXTENSIONS = {'.pdf', '.xlsx', '.xls'}


def classify_existing_attachments(apps, schema_editor):
    Attachment = apps.get_model('purchase', 'PurchaseRequestAttachment')
    for att in Attachment.objects.all().iterator():
        ext = Path(att.filename or att.file.name).suffix.lower()
        has_quote_data = bool(
            (att.vendor or '').strip()
            or att.total_price is not None
            or (att.extracted_text or '').strip()
            or att.structured_quote_json
        )
        if ext in QUOTE_EXTENSIONS or has_quote_data:
            att.kind = 'vendor_quote'
        else:
            att.kind = 'supporting'
        att.save(update_fields=['kind'])


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0032_vendor_bill_approval'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaserequestattachment',
            name='kind',
            field=models.CharField(
                choices=[
                    ('supporting', 'Supporting document'),
                    ('vendor_quote', 'Vendor quote'),
                ],
                default='supporting',
                max_length=20,
            ),
        ),
        migrations.RunPython(classify_existing_attachments, migrations.RunPython.noop),
    ]
