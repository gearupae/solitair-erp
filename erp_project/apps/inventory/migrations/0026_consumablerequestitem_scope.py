from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0025_ai_forecast_enhancements'),
    ]

    operations = [
        migrations.AddField(
            model_name='consumablerequestitem',
            name='additional_qty_at_request',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Qty above proposed (new item or excess quantity).',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='consumablerequestitem',
            name='proposed_qty_at_request',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Proposed qty on project Items list when request was submitted.',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='consumablerequestitem',
            name='scope_classification',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
