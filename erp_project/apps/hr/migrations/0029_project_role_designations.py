"""Add Salesman, Site Engineer, Operation Manager designations and reassign employees."""
from django.db import migrations


def forwards(apps, schema_editor):
    Designation = apps.get_model('hr', 'Designation')
    Employee = apps.get_model('hr', 'Employee')
    Department = apps.get_model('hr', 'Department')
    Role = apps.get_model('settings_app', 'Role')

    sales_dept = Department.objects.filter(code='SALES', is_active=True).first()
    ops_dept = Department.objects.filter(code='OPS', is_active=True).first()
    proj_dept = Department.objects.filter(code='PROJ', is_active=True).first()

    Designation.objects.filter(name='Sales', is_active=True).update(name='Salesman')

    for desig in Designation.objects.filter(name='Sales Executive', is_active=True):
        existing = Designation.objects.filter(
            name='Salesman',
            department_id=desig.department_id,
            is_active=True,
        ).first()
        if existing:
            Employee.objects.filter(designation_id=desig.pk).update(designation_id=existing.pk)
            desig.is_active = False
            desig.save(update_fields=['is_active'])
        else:
            desig.name = 'Salesman'
            desig.save(update_fields=['name'])

    def ensure_designation(name, department):
        if not department:
            return None
        desig, _ = Designation.objects.get_or_create(
            name=name,
            department=department,
            defaults={'is_active': True},
        )
        if not desig.is_active:
            desig.is_active = True
            desig.save(update_fields=['is_active'])
        return desig

    site_engineer_desig = ensure_designation('Site Engineer', proj_dept)
    operation_manager_desig = ensure_designation('Operation Manager', ops_dept)
    salesman_desig = ensure_designation('Salesman', sales_dept)

    if operation_manager_desig:
        Employee.objects.filter(
            is_active=True,
            designation__name='Project Manager',
        ).update(designation=operation_manager_desig)

    if site_engineer_desig:
        site_usernames = [
            'ali_khan',
            'amir_hassan',
            'faheem_ashraf',
            'ehsan_qureshi',
        ]
        Employee.objects.filter(
            is_active=True,
            user__username__in=site_usernames,
        ).update(designation=site_engineer_desig)

    if salesman_desig:
        Employee.objects.filter(
            is_active=True,
            designation__name='Sales',
        ).update(designation=salesman_desig)

    Role.objects.filter(code='sales', is_active=True).update(name='Salesman')


def backwards(apps, schema_editor):
    Designation = apps.get_model('hr', 'Designation')
    Role = apps.get_model('settings_app', 'Role')

    Designation.objects.filter(name='Salesman', is_active=True).update(name='Sales')
    Designation.objects.filter(name='Site Engineer', is_active=True).update(is_active=False)
    Designation.objects.filter(name='Operation Manager', is_active=True).update(is_active=False)
    Role.objects.filter(code='sales', is_active=True).update(name='Sales')


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0028_attendance_multiple_sessions_per_day'),
        ('settings_app', '0016_reports_module'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
