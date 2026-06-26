from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0027_purchaserequestattachment_structured_quote'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaserequest',
            name='vendor_quote_analysis_running_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='When background quote AI started (shared across workers).',
            ),
        ),
        migrations.AddField(
            model_name='purchaserequest',
            name='vendor_quote_analysis_phase',
            field=models.CharField(
                blank=True,
                default='',
                max_length=255,
                help_text='Current background quote AI step label for the UI.',
            ),
        ),
        migrations.AddField(
            model_name='purchaserequest',
            name='vendor_quote_analysis_run_key',
            field=models.CharField(
                blank=True,
                default='',
                max_length=64,
                help_text='Analysis key in flight; avoids showing stale results during re-run.',
            ),
        ),
    ]
