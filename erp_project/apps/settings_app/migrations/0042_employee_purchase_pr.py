"""Allow Employee role to view and create purchase requests."""
from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    ModulePermission = apps.get_model('settings_app', 'ModulePermission')

    role = Role.objects.filter(code='employee', is_active=True).first()
    if not role:
        return
    ModulePermission.objects.update_or_create(
        role=role,
        module='purchase',
        defaults={
            'can_view': True,
            'can_create': True,
            'can_edit': False,
            'can_delete': False,
        },
    )


def backwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    ModulePermission = apps.get_model('settings_app', 'ModulePermission')

    role = Role.objects.filter(code='employee').first()
    if not role:
        return
    ModulePermission.objects.filter(role=role, module='purchase').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0041_hr_manager_purchase_view'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
