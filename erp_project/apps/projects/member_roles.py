"""Resolve project roles from members and linked estimates."""
from __future__ import annotations

DESIGNATION_SALESMAN = 'salesman'
DESIGNATION_SITE_ENGINEER = 'site engineer'
DESIGNATION_OPERATION_MANAGER = 'operation manager'


def user_role_label(user) -> str:
    if not user:
        return 'Unassigned'
    emp = getattr(user, 'employee_profile', None)
    if emp:
        code = (emp.employee_code or '').strip()
        name = emp.full_name or user.get_full_name() or user.username
        return f'{name} ({code})' if code else name
    return user.get_full_name() or user.username


def _member_designation(user) -> str:
    emp = getattr(user, 'employee_profile', None)
    if emp and emp.designation_id:
        return (emp.designation.name or '').strip().lower()
    return ''


def _has_designation(user, designation_name: str) -> bool:
    return _member_designation(user) == designation_name.lower()


def get_project_source_estimate(project):
    """Primary estimate linked to this project (usually from conversion)."""
    estimates = getattr(project, '_prefetched_objects_cache', {}).get('estimates')
    if estimates is not None:
        active = [e for e in estimates if getattr(e, 'is_active', True)]
        if active:
            return sorted(active, key=lambda e: (e.date, e.pk), reverse=True)[0]
        return None
    return (
        project.estimates.filter(is_active=True)
        .select_related('assigned_to', 'assigned_to__employee_profile')
        .order_by('-date', '-pk')
        .first()
    )


def resolve_salesman_from_members(project):
    """Salesman from project members with HR designation Salesman."""
    for user in project.members.all().order_by('first_name', 'last_name', 'username'):
        if _has_designation(user, DESIGNATION_SALESMAN):
            return user
    return None


def resolve_salesman_user(project):
    """Salesperson from linked estimate, else project member designated Salesman."""
    estimate = get_project_source_estimate(project)
    if estimate and estimate.assigned_to_id:
        return estimate.assigned_to
    return resolve_salesman_from_members(project)


def resolve_site_engineer_from_members(project):
    """Site engineer from project members with HR designation Site Engineer."""
    for user in project.members.all().order_by('first_name', 'last_name', 'username'):
        if _has_designation(user, DESIGNATION_SITE_ENGINEER):
            return user
    return None


def resolve_operation_manager_from_members(project):
    """Operation manager from project members with HR designation Operation Manager."""
    for user in project.members.all().order_by('first_name', 'last_name', 'username'):
        if _has_designation(user, DESIGNATION_OPERATION_MANAGER):
            return user
    return None


def _sorted_users(users):
    return sorted(users, key=lambda u: (u.first_name or '', u.last_name or '', u.username))


def _users_by_designation(designation_name: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return list(
        User.objects.filter(
            is_active=True,
            employee_profile__is_active=True,
            employee_profile__status='active',
            employee_profile__designation__name=designation_name,
        )
        .select_related('employee_profile')
        .order_by('first_name', 'last_name', 'username')
    )


def _users_by_system_role(role_code: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return list(
        User.objects.filter(
            is_active=True,
            user_roles__role__code=role_code,
            user_roles__is_active=True,
            user_roles__role__is_active=True,
        )
        .select_related('employee_profile')
        .distinct()
        .order_by('first_name', 'last_name', 'username')
    )


def _merge_users(*user_lists):
    merged = {}
    for users in user_lists:
        for user in users:
            merged[user.pk] = user
    return _sorted_users(merged.values())


def all_salesmen_users():
    """All active users with Salesman HR designation or Salesman system role."""
    return _merge_users(
        _users_by_designation('Salesman'),
        _users_by_system_role('sales'),
    )


def all_site_engineer_users():
    """All active users with Site Engineer HR designation or system role."""
    return _merge_users(
        _users_by_designation('Site Engineer'),
        _users_by_system_role('site_engineer'),
    )


def all_operation_manager_users():
    """All active users with Operation Manager HR designation or system role."""
    return _merge_users(
        _users_by_designation('Operation Manager'),
        _users_by_system_role('operation_manager'),
    )


def user_filter_options(users):
    return [{'pk': user.pk, 'label': user_role_label(user)} for user in users]


def _staff_display_row(user, *, project=None):
    emp = getattr(user, 'employee_profile', None)
    designation = '—'
    department = '—'
    email = user.email or '—'
    phone = '—'
    if emp:
        if emp.designation_id:
            designation = emp.designation.name
        if emp.department_id:
            department = emp.department.name
        email = emp.email or user.email or '—'
        phone = (emp.phone or '').strip() or '—'

    badges = []
    if project and project.manager_id == user.pk:
        badges.append('Manager')

    return {
        'display_name': user_role_label(user),
        'designation': designation,
        'department': department,
        'email': email,
        'phone': phone,
        'badges': badges,
    }


def build_project_team_display(project):
    """Members and technicians for project detail page."""
    member_users = (
        project.members.all()
        .select_related('employee_profile', 'employee_profile__designation', 'employee_profile__department')
        .order_by('first_name', 'last_name', 'username')
    )
    member_ids = set(member_users.values_list('pk', flat=True))
    technician_users = (
        project.technicians.all()
        .select_related('employee_profile', 'employee_profile__designation', 'employee_profile__department')
        .order_by('first_name', 'last_name', 'username')
    )

    members = [_staff_display_row(user, project=project) for user in member_users]
    technicians = [
        _staff_display_row(user, project=project)
        for user in technician_users
        if user.pk not in member_ids
    ]

    return {
        'members': members,
        'technicians': technicians,
        'member_count': len(members),
        'technician_count': len(technician_users),
    }
