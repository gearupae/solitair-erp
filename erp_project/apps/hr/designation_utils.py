"""Helpers for HR designations and ERP role auto-assignment."""
from __future__ import annotations

# Fallback when designation name does not match any Role.name exactly.
DESIGNATION_ROLE_ALIASES: dict[str, str] = {
    'sales executive': 'sales',
    'senior accountant': 'accountant',
    'admin officer': 'employee',
    'developer': 'employee',
    'ceo': 'admin',
    'cfo': 'accountant',
    'cto': 'admin',
    'coo': 'operation_manager',
}

PROTECTED_ROLE_CODES = frozenset({'super_admin', 'admin'})


def role_code_from_name(name: str) -> str:
    """Build a unique role code from a designation/role display name."""
    import re

    from apps.settings_app.models import Role

    base = re.sub(r'[^a-z0-9]+', '_', (name or '').strip().lower()).strip('_')[:45] or 'role'
    code = base
    n = 2
    while Role.objects.filter(code=code).exclude(name__iexact=name).exists():
        code = f'{base}_{n}'[:50]
        n += 1
    return code


def ensure_role_for_designation(designation):
    """
    Create (or reactivate) an ERP role whose name matches the HR designation.
    Permissions are configured manually under Settings → Roles.
    """
    if not designation or not getattr(designation, 'is_active', True):
        return None

    from apps.settings_app.models import Role

    name = (designation.name or '').strip()
    if not name:
        return None

    dept_label = ''
    if getattr(designation, 'department_id', None) and designation.department:
        dept_label = designation.department.name

    role = Role.objects.filter(name__iexact=name).first()
    if role:
        if not role.is_active:
            role.is_active = True
            role.save(update_fields=['is_active'])
        return role

    description = 'Auto-created from HR designation.'
    if dept_label:
        description = f'Auto-created from HR designation ({dept_label}). Configure access under Settings → Roles.'

    return Role.objects.create(
        name=name,
        code=role_code_from_name(name),
        description=description,
        is_system_role=False,
        is_active=True,
    )


def get_auto_assignable_role_codes():
    """All active ERP roles that designation sync may assign (except admin tiers)."""
    from apps.settings_app.models import Role

    return frozenset(
        Role.objects.filter(is_active=True)
        .exclude(code__in=PROTECTED_ROLE_CODES)
        .values_list('code', flat=True)
    )


def ensure_role_designations(default_department=None) -> None:
    """
    Ensure each active ERP role has a matching designation in the given department.
    Lookup uses (name, department) so duplicate names across departments are safe.
    """
    from apps.settings_app.models import Role

    from .models import Department, Designation

    dept = default_department or Department.objects.filter(is_active=True).first()
    if not dept:
        return

    for role in Role.objects.filter(is_active=True).order_by('name'):
        Designation.objects.get_or_create(name=role.name, department=dept)


def designations_queryset(department_id=None, include_designation_id=None):
    """Active designations, optionally limited to one department."""
    from django.db.models import Q

    from .models import Designation

    qs = Designation.objects.filter(is_active=True).select_related('department')
    if department_id:
        if include_designation_id:
            qs = qs.filter(Q(department_id=department_id) | Q(pk=include_designation_id))
        else:
            qs = qs.filter(department_id=department_id)
    elif include_designation_id:
        qs = qs.filter(Q(is_active=True) | Q(pk=include_designation_id))
    return qs.order_by('department__name', 'name')


def designation_option_rows(queryset):
    return [
        {'id': d.pk, 'department_id': d.department_id, 'name': d.name}
        for d in queryset
    ]


def resolve_role_for_designation(designation):
    """
    Map HR designation to ERP role.
    Prefer exact Role.name match (e.g. HR Manager → HR Manager role) so each
    function can have its own permissions in Settings → Roles.
    """
    if not designation:
        return None

    from apps.settings_app.models import Role

    name = (designation.name or '').strip()
    if not name:
        return None

    role = Role.objects.filter(is_active=True, name__iexact=name).first()
    if role:
        return role

    alias_code = DESIGNATION_ROLE_ALIASES.get(name.lower())
    if alias_code:
        return Role.objects.filter(is_active=True, code=alias_code).first()

    key = name.lower()
    if 'salesman' in key or 'sales executive' in key:
        return Role.objects.filter(is_active=True, code='sales').first()
    if 'accountant' in key:
        return Role.objects.filter(is_active=True, code='accountant').first()
    if 'site engineer' in key:
        return Role.objects.filter(is_active=True, code='site_engineer').first()
    if name.lower() == 'manager':
        return Role.objects.filter(is_active=True, code='manager').first()

    return Role.objects.filter(is_active=True, code='employee').first()


def sync_erp_role_from_designation(employee) -> str | None:
    """
    Align the linked user's ERP role(s) with their HR designation.
    Returns assigned role code, or None when skipped.
    """
    if not employee or not employee.user_id or not employee.designation_id:
        return None

    from apps.settings_app.models import UserRole

    user = employee.user
    if user.is_superuser:
        return None

    existing_codes = set(
        UserRole.objects.filter(user=user, is_active=True).values_list('role__code', flat=True)
    )
    if existing_codes & PROTECTED_ROLE_CODES:
        return None

    role = resolve_role_for_designation(employee.designation)
    if not role:
        return None

    assignable = get_auto_assignable_role_codes()
    UserRole.objects.filter(
        user=user,
        role__code__in=assignable,
    ).exclude(role=role).delete()

    UserRole.objects.update_or_create(
        user=user,
        role=role,
        defaults={'is_active': True},
    )

    from apps.crm.utils import sync_sales_crm_role_from_employee

    sync_sales_crm_role_from_employee(employee)
    return role.code


def sync_all_employee_roles_from_designations(limit: int = 2000) -> int:
    """Re-sync ERP roles for employees with login + designation. Returns count updated."""
    from .models import Employee

    n = 0
    qs = (
        Employee.objects.filter(is_active=True, user__isnull=False, designation__isnull=False)
        .select_related('designation', 'user')
        .order_by('pk')[:limit]
    )
    for emp in qs:
        if sync_erp_role_from_designation(emp):
            n += 1
    return n


def resolve_designation_for_role_name(role_name, department=None):
    """Find an active HR designation matching an ERP role display name."""
    from .models import Designation

    name = (role_name or '').strip()
    if not name:
        return None

    qs = Designation.objects.filter(is_active=True, name__iexact=name)
    if department:
        match = qs.filter(department=department).first()
        if match:
            return match
    return qs.first()


def sync_designation_from_user_roles(employee):
    """
    Set employee.designation from linked user's ERP role(s).
    Prefers specific roles over generic Manager when multiple roles exist.
    Returns True when designation was set or updated.
    """
    if not employee or not employee.user_id:
        return False

    from apps.settings_app.models import UserRole

    role_names = list(
        UserRole.objects.filter(user=employee.user, is_active=True)
        .select_related('role')
        .order_by('role__name')
        .values_list('role__name', flat=True)
    )
    if not role_names:
        return False

    ordered = [n for n in role_names if n.lower() != 'manager']
    ordered.extend(n for n in role_names if n.lower() == 'manager')

    chosen = None
    for name in ordered:
        chosen = resolve_designation_for_role_name(name, employee.department)
        if chosen:
            break

    if not chosen or employee.designation_id == chosen.pk:
        return False

    employee.designation = chosen
    employee.save(update_fields=['designation', 'updated_at'])
    return True


def sync_all_designations_from_user_roles(limit: int = 2000) -> int:
    """Backfill employee.designation from ERP roles. Returns count updated."""
    from .models import Employee

    n = 0
    qs = (
        Employee.objects.filter(is_active=True, user__isnull=False)
        .select_related('user', 'department', 'designation')
        .order_by('pk')[:limit]
    )
    for emp in qs:
        if sync_designation_from_user_roles(emp):
            n += 1
    return n
