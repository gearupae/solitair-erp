"""Integrated project & operations dashboard — live metrics from GearUp modules."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.contracts.models import Contract, ContractType
from apps.core.utils import PermissionChecker
from apps.hr.models import Department
from apps.operations.models import StaffDutySchedule
from apps.projects.models import Inspection, Project
from apps.reports.project_report_financial import COMPLETED_STATUSES, attach_project_list_financials
from apps.support.models import SupportTicket, SupportTicketKanbanStage

ACTIVE_PROJECT_STATUSES = (
    'planning',
    'ongoing',
    'on_hold',
    'completed_payment_pending',
    'ongoing_payment_received',
)

LIFECYCLE_BUCKETS = (
    ('initiation', 'Initiation', ('draft',)),
    ('planning', 'Planning', ('planning',)),
    (
        'execution',
        'Execution',
        ('ongoing', 'on_hold', 'ongoing_payment_received', 'completed_payment_pending'),
    ),
    ('closure', 'Closure', ('completed', 'cancelled')),
)

CONTRACT_CHART_TYPES = ('AMC', 'Service Agreement')

PREVIEW_LIMIT = 8


def _has_date_filter(filters: dict) -> bool:
    return bool(filters.get('date_from') and filters.get('date_to'))


def _apply_date_range(qs, filters: dict, field: str):
    if not _has_date_filter(filters):
        return qs
    lookup_from = f'{field}__gte'
    lookup_to = f'{field}__lte'
    return qs.filter(**{lookup_from: filters['date_from'], lookup_to: filters['date_to']})


def _parse_date(raw: str | None) -> date | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_dashboard_filters(params) -> dict:
    date_from = _parse_date(params.get('date_from'))
    date_to = _parse_date(params.get('date_to'))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    department = (params.get('department') or '').strip()
    status = (params.get('status') or '').strip()

    return {
        'date_from': date_from,
        'date_to': date_to,
        'department': department,
        'status': status,
        'support_priority': (params.get('support_priority') or '').strip(),
        'support_stage': (params.get('support_stage') or '').strip(),
        'support_assignee': (params.get('support_assignee') or '').strip(),
        'inspection_type': (params.get('inspection_type') or '').strip(),
        'duty_staff': (params.get('duty_staff') or '').strip(),
        'duty_status': (params.get('duty_status') or '').strip(),
    }


def _base_projects_qs(user):
    from apps.core.visibility import filter_projects_for_user

    return filter_projects_for_user(
        Project.objects.filter(is_active=True).select_related('customer', 'manager'),
        user,
    )


def _apply_project_filters(qs, filters: dict):
    if filters.get('status'):
        qs = qs.filter(status=filters['status'])
    department = filters.get('department')
    if department:
        try:
            dept_id = int(department)
        except (TypeError, ValueError):
            dept_id = None
        if dept_id:
            qs = qs.filter(
                Q(manager__employee_profile__department_id=dept_id)
                | Q(members__employee_profile__department_id=dept_id)
                | Q(technicians__employee_profile__department_id=dept_id)
            ).distinct()
    date_from = filters.get('date_from')
    date_to = filters.get('date_to')
    if date_from and date_to:
        qs = qs.filter(
            Q(start_date__lte=date_to, end_date__gte=date_from)
            | Q(start_date__isnull=True, end_date__gte=date_from)
            | Q(end_date__isnull=True, start_date__lte=date_to)
            | Q(start_date__isnull=True, end_date__isnull=True, created_at__date__range=(date_from, date_to))
        )
    return qs


def _apply_project_scope_filters(qs, filters: dict):
    """Department and status only — used for needs-attention project alerts."""
    if filters.get('status'):
        qs = qs.filter(status=filters['status'])
    department = filters.get('department')
    if department:
        try:
            dept_id = int(department)
        except (TypeError, ValueError):
            dept_id = None
        if dept_id:
            qs = qs.filter(
                Q(manager__employee_profile__department_id=dept_id)
                | Q(members__employee_profile__department_id=dept_id)
                | Q(technicians__employee_profile__department_id=dept_id)
            ).distinct()
    return qs



def _project_health(project: Project, today: date) -> str:
    if project.status in COMPLETED_STATUSES or project.status == 'cancelled':
        return 'closed'
    if project.status == 'on_hold' or project.edit_approval_status == 'pending':
        return 'at_risk'
    if project.end_date and project.end_date < today:
        return 'delayed'
    if project.end_date and project.end_date <= today + timedelta(days=7):
        return 'at_risk'
    return 'on_track'


def _build_projects_overview(projects_qs, today: date) -> dict:
    projects = list(
        projects_qs.annotate(
            task_total_count=Count('tasks', filter=Q(tasks__is_active=True)),
            task_done_count=Count(
                'tasks',
                filter=Q(tasks__is_active=True, tasks__status='completed'),
            ),
        )
    )
    total = len(projects)
    on_track = delayed = at_risk = 0
    lifecycle = {key: 0 for key, _, _ in LIFECYCLE_BUCKETS}

    for project in projects:
        if project.status in COMPLETED_STATUSES or project.status == 'cancelled':
            continue
        health = _project_health(project, today)
        if health == 'on_track':
            on_track += 1
        elif health == 'delayed':
            delayed += 1
        elif health == 'at_risk':
            at_risk += 1
        for key, _, statuses in LIFECYCLE_BUCKETS:
            if project.status in statuses:
                lifecycle[key] += 1
                break

    gantt_projects = []
    active_for_gantt = [
        p
        for p in projects
        if p.status not in COMPLETED_STATUSES
        and p.status not in ('cancelled', 'draft')
        and (p.start_date or p.end_date)
    ]
    if active_for_gantt:
        starts = [p.start_date or p.end_date for p in active_for_gantt if p.start_date or p.end_date]
        ends = [p.end_date or p.start_date for p in active_for_gantt if p.start_date or p.end_date]
        range_start = min(starts)
        range_end = max(ends)
        if range_end <= range_start:
            range_end = range_start + timedelta(days=30)
        span_days = max((range_end - range_start).days, 1)
        for project in sorted(active_for_gantt, key=lambda p: (p.start_date or p.end_date or today))[:12]:
            start = project.start_date or project.end_date or range_start
            end = project.end_date or project.start_date or start
            if end < start:
                end = start
            left_pct = max(0, (start - range_start).days / span_days * 100)
            width_pct = max(2, (end - start).days / span_days * 100 or 2)
            gantt_projects.append(
                {
                    'project': project,
                    'left_pct': round(left_pct, 1),
                    'width_pct': round(min(width_pct, 100 - left_pct), 1),
                    'health': _project_health(project, today),
                }
            )
    else:
        range_start = range_end = today

    return {
        'total_projects': total,
        'on_track': on_track,
        'delayed': delayed,
        'at_risk': at_risk,
        'lifecycle': [
            {'key': key, 'label': label, 'count': lifecycle[key]}
            for key, label, _ in LIFECYCLE_BUCKETS
        ],
        'lifecycle_total': sum(lifecycle.values()) or 1,
        'gantt_projects': gantt_projects,
        'gantt_range_start': range_start,
        'gantt_range_end': range_end,
    }


def _contract_lifecycle_label(contract: Contract, today: date) -> str:
    if contract.status == 'cancelled':
        return 'Cancelled'
    if contract.end_date < today:
        return 'Expired'
    if contract.start_date > today:
        return 'Upcoming'
    return 'Active'


def _build_contracts_section(user, filters: dict, today: date) -> dict | None:
    if not (user.is_superuser or PermissionChecker.has_permission(user, 'contracts', 'view')):
        return None

    qs = Contract.objects.filter(is_active=True).select_related('customer').prefetch_related('contract_types')
    date_from = filters.get('date_from')
    date_to = filters.get('date_to')
    if date_from and date_to:
        qs = qs.filter(start_date__lte=date_to, end_date__gte=date_from)

    week_ago = today - timedelta(days=7)
    horizon = today + timedelta(days=30)
    all_c = qs.exclude(status='cancelled')

    type_rows = []
    chart_types = ContractType.objects.filter(is_active=True, name__in=CONTRACT_CHART_TYPES).order_by('name')
    for ct in chart_types:
        linked = all_c.filter(contract_types=ct)
        total = linked.aggregate(s=Sum('contract_value'))['s'] or Decimal('0')
        type_rows.append({'name': ct.name, 'count': linked.count(), 'value': float(total)})

    preview = []
    for contract in all_c.order_by('-created_at')[:PREVIEW_LIMIT]:
        preview.append(
            {
                'contract': contract,
                'lifecycle': _contract_lifecycle_label(contract, today),
                'type_names': [t.name for t in contract.contract_types.all()],
            }
        )

    return {
        'metric_active': all_c.filter(start_date__lte=today, end_date__gte=today).count(),
        'metric_expired': all_c.filter(end_date__lt=today).count(),
        'metric_expiring': all_c.filter(end_date__gte=today, end_date__lte=horizon).count(),
        'metric_recent': all_c.filter(created_at__date__gte=week_ago).count(),
        'type_chart_data': type_rows,
        'preview': preview,
    }


def _open_tickets_qs():
    return SupportTicket.objects.filter(is_active=True).filter(
        Q(kanban_stage__isnull=True) | Q(kanban_stage__is_closed=False)
    )


def _unattended_tickets_qs():
    """Open tickets that are unassigned or still in New / unassigned stage."""
    return _open_tickets_qs().filter(
        Q(assigned_to__isnull=True)
        | Q(kanban_stage__slug='new')
        | Q(kanban_stage__isnull=True)
    )


def _build_support_section(user, filters: dict) -> dict | None:
    if not (user.is_superuser or PermissionChecker.has_permission(user, 'support', 'view')):
        return None

    qs = SupportTicket.objects.filter(is_active=True).select_related(
        'customer', 'project', 'amc_contract', 'assigned_to', 'kanban_stage'
    )
    qs = _apply_date_range(qs, filters, 'opened_date')
    if filters.get('support_priority'):
        qs = qs.filter(priority=filters['support_priority'])
    if filters.get('support_assignee'):
        try:
            qs = qs.filter(assigned_to_id=int(filters['support_assignee']))
        except (TypeError, ValueError):
            pass
    if filters.get('support_stage'):
        stage = filters['support_stage']
        if stage == 'unassigned':
            qs = qs.filter(kanban_stage__isnull=True)
        else:
            try:
                qs = qs.filter(kanban_stage_id=int(stage))
            except (TypeError, ValueError):
                pass

    all_tickets = SupportTicket.objects.filter(is_active=True)
    scoped_tickets = _apply_date_range(all_tickets, filters, 'opened_date')

    priority_counts = {
        value: scoped_tickets.filter(priority=value).count()
        for value, _ in SupportTicket.PRIORITY_CHOICES
    }
    priority_breakdown = [
        {'label': label, 'count': priority_counts[value]}
        for value, label in SupportTicket.PRIORITY_CHOICES
    ]
    stage_counts = []
    for stage in SupportTicketKanbanStage.objects.filter(is_active=True).order_by('sort_order', 'id'):
        stage_counts.append({'name': stage.name, 'count': scoped_tickets.filter(kanban_stage=stage).count()})
    stage_counts.append({'name': 'Unassigned', 'count': scoped_tickets.filter(kanban_stage__isnull=True).count()})

    return {
        'total_tickets': scoped_tickets.count(),
        'open_tickets': _open_tickets_qs().count(),
        'urgent_tickets': scoped_tickets.filter(priority='urgent').count(),
        'unassigned_tickets': scoped_tickets.filter(assigned_to__isnull=True).count(),
        'priority_counts': priority_counts,
        'priority_breakdown': priority_breakdown,
        'stage_counts': stage_counts,
        'preview': list(qs.order_by('-opened_date', '-created_at')[:PREVIEW_LIMIT]),
        'stages': SupportTicketKanbanStage.objects.filter(is_active=True).order_by('sort_order', 'id'),
        'priority_choices': SupportTicket.PRIORITY_CHOICES,
    }


def _inspection_qs():
    return (
        Inspection.objects.filter(is_active=True)
        .select_related('project', 'amc_contract')
        .annotate(
            item_count=Count('checklist_items', filter=Q(checklist_items__is_active=True)),
            done_count=Count(
                'checklist_items',
                filter=Q(checklist_items__is_active=True, checklist_items__is_flagged_red=True),
            ),
        )
    )


def _build_inspections_section(filters: dict) -> dict:
    qs = _inspection_qs()
    qs = _apply_date_range(qs, filters, 'inspection_date')
    if filters.get('inspection_type') in ('project', 'amc'):
        qs = qs.filter(link_type=filters['inspection_type'])

    rows = list(qs)
    completed = sum(1 for row in rows if row.item_count and row.done_count >= row.item_count)
    in_progress = sum(1 for row in rows if row.item_count and row.done_count < row.item_count)

    type_breakdown = {
        'project': sum(1 for row in rows if row.link_type == 'project'),
        'amc': sum(1 for row in rows if row.link_type == 'amc'),
    }

    rows.sort(key=lambda r: (r.inspection_date, r.created_at), reverse=True)

    return {
        'total_inspections': len(rows),
        'completed_checklists': completed,
        'in_progress': in_progress,
        'type_breakdown': type_breakdown,
        'preview': rows[:PREVIEW_LIMIT],
    }


def _build_operations_section(filters: dict, today: date) -> dict:
    qs = StaffDutySchedule.objects.filter(is_active=True).select_related(
        'employee', 'project', 'amc_contract'
    )
    qs = _apply_date_range(qs, filters, 'duty_date')
    if filters.get('duty_status'):
        qs = qs.filter(status=filters['duty_status'])
    if filters.get('duty_staff'):
        try:
            qs = qs.filter(employee_id=int(filters['duty_staff']))
        except (TypeError, ValueError):
            pass

    all_qs = qs
    status_counts = {
        value: all_qs.filter(status=value).count()
        for value, _ in StaffDutySchedule.STATUS_CHOICES
    }
    on_duty_today = StaffDutySchedule.objects.filter(
        is_active=True, duty_date=today, status='scheduled'
    ).count()

    return {
        'total_scheduled': all_qs.filter(status='scheduled').count(),
        'total_duties': all_qs.count(),
        'status_counts': status_counts,
        'on_duty_today': on_duty_today,
        'preview': list(all_qs.order_by('-duty_date', 'start_time')[:PREVIEW_LIMIT]),
    }


def _amc_contracts_qs():
    return Contract.objects.filter(is_active=True).exclude(status='cancelled').filter(
        Q(contract_types__name__iexact='AMC') | Q(contract_types__slug__icontains='amc')
    ).distinct()


def _build_needs_attention(user, filters: dict, today: date) -> dict:
    horizon = today + timedelta(days=30)
    projects_qs = _apply_project_scope_filters(_base_projects_qs(user), filters)

    overdue_qs = (
        projects_qs.exclude(status__in=COMPLETED_STATUSES)
        .exclude(status='cancelled')
        .filter(end_date__lt=today)
        .order_by('end_date')
    )
    overdue_list = list(overdue_qs)
    attach_project_list_financials(overdue_list, as_of_date=today)
    overdue_projects = []
    for project in overdue_list:
        completion = None
        if hasattr(project, 'list_financials') and project.list_financials:
            completion = project.list_financials.get('project_completion_pct')
        if completion is None:
            completion = project.task_progress_percent
        overdue_projects.append({'project': project, 'completion_pct': completion})

    unattended = []
    unattended_count = 0
    if user.is_superuser or PermissionChecker.has_permission(user, 'support', 'view'):
        unattended_qs = _unattended_tickets_qs().select_related(
            'kanban_stage', 'project', 'amc_contract', 'customer'
        ).order_by('-opened_date')
        unattended_count = unattended_qs.count()
        unattended = list(unattended_qs)

    pending_all = [i for i in _inspection_qs() if i.item_count and i.done_count < i.item_count]
    pending_all.sort(key=lambda i: (i.item_count - i.done_count), reverse=True)
    pending_inspections = [
        {'inspection': insp, 'items_remaining': insp.item_count - insp.done_count}
        for insp in pending_all
    ]

    missed_duty_qs = (
        StaffDutySchedule.objects.filter(is_active=True, status='scheduled', duty_date__lt=today)
        .select_related('employee', 'project', 'amc_contract')
        .order_by('-duty_date')
    )
    missed_duty = list(missed_duty_qs)

    amc_expiries = []
    amc_expiry_count = 0
    if user.is_superuser or PermissionChecker.has_permission(user, 'contracts', 'view'):
        expiry_qs = (
            _amc_contracts_qs()
            .filter(Q(end_date__lt=today) | Q(end_date__gte=today, end_date__lte=horizon))
            .select_related('customer')
            .order_by('end_date')
        )
        amc_expiry_count = expiry_qs.count()
        for contract in expiry_qs:
            amc_expiries.append(
                {
                    'contract': contract,
                    'lifecycle': _contract_lifecycle_label(contract, today),
                }
            )

    alerts = [
        {
            'key': 'overdue_projects',
            'label': 'Overdue / Incomplete Projects',
            'count': overdue_qs.count(),
            'items': overdue_projects,
            'type': 'projects',
        },
        {
            'key': 'unattended_tickets',
            'label': 'Unattended Support Tickets',
            'count': unattended_count,
            'items': unattended,
            'type': 'support',
        },
        {
            'key': 'pending_inspections',
            'label': 'Pending Inspection Checklist Items',
            'count': len(pending_all),
            'items': pending_inspections,
            'type': 'inspections',
        },
        {
            'key': 'missed_duty',
            'label': 'Missed / Pending Staff Duty',
            'count': missed_duty_qs.count(),
            'items': missed_duty,
            'type': 'operations',
        },
        {
            'key': 'amc_expiries',
            'label': 'Upcoming AMC Expiries',
            'count': amc_expiry_count,
            'items': amc_expiries,
            'type': 'contracts',
        },
    ]

    return {'alerts': alerts, 'total_count': sum(a['count'] for a in alerts)}


def build_dashboard_context(user, params) -> dict:
    filters = parse_dashboard_filters(params)
    today = timezone.localdate()

    projects_qs = _apply_project_filters(_base_projects_qs(user), filters)

    from apps.operations.utils import get_hr_employee_queryset

    contracts = _build_contracts_section(user, filters, today)
    if contracts:
        contracts['type_chart_json'] = json.dumps(contracts['type_chart_data'])

    return {
        'filters': filters,
        'date_from_iso': filters['date_from'].isoformat() if filters.get('date_from') else '',
        'date_to_iso': filters['date_to'].isoformat() if filters.get('date_to') else '',
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'status_choices': Project.STATUS_CHOICES,
        'projects_overview': _build_projects_overview(projects_qs, today),
        'contracts': contracts,
        'support': _build_support_section(user, filters),
        'inspections': _build_inspections_section(filters),
        'operations': _build_operations_section(filters, today),
        'needs_attention': _build_needs_attention(user, filters, today),
        'filter_employees': get_hr_employee_queryset(),
        'today': today,
        'can_view_support': user.is_superuser or PermissionChecker.has_permission(user, 'support', 'view'),
        'can_view_contracts': user.is_superuser or PermissionChecker.has_permission(user, 'contracts', 'view'),
    }
