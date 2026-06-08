from django.db import migrations, models


def seed_default_expense_types(apps, schema_editor):
    ItemSubGroupExpenseType = apps.get_model('settings_app', 'ItemSubGroupExpenseType')
    defaults = [
        ('Labour expenses', 1),
        ('Other expenses', 2),
        ('Materials', 3),
    ]
    for name, order in defaults:
        ItemSubGroupExpenseType.objects.get_or_create(
            name=name,
            defaults={'sort_order': order, 'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0023_project_conversion_approval'),
    ]

    operations = [
        migrations.CreateModel(
            name='ItemSubGroupExpenseType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Sub-group expense type',
                'verbose_name_plural': 'Sub-group expense types',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.RunPython(seed_default_expense_types, migrations.RunPython.noop),
    ]
