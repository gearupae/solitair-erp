"""Allow HR Manager role to view purchase requests (PR approvers)."""
from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    ModulePermission = apps.get_model('settings_app', 'ModulePermission')

    role = Role.objects.filter(code='hr_manager', is_active=True).first()
    if not role:
        return
    ModulePermission.objects.update_or_create(
        role=role,
        module='purchase',
        defaults={
            'can_view': True,
            'can_create': False,
            'can_edit': False,
            'can_delete': False,
        },
    )


def backwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    ModulePermission = apps.get_model('settings_app', 'ModulePermission')

    role = Role.objects.filter(code='hr_manager').first()
    if not role:
        return
    ModulePermission.objects.filter(role=role, module='purchase').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0040_module_request_sent_email'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
