"""Persisted AI vendor quote comparison on purchase requests."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0024_purchaseorder_terms_and_conditions'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaserequest',
            name='vendor_quote_analysis',
            field=models.JSONField(
                blank=True,
                help_text='Persisted AI vendor quote comparison (survives cache restarts).',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='purchaserequest',
            name='vendor_quote_analysis_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='purchaserequest',
            name='vendor_quote_analysis_key',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Hash of PR + attachments; invalidates stored analysis when quotes change.',
                max_length=64,
            ),
        ),
    ]
