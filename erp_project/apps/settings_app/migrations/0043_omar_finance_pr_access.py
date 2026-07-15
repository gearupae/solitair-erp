"""Grant Omar Finance PR access via finance_manager role."""
from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Role = apps.get_model('settings_app', 'Role')
    UserRole = apps.get_model('settings_app', 'UserRole')

    user = User.objects.filter(username='omar.finance', is_active=True).first()
    role = Role.objects.filter(code='finance_manager', is_active=True).first()
    if not user or not role:
        return

    UserRole.objects.filter(user=user, role__code='accountant').update(is_active=False)
    UserRole.objects.update_or_create(
        user=user,
        role=role,
        defaults={'is_active': True},
    )


def backwards(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Role = apps.get_model('settings_app', 'Role')
    UserRole = apps.get_model('settings_app', 'UserRole')

    user = User.objects.filter(username='omar.finance').first()
    accountant = Role.objects.filter(code='accountant').first()
    finance_manager = Role.objects.filter(code='finance_manager').first()
    if not user:
        return
    if finance_manager:
        UserRole.objects.filter(user=user, role=finance_manager).update(is_active=False)
    if accountant:
        UserRole.objects.update_or_create(
            user=user,
            role=accountant,
            defaults={'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0042_employee_purchase_pr'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
