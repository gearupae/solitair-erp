"""Add Site Engineer and Operation Manager system login roles."""
from django.db import migrations


def _ensure_module_permissions(ModulePermission, role, modules):
    for module, perms in modules.items():
        ModulePermission.objects.update_or_create(
            role=role,
            module=module,
            defaults={
                'can_view': perms.get('view', False),
                'can_create': perms.get('create', False),
                'can_edit': perms.get('edit', False),
                'can_delete': perms.get('delete', False),
            },
        )


def forwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    ModulePermission = apps.get_model('settings_app', 'ModulePermission')
    UserRole = apps.get_model('settings_app', 'UserRole')
    Employee = apps.get_model('hr', 'Employee')

    site_engineer_role, _ = Role.objects.get_or_create(
        code='site_engineer',
        defaults={
            'name': 'Site Engineer',
            'description': 'Field site engineer — projects, inventory, and reports access',
            'is_system_role': False,
            'is_active': True,
        },
    )
    if not site_engineer_role.is_active:
        site_engineer_role.is_active = True
        site_engineer_role.save(update_fields=['is_active'])
    site_engineer_role.name = 'Site Engineer'
    site_engineer_role.description = 'Field site engineer — projects, inventory, and reports access'
    site_engineer_role.save(update_fields=['name', 'description'])

    operation_manager_role, _ = Role.objects.get_or_create(
        code='operation_manager',
        defaults={
            'name': 'Operation Manager',
            'description': 'Operations manager — projects, reports, and team oversight',
            'is_system_role': False,
            'is_active': True,
        },
    )
    if not operation_manager_role.is_active:
        operation_manager_role.is_active = True
        operation_manager_role.save(update_fields=['is_active'])
    operation_manager_role.name = 'Operation Manager'
    operation_manager_role.description = 'Operations manager — projects, reports, and team oversight'
    operation_manager_role.save(update_fields=['name', 'description'])

    _ensure_module_permissions(
        ModulePermission,
        site_engineer_role,
        {
            'projects': {'view': True, 'create': False, 'edit': True, 'delete': False},
            'inventory': {'view': True, 'create': False, 'edit': False, 'delete': False},
            'reports': {'view': True, 'create': False, 'edit': False, 'delete': False},
            'hr': {'view': True, 'create': False, 'edit': False, 'delete': False},
        },
    )
    _ensure_module_permissions(
        ModulePermission,
        operation_manager_role,
        {
            'projects': {'view': True, 'create': True, 'edit': True, 'delete': False},
            'reports': {'view': True, 'create': False, 'edit': False, 'delete': False},
            'inventory': {'view': True, 'create': False, 'edit': False, 'delete': False},
            'crm': {'view': True, 'create': False, 'edit': False, 'delete': False},
            'hr': {'view': True, 'create': False, 'edit': False, 'delete': False},
        },
    )

    for employee in Employee.objects.filter(
        is_active=True,
        user__isnull=False,
        designation__name='Site Engineer',
    ):
        UserRole.objects.get_or_create(
            user_id=employee.user_id,
            role=site_engineer_role,
            defaults={'is_active': True},
        )

    for employee in Employee.objects.filter(
        is_active=True,
        user__isnull=False,
        designation__name='Operation Manager',
    ):
        UserRole.objects.get_or_create(
            user_id=employee.user_id,
            role=operation_manager_role,
            defaults={'is_active': True},
        )


def backwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    Role.objects.filter(code__in=['site_engineer', 'operation_manager']).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0016_reports_module'),
        ('hr', '0029_project_role_designations'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
