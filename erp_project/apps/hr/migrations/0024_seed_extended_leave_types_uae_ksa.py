# Re-sync leave type catalog (UAE + KSA). Idempotent.

from django.db import migrations


def forwards(apps, schema_editor):
    LeaveType = apps.get_model('hr', 'LeaveType')
    from apps.hr.management.commands.setup_leave_types import seed_leave_types

    seed_leave_types(LeaveType)


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0023_payrolltemplate_basic_optional'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
