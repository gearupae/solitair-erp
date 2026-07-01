"""Employee ↔ project assignment helpers (via linked ERP user)."""
from __future__ import annotations

from django.db.models import Q

from apps.projects.models import Project


def employee_project_rows(employee) -> list[dict]:
    """Projects this employee is on (manager, member, or technician)."""
    user = employee.user
    if not user:
        return []

    projects = (
        Project.objects.filter(is_active=True)
        .filter(Q(members=user) | Q(technicians=user) | Q(manager=user))
        .distinct()
        .select_related('customer', 'manager')
        .prefetch_related('members', 'technicians')
        .order_by('-created_at')
    )

    rows = []
    for project in projects:
        roles = []
        is_manager = project.manager_id == user.pk
        is_member = any(m.pk == user.pk for m in project.members.all())
        is_technician = any(t.pk == user.pk for t in project.technicians.all())
        if is_manager:
            roles.append('Manager')
        if is_member:
            roles.append('Member')
        if is_technician:
            roles.append('Technician')
        rows.append({
            'project': project,
            'roles': roles,
            'role_label': ', '.join(roles) if roles else 'Assigned',
            'can_remove': is_member or is_technician,
        })
    return rows


def available_projects_for_employee(employee, *, user):
    """Active projects not yet linked to this employee's user."""
    linked_user = employee.user
    if not linked_user:
        return Project.objects.none()

    from apps.core.visibility import filter_projects_for_user

    assigned_ids = (
        Project.objects.filter(is_active=True)
        .filter(Q(members=linked_user) | Q(technicians=linked_user) | Q(manager=linked_user))
        .values_list('pk', flat=True)
    )
    qs = filter_projects_for_user(
        Project.objects.filter(is_active=True).exclude(pk__in=assigned_ids).select_related('customer'),
        user,
    )
    return qs.order_by('project_code')
