"""Auto-create Django users when HR employees are saved without a linked login."""
from __future__ import annotations

import re

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.hr.models import Employee
from apps.settings_app.models import Role, UserProfile, UserRole

User = get_user_model()


def default_roles_for_new_hire() -> list:
    """Fallback roles when none selected: ``employee`` role, else first active role."""
    r = Role.objects.filter(code='employee', is_active=True).first()
    if r:
        return [r]
    r = Role.objects.filter(is_active=True).order_by('pk').first()
    return [r] if r else []


def resolve_roles(selected) -> list:
    """Use selected roles from the form, or default hire roles."""
    sel = list(selected or [])
    if sel:
        return sel
    return default_roles_for_new_hire()


def _default_login_password() -> str:
    return getattr(settings, 'HR_EMPLOYEE_DEFAULT_PASSWORD', 'AlNajahEmployee123!')


def _unique_username(email: str, employee_code: str) -> str:
    base = ''
    if email and '@' in email:
        base = email.split('@', 1)[0]
    base = re.sub(r'[^a-zA-Z0-9_]', '_', base).strip('_')[:30]
    if not base:
        raw = (employee_code or 'user').replace('-', '_')
        base = re.sub(r'[^a-zA-Z0-9_]', '_', raw).strip('_')[:30] or 'user'
    username = base
    if User.objects.filter(username__iexact=username).exists():
        n = 1
        while User.objects.filter(username__iexact=f'{username}_{n}').exists():
            n += 1
        username = f'{username}_{n}'
    return username[:150]


def provision_user_for_employee(employee, roles):
    """
    Create ``User``, ``UserProfile``, ``UserRole`` rows, link ``employee.user``.
    Password is ``settings.HR_EMPLOYEE_DEFAULT_PASSWORD``.
    ``roles`` may be empty — then ``default_roles_for_new_hire()`` is used.

    Returns ``(user, plaintext_password)`` if a user was created; ``(existing_user, None)`` if already linked.
    """
    if employee.user_id:
        return employee.user, None

    role_list = resolve_roles(roles)
    if not role_list:
        raise ValueError(
            'No ERP role available. Run setup_initial_data (Employee role) or pick roles on the employee form.'
        )

    raw_password = _default_login_password()
    username = _unique_username((employee.email or '').strip(), employee.employee_code or '')

    user = User.objects.create_user(
        username=username,
        email=(employee.email or '').strip(),
        password=raw_password,
        first_name=(employee.first_name or '')[:150],
        last_name=(employee.last_name or '')[:150],
        is_active=True,
    )
    UserProfile.objects.get_or_create(user=user)

    for role in role_list:
        rid = role.pk if hasattr(role, 'pk') else int(role)
        UserRole.objects.get_or_create(user=user, role_id=rid)

    employee.user = user
    employee.save(update_fields=['user'])

    from apps.crm.utils import sync_sales_crm_role_from_employee

    sync_sales_crm_role_from_employee(employee)

    return user, raw_password


def sync_pending_employees_to_users(limit: int = 500) -> int:
    """
    Create ERP users for active HR employees without ``user`` (not terminated).
    Returns count created.
    """
    roles = default_roles_for_new_hire()
    if not roles:
        return 0

    qs = (
        Employee.objects.filter(is_active=True, user__isnull=True)
        .exclude(status='terminated')
        .order_by('pk')[:limit]
    )
    n = 0
    for emp in qs:
        try:
            provision_user_for_employee(emp, roles)
            n += 1
        except Exception:
            continue
    return n
