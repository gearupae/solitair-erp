"""Backfill employee.designation from linked ERP user roles."""

from django.db import migrations


def sync_employee_designations(apps, schema_editor):
    from apps.hr.designation_utils import sync_all_designations_from_user_roles

    sync_all_designations_from_user_roles()


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0045_procurement_department_manager_ahmed'),
        ('settings_app', '0045_modulefeaturepermission'),
    ]

    operations = [
        migrations.RunPython(sync_employee_designations, migrations.RunPython.noop),
    ]
