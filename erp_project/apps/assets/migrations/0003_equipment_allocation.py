# Generated manually for equipment allocation

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0023_inspection_checklist'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('assets', '0002_alter_assetdepreciation_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='fixedasset',
            name='cost_per_hour',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Internal charge-out rate per hour for project costing', max_digits=12),
        ),
        migrations.AddField(
            model_name='fixedasset',
            name='current_location',
            field=models.CharField(blank=True, help_text='Current site or warehouse location', max_length=200),
        ),
        migrations.AddField(
            model_name='fixedasset',
            name='operational_status',
            field=models.CharField(choices=[('available', 'Available'), ('allocated', 'Allocated'), ('maintenance', 'Under Maintenance')], db_index=True, default='available', max_length=20),
        ),
        migrations.AddField(
            model_name='fixedasset',
            name='ownership_type',
            field=models.CharField(choices=[('owned', 'Owned'), ('rented', 'Rented')], default='owned', max_length=20),
        ),
        migrations.AddField(
            model_name='fixedasset',
            name='rental_rate_per_day',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Daily rental rate when ownership is Rented', max_digits=12),
        ),
        migrations.CreateModel(
            name='EquipmentAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('start_date', models.DateField()),
                ('expected_end_date', models.DateField(blank=True, null=True)),
                ('actual_end_date', models.DateField(blank=True, null=True)),
                ('rate_per_hour', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('rate_per_day', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('hours_used', models.DecimalField(blank=True, decimal_places=2, help_text='Actual hours used; auto-estimated from days if blank', max_digits=10, null=True)),
                ('status', models.CharField(choices=[('active', 'Active'), ('returned', 'Returned'), ('transferred', 'Transferred')], db_index=True, default='active', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('allocated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment_allocations_created', to=settings.AUTH_USER_MODEL)),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='allocations', to='assets.fixedasset')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='equipment_allocations', to='projects.project')),
                ('returned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment_allocations_returned', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-start_date', '-pk'],
            },
        ),
        migrations.CreateModel(
            name='EquipmentMaintenanceLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('reason', models.TextField()),
                ('blocks_allocation', models.BooleanField(default=True)),
                ('cleared_at', models.DateTimeField(blank=True, null=True)),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='maintenance_logs', to='assets.fixedasset')),
                ('cleared_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment_maintenance_cleared', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created', to=settings.AUTH_USER_MODEL)),
                ('flagged_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment_maintenance_flagged', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='EquipmentMovementLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('from_location', models.CharField(blank=True, max_length=200)),
                ('to_location', models.CharField(blank=True, max_length=200)),
                ('movement_type', models.CharField(choices=[('allocate', 'Allocated to Project'), ('return', 'Returned to Warehouse'), ('transfer', 'Transferred Between Projects'), ('maintenance', 'Sent to Maintenance'), ('maintenance_clear', 'Maintenance Cleared')], max_length=30)),
                ('notes', models.TextField(blank=True)),
                ('moved_at', models.DateTimeField(auto_now_add=True)),
                ('allocation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='movement_logs', to='assets.equipmentallocation')),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movement_logs', to='assets.fixedasset')),
                ('from_project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment_movements_from', to='projects.project')),
                ('moved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('to_project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment_movements_to', to='projects.project')),
            ],
            options={
                'ordering': ['-moved_at'],
            },
        ),
        migrations.CreateModel(
            name='RentalCostLedger',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('hours_used', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10)),
                ('days_used', models.IntegerField(default=0)),
                ('rate_per_hour', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('rate_per_day', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('total_cost', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('cost_type', models.CharField(default='owned', max_length=20)),
                ('allocation', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='cost_ledger', to='assets.equipmentallocation')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
