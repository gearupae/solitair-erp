# Seed 2026 public holidays (UAE and KSA separate rows).

from django.db import migrations


def forwards(apps, schema_editor):
    Holiday = apps.get_model('hr', 'Holiday')
    from apps.hr.management.commands.setup_holidays import seed_public_holidays

    seed_public_holidays(Holiday, 2026)


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0024_seed_extended_leave_types_uae_ksa'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
