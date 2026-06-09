from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0024_remove_material_requisition_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='lead_time_days',
            field=models.PositiveSmallIntegerField(
                default=7,
                help_text='Supplier lead time in days for reorder planning',
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='safety_stock_qty',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Safety stock buffer quantity for forecast reports',
            ),
        ),
        migrations.CreateModel(
            name='InventoryAIActionSummary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('cache_key', models.CharField(max_length=64, unique=True)),
                ('bullets', models.JSONField(default=list)),
                ('generated_at', models.DateTimeField()),
                ('raw_response', models.TextField(blank=True)),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name='%(app_label)s_%(class)s_created',
                    to='auth.user',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name='%(app_label)s_%(class)s_updated',
                    to='auth.user',
                )),
            ],
            options={
                'verbose_name_plural': 'Inventory AI action summaries',
                'ordering': ['-generated_at'],
            },
        ),
    ]
