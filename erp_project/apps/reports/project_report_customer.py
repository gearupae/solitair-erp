"""Customer Progress Report: progress summary without costing."""
from __future__ import annotations

from apps.projects.models import Project


def _member_row(user, role: str) -> dict:
    emp = getattr(user, 'employee_profile', None)
    if emp:
        name = emp.full_name or user.get_full_name() or user.username
        employee_code = (emp.employee_code or '').strip() or '—'
        designation = emp.designation.name if emp.designation_id else '—'
        department = emp.department.name if emp.department_id else '—'
        email = emp.email or user.email or '—'
        phone = (emp.phone or '').strip() or '—'
    else:
        name = user.get_full_name() or user.username
        employee_code = '—'
        designation = '—'
        department = '—'
        email = user.email or '—'
        phone = '—'

    return {
        'name': name,
        'role': role,
        'employee_code': employee_code,
        'designation': designation,
        'department': department,
        'email': email,
        'phone': phone,
    }


def _team_members(project) -> list[dict]:
    """Project manager and assigned members (excludes technicians)."""
    rows = []
    seen_pks = set()

    if project.manager_id:
        rows.append(_member_row(project.manager, 'Project Manager'))
        seen_pks.add(project.manager_id)

    for user in project.members.all().order_by('first_name', 'last_name', 'username'):
        if user.pk in seen_pks:
            continue
        rows.append(_member_row(user, 'Team Member'))
        seen_pks.add(user.pk)

    return rows


def _technicians(project) -> list[dict]:
    """Field technicians assigned to the project."""
    rows = []
    member_pks = set(project.members.values_list('pk', flat=True))
    manager_pk = project.manager_id

    for user in project.technicians.all().order_by('first_name', 'last_name', 'username'):
        role = 'Technician'
        if user.pk == manager_pk:
            role = 'Technician / Project Manager'
        elif user.pk in member_pks:
            role = 'Technician / Team Member'
        rows.append(_member_row(user, role))

    return rows


def _task_row(task) -> dict:
    assigned = task.assigned_to
    if assigned:
        emp = getattr(assigned, 'employee_profile', None)
        if emp:
            assigned_name = f'{emp.full_name} ({emp.employee_code})'
        else:
            assigned_name = assigned.get_full_name() or assigned.username
    else:
        assigned_name = '—'

    return {
        'pk': task.pk,
        'name': task.name,
        'description': (task.description or '').strip(),
        'assigned_to': assigned_name,
        'priority': task.get_priority_display(),
        'status': task.status,
        'status_display': task.get_status_display(),
        'is_completed': task.status == 'completed',
        'start_date': task.start_date,
        'end_date': task.due_date,
    }


def build_project_report_customer(*, project):
    """Customer-facing project summary — no financial or costing data."""
    from apps.settings_app.models import CompanySettings

    tasks_qs = (
        project.tasks.filter(is_active=True)
        .select_related('assigned_to', 'assigned_to__employee_profile')
        .order_by('due_date', 'start_date', 'name')
    )
    tasks = [_task_row(t) for t in tasks_qs]
    completed = [t for t in tasks if t['is_completed']]
    pending = [t for t in tasks if not t['is_completed']]
    team_members = _team_members(project)
    technicians = _technicians(project)

    return {
        'project': project,
        'company': CompanySettings.get_settings(),
        'customer': project.customer,
        'team_members': team_members,
        'technicians': technicians,
        'technician_count': len(technicians),
        'team_member_count': len(team_members),
        'tasks': tasks,
        'completed_tasks': completed,
        'pending_tasks': pending,
        'total_tasks': len(tasks),
        'completed_count': len(completed),
        'pending_count': len(pending),
        'task_progress_percent': project.task_progress_percent,
        'period_start': project.start_date,
        'period_end': project.end_date,
    }


def project_choices_for_report():
    return (
        Project.objects.filter(is_active=True)
        .select_related('customer', 'manager')
        .prefetch_related('members', 'technicians')
        .order_by('-created_at', '-pk')
    )
