"""Public quotation share token, creator IP, and view analytics."""

import uuid

from django.db import migrations, models
import django.db.models.deletion


def assign_public_tokens(apps, schema_editor):
    Estimate = apps.get_model('sales', 'Estimate')
    for est in Estimate.objects.filter(
        status__in=('quotation_won', 'under_negotiation'),
        public_share_token__isnull=True,
        is_active=True,
    ):
        est.public_share_token = uuid.uuid4()
        est.save(update_fields=['public_share_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0027_estimate_sales_order_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='public_share_token',
            field=models.UUIDField(
                blank=True,
                editable=False,
                help_text='Token for the public quotation link (quot won / under negotiation).',
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='estimate',
            name='quotation_creator_ip',
            field=models.GenericIPAddressField(
                blank=True,
                help_text='IP when the estimate was created; excluded from public link view counts.',
                null=True,
            ),
        ),
        migrations.CreateModel(
            name='EstimatePublicView',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('viewed_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.TextField(blank=True, default='')),
                ('device_key', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('is_counted', models.BooleanField(
                    default=True,
                    help_text='False when the viewer IP matches the quotation creator IP.',
                )),
                ('estimate', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='public_views',
                    to='sales.estimate',
                )),
            ],
            options={
                'verbose_name': 'Public quotation view',
                'verbose_name_plural': 'Public quotation views',
                'ordering': ['-viewed_at'],
            },
        ),
        migrations.RunPython(assign_public_tokens, migrations.RunPython.noop),
    ]
