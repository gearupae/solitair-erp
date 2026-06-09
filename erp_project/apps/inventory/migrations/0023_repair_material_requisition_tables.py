"""Repair missing MaterialRequisitionIssue tables if migration 0019 was partially applied."""
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _table_exists(schema_editor, table_name: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        tables = schema_editor.connection.introspection.table_names(cursor)
    return table_name in tables


def create_missing_requisition_tables(apps, schema_editor):
    if _table_exists(schema_editor, 'inventory_materialrequisitionissue'):
        return

    MaterialRequisitionIssue = apps.get_model('inventory', 'MaterialRequisitionIssue')
    MaterialRequisitionIssueLine = apps.get_model('inventory', 'MaterialRequisitionIssueLine')
    schema_editor.create_model(MaterialRequisitionIssue)
    schema_editor.create_model(MaterialRequisitionIssueLine)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0022_inventory_reporting_models'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(create_missing_requisition_tables, noop_reverse),
    ]
