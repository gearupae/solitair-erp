"""Set Ahmed Khan as manager (admin) of the Procurement department."""
from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Department = apps.get_model('hr', 'Department')

    user = User.objects.filter(username='ahmed.khan', is_active=True).first()
    dept = Department.objects.filter(is_active=True, code='PROC').first()
    if not user or not dept:
        return
    dept.manager = user
    dept.save(update_fields=['manager'])


def backwards(apps, schema_editor):
    Department = apps.get_model('hr', 'Department')
    Department.objects.filter(code='PROC').update(manager=None)


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0044_employee_photo'),
        ('settings_app', '0044_purchase_role_procurement'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
