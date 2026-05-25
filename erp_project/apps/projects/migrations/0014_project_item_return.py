from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0013_serial_model_tracking'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0013_serial_model_tracking'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProjectItemReturn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=2, default=Decimal('1'), max_digits=15)),
                ('returned_date', models.DateField()),
                ('notes', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='project_item_returns', to='inventory.item')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='item_returns', to='projects.project')),
                ('returned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='project_item_returns', to=settings.AUTH_USER_MODEL)),
                ('serial_number', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='project_returns', to='inventory.itemserialnumber')),
            ],
            options={
                'verbose_name': 'Project item return',
                'verbose_name_plural': 'Project item returns',
                'ordering': ['-returned_date', '-pk'],
            },
        ),
    ]
