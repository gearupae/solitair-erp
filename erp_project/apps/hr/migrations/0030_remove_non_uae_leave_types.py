# Remove KSA and other non-UAE leave types from catalog.

from django.db import migrations


def remove_non_uae_leave_types(apps, schema_editor):
    LeaveType = apps.get_model('hr', 'LeaveType')
    LeaveType.objects.exclude(location='uae').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0029_project_role_designations'),
    ]

    operations = [
        migrations.RunPython(remove_non_uae_leave_types, migrations.RunPython.noop),
    ]
