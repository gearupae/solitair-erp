import uuid

from django.db import migrations, models


def populate_public_tokens(apps, schema_editor):
    Estimate = apps.get_model('sales', 'Estimate')
    for row in Estimate.objects.filter(public_view_token__isnull=True):
        row.public_view_token = uuid.uuid4()
        row.save(update_fields=['public_view_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0026_estimate_revision_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='creator_ip',
            field=models.GenericIPAddressField(
                blank=True,
                help_text='IP of the user who created this estimate; excluded from public view analytics.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='estimate',
            name='public_view_token',
            field=models.UUIDField(
                db_index=True,
                editable=False,
                help_text='Secret token for the customer-facing public quotation link.',
                null=True,
            ),
        ),
        migrations.RunPython(populate_public_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='estimate',
            name='public_view_token',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text='Secret token for the customer-facing public quotation link.',
                unique=True,
            ),
        ),
        migrations.CreateModel(
            name='EstimatePublicView',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_id', models.CharField(db_index=True, max_length=64)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, default='', max_length=500)),
                ('viewed_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    'excluded',
                    models.BooleanField(
                        default=False,
                        help_text='True when view is from the estimate creator IP (not counted in stats).',
                    ),
                ),
                (
                    'estimate',
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name='public_views',
                        to='sales.estimate',
                    ),
                ),
            ],
            options={
                'ordering': ['-viewed_at'],
                'indexes': [
                    models.Index(fields=['estimate', 'excluded'], name='sales_estim_estimat_8a1f2d_idx'),
                    models.Index(fields=['estimate', 'device_id'], name='sales_estim_estimat_4c9e81_idx'),
                ],
            },
        ),
    ]
