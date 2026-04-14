import uuid

from django.db import migrations, models


def assign_public_tokens(apps, schema_editor):
    Session = apps.get_model('stock_take', 'StockTakeSession')
    for row in Session.objects.all():
        row.public_scan_token = uuid.uuid4()
        row.save(update_fields=['public_scan_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('stock_take', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='stocktakesession',
            name='public_scan_token',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(assign_public_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='stocktakesession',
            name='public_scan_token',
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
            ),
        ),
    ]
