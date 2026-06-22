from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0026_consumablerequestitem_scope'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InventoryAIHubCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cache_key', models.CharField(max_length=128, unique=True)),
                ('tab', models.CharField(db_index=True, max_length=40)),
                ('payload', models.JSONField(default=dict)),
                ('generated_at', models.DateTimeField()),
            ],
            options={
                'ordering': ['-generated_at'],
            },
        ),
        migrations.CreateModel(
            name='InventoryComplianceFlag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('check_code', models.CharField(db_index=True, max_length=60)),
                ('severity', models.CharField(
                    choices=[('high', 'High'), ('medium', 'Med'), ('low', 'Low')],
                    default='medium',
                    max_length=10,
                )),
                ('issue', models.CharField(max_length=300)),
                ('sku', models.CharField(blank=True, default='', max_length=80)),
                ('value_impact', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=15)),
                ('suggested_fix', models.TextField(blank=True, default='')),
                ('run_key', models.CharField(db_index=True, default='', max_length=64)),
                ('is_resolved', models.BooleanField(default=False)),
                (
                    'created_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_created',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'item',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='compliance_flags',
                        to='inventory.item',
                    ),
                ),
                (
                    'updated_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_updated',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'warehouse',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='compliance_flags',
                        to='inventory.warehouse',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='inventorycomplianceflag',
            index=models.Index(fields=['run_key', 'check_code'], name='inv_comp_run_check_idx'),
        ),
        migrations.AddIndex(
            model_name='inventorycomplianceflag',
            index=models.Index(fields=['is_resolved', '-created_at'], name='inv_comp_resolved_idx'),
        ),
    ]
