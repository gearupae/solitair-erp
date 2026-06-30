"""Add Other service expenses sub-group expense type for inventory service lines."""
from django.db import migrations


def add_other_service_expenses(apps, schema_editor):
    ItemSubGroupExpenseType = apps.get_model('settings_app', 'ItemSubGroupExpenseType')
    ItemSubGroupExpenseType.objects.get_or_create(
        name='Other service expenses',
        defaults={'sort_order': 4, 'is_active': True},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0035_cashflow_auto_sync_fields'),
    ]

    operations = [
        migrations.RunPython(add_other_service_expenses, migrations.RunPython.noop),
    ]
