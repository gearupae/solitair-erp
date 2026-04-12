# Generated manually for consumables / inventory enhancements

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_consumable_request_enhancements'),
    ]

    operations = [
        migrations.CreateModel(
            name='StorageLocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('name', models.CharField(max_length=200, unique=True)),
                ('description', models.TextField(blank=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_storagelocation_created', to='auth.user')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_storagelocation_updated', to='auth.user')),
            ],
            options={
                'verbose_name': 'Storage location',
                'verbose_name_plural': 'Storage locations',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='item',
            name='barcode',
            field=models.CharField(blank=True, default='', max_length=120, verbose_name='Barcode / Asset Code'),
        ),
        migrations.AddField(
            model_name='item',
            name='brand',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='item',
            name='purchase_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='item',
            name='qr_code',
            field=models.ImageField(blank=True, null=True, upload_to='inventory/item_qr/'),
        ),
        migrations.AddField(
            model_name='item',
            name='serial_batch_number',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='item',
            name='storage_location',
            field=models.CharField(blank=True, default='', help_text='Shelf, rack, or free-text location (e.g. Shelf A3, Rack 2)', max_length=200),
        ),
        migrations.AddField(
            model_name='item',
            name='warranty_expiry',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='item',
            name='storage_location_master',
            field=models.ForeignKey(blank=True, help_text='Optional preset from the locations master list', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='items', to='inventory.storagelocation'),
        ),
    ]
