"""Dedicated ERP roles per manager function (name matches HR designation for auto-assign)."""
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


def _ensure_role(Role, code, name, description):
    role, _ = Role.objects.get_or_create(
        code=code,
        defaults={
            'name': name,
            'description': description,
            'is_system_role': False,
            'is_active': True,
        },
    )
    role.name = name
    role.description = description
    role.is_active = True
    role.save(update_fields=['name', 'description', 'is_active'])
    return role


def forwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    ModulePermission = apps.get_model('settings_app', 'ModulePermission')

    roles_config = [
        (
            'hr_manager',
            'HR Manager',
            'Human resources leadership — configure module access under Settings → Roles.',
            {
                'hr': {'view': True, 'create': True, 'edit': True, 'delete': True},
                'reports': {'view': True},
                'documents': {'view': True, 'create': True, 'edit': True, 'delete': False},
            },
        ),
        (
            'hr_executive',
            'HR Executive',
            'HR operations staff — tune permissions per user needs.',
            {
                'hr': {'view': True, 'create': True, 'edit': True, 'delete': False},
                'documents': {'view': True},
            },
        ),
        (
            'it_manager',
            'IT Manager',
            'Information technology leadership.',
            {
                'projects': {'view': True, 'create': True, 'edit': True, 'delete': False},
                'inventory': {'view': True, 'create': False, 'edit': True, 'delete': False},
                'hr': {'view': True},
                'reports': {'view': True},
            },
        ),
        (
            'finance_manager',
            'Finance Manager',
            'Finance and accounting leadership.',
            {
                'finance': {'view': True, 'create': True, 'edit': True, 'delete': False},
                'purchase': {'view': True, 'create': True, 'edit': True, 'delete': False},
                'sales': {'view': True},
                'reports': {'view': True},
            },
        ),
        (
            'marketing_manager',
            'Marketing Manager',
            'Marketing and lead pipeline leadership.',
            {
                'crm': {'view': True, 'create': True, 'edit': True, 'delete': False},
                'sales': {'view': True, 'create': True, 'edit': True, 'delete': False},
            },
        ),
        (
            'project_manager',
            'Project Manager',
            'Project delivery leadership (separate from Operation Manager).',
            {
                'projects': {'view': True, 'create': True, 'edit': True, 'delete': False},
                'reports': {'view': True},
                'inventory': {'view': True},
                'crm': {'view': True},
                'hr': {'view': True},
            },
        ),
    ]

    for code, name, description, modules in roles_config:
        role = _ensure_role(Role, code, name, description)
        _ensure_module_permissions(ModulePermission, role, modules)


def backwards(apps, schema_editor):
    Role = apps.get_model('settings_app', 'Role')
    Role.objects.filter(
        code__in=[
            'hr_manager',
            'hr_executive',
            'it_manager',
            'finance_manager',
            'marketing_manager',
            'project_manager',
        ]
    ).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0018_approval_leave_module'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
