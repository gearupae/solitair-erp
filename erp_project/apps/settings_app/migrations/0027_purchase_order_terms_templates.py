from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0026_inventory_reporting_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='PurchaseOrderTermsTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('body', models.TextField(blank=True)),
                ('is_default', models.BooleanField(
                    default=False,
                    help_text='Pre-selected when creating a new purchase order.',
                )),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Purchase order terms template',
                'verbose_name_plural': 'Purchase order terms templates',
                'ordering': ['sort_order', 'name'],
            },
        ),
    ]
