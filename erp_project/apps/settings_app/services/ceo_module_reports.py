"""CEO dashboard — segregated module reports with health flags (read-only)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.assets.models import EquipmentAllocation
from apps.contracts.models import Contract, ContractType
from apps.core.visibility import filter_projects_for_user
from apps.hr.services.kpi_scoring import build_kpi_dashboard
from apps.operations.models import StaffDutySchedule
from apps.projects.models import Inspection, Project, Task
from apps.projects.project_dashboard import (
    _build_contracts_section,
    _build_inspections_section,
    _build_operations_section as _staff_ops_metrics,
    _build_support_section,
    _open_tickets_qs,
    _project_health,
)
from .ceo_executive_reports import (
    CeoFilters,
    COMPLETED_PROJECT,
    OPEN_PROJECT,
    _apply_service_line_to_projects,
    _money,
)

MODULE_FLAG_LABELS = {
    'projects': {'green': 'On track', 'yellow': 'Watch', 'red': 'Action needed'},
    'estimates': {'green': 'Pipeline healthy', 'yellow': 'Needs attention', 'red': 'Action needed'},
    'quotations': {'green': 'Pipeline healthy', 'yellow': 'Watch', 'red': 'Action needed'},
    'sales_orders': {'green': 'Orders flowing', 'yellow': 'Low volume', 'red': 'No orders'},
    'leads': {'green': 'Pipeline healthy', 'yellow': 'Watch', 'red': 'Action needed'},
    'inspections': {'green': 'On track', 'yellow': 'Watch', 'red': 'Failures rising'},
    'operations': {'green': 'On track', 'yellow': 'Watch', 'red': 'Action needed'},
    'support': {'green': 'Under control', 'yellow': 'Watch', 'red': 'Action needed'},
    'contracts': {'green': 'Stable', 'yellow': 'Watch', 'red': 'Action needed'},
    'assets': {'green': 'Utilized', 'yellow': 'Watch', 'red': 'Action needed'},
    'purchase': {'green': 'Under control', 'yellow': 'Watch', 'red': 'Action needed'},
    'inventory': {'green': 'Stock OK', 'yellow': 'Watch', 'red': 'Action needed'},
    'hr': {'green': 'On track', 'yellow': 'Watch', 'red': 'Action needed'},
}


def _filters_dict(filters: CeoFilters) -> dict:
    return {'date_from': filters.date_from, 'date_to': filters.date_to}


def _health_flag(*, red: bool, yellow: bool) -> str:
    if red:
        return 'red'
    if yellow:
        return 'yellow'
    return 'green'


def _flag_meta(flag: str, module_key: str = '') -> dict:
    labels = MODULE_FLAG_LABELS.get(
        module_key,
        {'green': 'Healthy', 'yellow': 'Watch', 'red': 'Action needed'},
    )
    tone = {
        'green': {'icon': 'fa-circle-check', 'class': 'ceo-flag-pill--green', 'label': labels['green']},
        'yellow': {'icon': 'fa-triangle-exclamation', 'class': 'ceo-flag-pill--yellow', 'label': labels['yellow']},
        'red': {'icon': 'fa-circle-exclamation', 'class': 'ceo-flag-pill--red', 'label': labels['red']},
    }[flag]
    return tone


def _status_chip(label: str, value, tone: str) -> dict:
    return {'label': label, 'value': value, 'tone': tone}


def _module_shell(
    *,
    key: str,
    title: str,
    icon: str,
    url_name: str,
    flag: str,
    headline: str,
    watch: list[str],
    metrics: list[tuple],
    columns: list[str],
    rows: list[dict],
    status_counts: list[dict] | None = None,
    kpis: list[dict] | None = None,
    dashboard_url: str = '',
    period_label: str = '',
    prev_period_label: str = '',
    total_in_scope: int | None = None,
) -> dict:
    return {
        'key': key,
        'title': title,
        'icon': icon,
        'url': reverse(url_name),
        'dashboard_url': dashboard_url,
        'flag': flag,
        'flag_display': _flag_meta(flag, key),
        'headline': headline,
        'period_label': period_label,
        'prev_period_label': prev_period_label,
        'total_in_scope': total_in_scope,
        'watch': watch,
        'metrics': metrics,
        'kpis': kpis or [],
        'columns': columns,
        'rows': rows,
        'status_counts': status_counts or [],
    }


def _projects_module(user, filters: CeoFilters) -> dict:
    today = filters.date_to
    qs = filter_projects_for_user(
        Project.objects.filter(is_active=True).select_related('customer', 'manager'),
        user,
    )
    qs = _apply_service_line_to_projects(qs, filters.service_line)
    active = [p for p in qs if p.status in OPEN_PROJECT or p.status in COMPLETED_PROJECT]

    on_track = delayed = at_risk = 0
    rows = []
    pending_approval = 0
    for p in qs:
        if p.conversion_approval_status == 'pending' or p.edit_approval_status == 'pending':
            pending_approval += 1
        if p.status in COMPLETED_PROJECT or p.status in ('cancelled', 'draft'):
            continue
        health = _project_health(p, today)
        if health == 'on_track':
            on_track += 1
        elif health == 'delayed':
            delayed += 1
        elif health == 'at_risk':
            at_risk += 1
        if health in ('delayed', 'at_risk'):
            issue = 'Past deadline' if health == 'delayed' else 'Due within 7 days / on hold'
            rows.append({
                'cells': [
                    p.project_code,
                    (p.customer.display_name if p.customer_id else '—')[:22],
                    p.get_status_display(),
                    f'{float(p.task_progress_percent or 0):.0f}%',
                    issue,
                ],
            })

    rows.sort(key=lambda r: r['cells'][0])
    active_open = on_track + delayed + at_risk
    flag = _health_flag(red=delayed >= 2, yellow=delayed >= 1 or at_risk >= 2 or pending_approval > 0)
    watch = []
    if delayed:
        watch.append(f'{delayed} project(s) past planned end date')
    if at_risk:
        watch.append(f'{at_risk} project(s) at risk (due soon or on hold)')
    if pending_approval:
        watch.append(f'{pending_approval} pending approval(s) on projects')
    if not watch:
        watch.append('No critical project delays in current portfolio')

    return _module_shell(
        key='projects',
        title='Projects',
        icon='fa-project-diagram',
        url_name='projects:project_list',
        flag=flag,
        headline=f'{active_open} active · {on_track} on track · {delayed} delayed · {at_risk} at risk',
        watch=watch,
        status_counts=[
            _status_chip('On track', on_track, 'success'),
            _status_chip('Delayed', delayed, 'danger'),
            _status_chip('At risk', at_risk, 'warning'),
            _status_chip('Pending approval', pending_approval, 'warning'),
        ],
        metrics=[
            ('Active jobs', active_open, 'int'),
            ('On track', on_track, 'int'),
            ('Delayed', delayed, 'int'),
            ('At risk', at_risk, 'int'),
            ('Pending approval', pending_approval, 'int'),
        ],
        columns=['Job', 'Client', 'Status', 'Progress', 'Issue'],
        rows=rows[:15],
    )


def _inspections_module(user, filters: CeoFilters) -> dict:
    data = _build_inspections_section(_filters_dict(filters))
    failed = 0
    passed = 0
    pending = 0
    rows = []
    qs = Inspection.objects.filter(
        is_active=True,
        inspection_date__gte=filters.date_from,
        inspection_date__lte=filters.date_to,
    ).select_related('project', 'amc_contract').prefetch_related('checklist_items')

    for insp in qs.order_by('-inspection_date')[:20]:
        items = list(insp.checklist_items.filter(is_active=True))
        total = len(items)
        failed_items = sum(1 for i in items if i.is_flagged_red)
        if failed_items:
            failed += 1
        status = 'Passed' if total and not failed_items else ('Failed' if failed_items else 'Pending')
        if status == 'Passed':
            passed += 1
        elif status == 'Failed':
            failed += 1
        else:
            pending += 1
        rows.append({
            'cells': [
                insp.inspection_number,
                insp.get_link_type_display(),
                insp.inspection_date.strftime('%d/%m/%Y'),
                status,
                f'{round((total - failed_items) / total * 100) if total else 0}%',
            ],
        })

    flag = _health_flag(
        red=failed >= 3,
        yellow=failed >= 1 or data['in_progress'] > data['completed_checklists'],
    )
    watch = []
    if failed:
        watch.append(f'{failed} inspection(s) with checklist failures')
    if data['in_progress']:
        watch.append(f'{data["in_progress"]} inspection(s) in progress')
    if not watch:
        watch.append('Inspection checklist completion on track')

    return _module_shell(
        key='inspections',
        title='Inspections',
        icon='fa-clipboard-check',
        url_name='projects:inspection_list',
        flag=flag,
        headline=f'{data["total_inspections"]} in period · {data["completed_checklists"]} complete · {failed} failed',
        watch=watch,
        status_counts=[
            _status_chip('Passed', passed, 'success'),
            _status_chip('Failed', failed, 'danger'),
            _status_chip('Pending', pending, 'warning'),
            _status_chip('In progress', data['in_progress'], 'info'),
        ],
        metrics=[
            ('Total inspections', data['total_inspections'], 'int'),
            ('Checklists complete', data['completed_checklists'], 'int'),
            ('In progress', data['in_progress'], 'int'),
            ('Project-linked', data['type_breakdown']['project'], 'int'),
            ('AMC-linked', data['type_breakdown']['amc'], 'int'),
        ],
        columns=['Inspection', 'Type', 'Date', 'Status', 'Pass %'],
        rows=rows,
    )


def _staff_operations_module(user, filters: CeoFilters) -> dict:
    today = filters.date_to
    data = _staff_ops_metrics(_filters_dict(filters), today)
    rows = []
    for duty in data['preview']:
        target = '—'
        if duty.project_id:
            target = duty.project.project_code
        elif duty.amc_contract_id:
            target = duty.amc_contract.contract_number
        rows.append({
            'cells': [
                str(duty.employee) if duty.employee_id else '—',
                duty.duty_date.strftime('%d/%m/%Y'),
                duty.get_status_display(),
                target,
                f'{duty.start_time:%H:%M}' if duty.start_time else '—',
            ],
        })

    cancelled = data['status_counts'].get('cancelled', 0)
    flag = _health_flag(
        red=cancelled >= 3,
        yellow=cancelled >= 1 or data['on_duty_today'] == 0,
    )
    watch = []
    if cancelled:
        watch.append(f'{cancelled} duty schedule(s) cancelled in period')
    if data['on_duty_today'] == 0:
        watch.append('No staff scheduled on duty today')
    else:
        watch.append(f'{data["on_duty_today"]} staff on duty today')
    if data['total_scheduled']:
        watch.append(f'{data["total_scheduled"]} scheduled duties in filter period')

    return _module_shell(
        key='operations',
        title='Field operations',
        icon='fa-user-clock',
        url_name='operations:schedule_list',
        flag=flag,
        headline=f'{data["total_duties"]} duties · {data["on_duty_today"]} on duty today',
        watch=watch[:4],
        status_counts=[
            _status_chip('Scheduled', data['total_scheduled'], 'info'),
            _status_chip('On duty today', data['on_duty_today'], 'success'),
            _status_chip('Cancelled', cancelled, 'danger'),
            _status_chip('Paused', data['status_counts'].get('paused', 0), 'warning'),
        ],
        metrics=[
            ('Duties in period', data['total_duties'], 'int'),
            ('Scheduled', data['total_scheduled'], 'int'),
            ('On duty today', data['on_duty_today'], 'int'),
            ('Cancelled', cancelled, 'int'),
            ('Paused', data['status_counts'].get('paused', 0), 'int'),
        ],
        columns=['Employee', 'Date', 'Status', 'Target', 'Start'],
        rows=rows,
    )


def _support_module(user, filters: CeoFilters) -> dict:
    data = _build_support_section(user, _filters_dict(filters))
    if data is None:
        return _module_shell(
            key='support',
            title='Support',
            icon='fa-life-ring',
            url_name='support:ticket_list',
            flag='yellow',
            headline='No access to support data',
            watch=['Grant support view permission for CEO reporting'],
            metrics=[],
            columns=[],
            rows=[],
        )

    open_count = data['open_tickets']
    urgent = data['urgent_tickets']
    unassigned = data['unassigned_tickets']
    rows = []
    for t in data['preview']:
        rows.append({
            'cells': [
                t.ticket_number,
                t.subject[:28],
                t.get_priority_display(),
                t.kanban_stage.name if t.kanban_stage_id else 'Unassigned',
                str(t.assigned_to) if t.assigned_to_id else '—',
            ],
        })

    flag = _health_flag(red=urgent >= 2 or unassigned >= 5, yellow=urgent >= 1 or unassigned >= 2)
    watch = []
    if urgent:
        watch.append(f'{urgent} urgent ticket(s) open')
    if unassigned:
        watch.append(f'{unassigned} ticket(s) without assignee')
    if open_count:
        watch.append(f'{open_count} total open tickets')
    if not watch:
        watch.append('Support queue under control')

    return _module_shell(
        key='support',
        title='Support',
        icon='fa-life-ring',
        url_name='support:ticket_list',
        flag=flag,
        headline=f'{open_count} open · {urgent} urgent · {unassigned} unassigned',
        watch=watch,
        status_counts=[
            _status_chip('Open', open_count, 'warning'),
            _status_chip('Urgent', urgent, 'danger'),
            _status_chip('Unassigned', unassigned, 'warning'),
            _status_chip('In period', data['total_tickets'], 'info'),
        ],
        metrics=[
            ('Open tickets', open_count, 'int'),
            ('Urgent', urgent, 'int'),
            ('Unassigned', unassigned, 'int'),
            ('In period', data['total_tickets'], 'int'),
        ],
        columns=['Ticket', 'Subject', 'Priority', 'Stage', 'Owner'],
        rows=rows,
    )


def _contracts_module(user, filters: CeoFilters) -> dict:
    today = filters.date_to
    data = _build_contracts_section(user, _filters_dict(filters), today)
    if data is None:
        return _module_shell(
            key='contracts',
            title='Contracts',
            icon='fa-file-contract',
            url_name='contracts:contract_list',
            flag='yellow',
            headline='No access to contracts data',
            watch=[],
            metrics=[],
            columns=[],
            rows=[],
        )

    rows = []
    for item in data['preview']:
        c = item['contract']
        rows.append({
            'cells': [
                c.contract_number,
                (c.customer.display_name if c.customer_id else '—')[:22],
                ', '.join(item['type_names'][:2]) or '—',
                item['lifecycle'],
                f'{float(c.contract_value):,.0f}',
            ],
        })

    expiring = data['metric_expiring']
    expired = data['metric_expired']
    flag = _health_flag(red=expiring >= 5, yellow=expiring >= 1 or expired >= 3)
    watch = []
    if expiring:
        watch.append(f'{expiring} contract(s) expiring within 30 days')
    if expired:
        watch.append(f'{expired} expired contract(s) on record')
    if data['metric_recent']:
        watch.append(f'{data["metric_recent"]} new contract(s) in last 7 days')
    if not watch:
        watch.append('Contract portfolio stable')

    return _module_shell(
        key='contracts',
        title='Contracts',
        icon='fa-file-signature',
        url_name='contracts:contract_list',
        flag=flag,
        headline=f'{data["metric_active"]} active · {expiring} expiring · {expired} expired',
        watch=watch,
        status_counts=[
            _status_chip('Active', data['metric_active'], 'success'),
            _status_chip('Expiring (30d)', expiring, 'warning'),
            _status_chip('Expired', expired, 'danger'),
            _status_chip('New (7d)', data['metric_recent'], 'info'),
        ],
        metrics=[
            ('Active', data['metric_active'], 'int'),
            ('Expiring (30d)', expiring, 'int'),
            ('Expired', expired, 'int'),
            ('New (7d)', data['metric_recent'], 'int'),
        ],
        columns=['Contract', 'Customer', 'Type', 'Status', 'Value (AED)'],
        rows=rows,
    )


def _assets_module(user, filters: CeoFilters) -> dict:
    qs = EquipmentAllocation.objects.filter(is_active=True).select_related(
        'asset', 'project', 'allocated_by',
    )
    period_qs = qs.filter(
        start_date__lte=filters.date_to,
    ).filter(
        Q(actual_end_date__gte=filters.date_from)
        | Q(actual_end_date__isnull=True)
    )

    active = qs.filter(status='active').count()
    returned = period_qs.filter(status='returned').count()
    transferred = period_qs.filter(status='transferred').count()

    total_cost = Decimal('0.00')
    rows = []
    for alloc in qs.filter(status='active').order_by('-start_date')[:12]:
        cost = alloc.display_cost()
        total_cost += cost
        rows.append({
            'cells': [
                alloc.asset.asset_number if alloc.asset_id else '—',
                (alloc.asset.name if alloc.asset_id else '—')[:22],
                alloc.project.project_code if alloc.project_id else '—',
                alloc.start_date.strftime('%d/%m/%Y'),
                f'{float(cost):,.0f}',
                alloc.get_status_display(),
            ],
        })

    projects_using = qs.filter(status='active').values('project_id').distinct().count()

    flag = _health_flag(red=active == 0 and period_qs.exists(), yellow=active >= 15)
    watch = []
    if active:
        watch.append(f'{active} asset(s) currently allocated to projects')
        watch.append(f'AED {float(total_cost):,.0f} active allocation cost (estimated)')
    if projects_using:
        watch.append(f'{projects_using} project(s) using allocated equipment')
    if not watch:
        watch.append('No active equipment allocations')

    return _module_shell(
        key='assets',
        title='Assets & equipment',
        icon='fa-truck-monster',
        url_name='assets:asset_list',
        flag=flag,
        headline=f'{active} active allocations · {projects_using} projects · AED {float(total_cost):,.0f} est. cost',
        watch=watch,
        status_counts=[
            _status_chip('Active', active, 'success'),
            _status_chip('Returned', returned, 'info'),
            _status_chip('Transferred', transferred, 'secondary'),
            _status_chip('Projects', projects_using, 'primary'),
        ],
        metrics=[
            ('Active allocations', active, 'int'),
            ('Projects using assets', projects_using, 'int'),
            ('Est. active cost', float(total_cost), 'money'),
            ('Returned (period)', returned, 'int'),
            ('Transferred (period)', transferred, 'int'),
        ],
        columns=['Asset #', 'Equipment', 'Project', 'Start', 'Est. cost', 'Status'],
        rows=rows,
    )


def build_ops_modules(user, filters: CeoFilters) -> list[dict]:
    return [
        _projects_module(user, filters),
        _inspections_module(user, filters),
        _staff_operations_module(user, filters),
        _support_module(user, filters),
        _contracts_module(user, filters),
        _assets_module(user, filters),
    ]


def build_sales_modules(user, filters: CeoFilters) -> list[dict]:
    from .ceo_sales_modules import build_ceo_sales_modules

    return build_ceo_sales_modules(user, filters)


def build_hr_kpi_section(user, filters: CeoFilters) -> dict:
    data = build_kpi_dashboard()
    overall = [r for r in data['overall'] if r['total_sum'] > 0]
    best = overall[:5]
    worst = list(reversed(overall[-5:])) if len(overall) >= 5 else list(reversed(overall))

    track_highlights = []
    for key, track in data['tracks'].items():
        rows = track['rows']
        if not rows:
            continue
        top = rows[0]
        bottom = rows[-1] if len(rows) > 1 else None
        track_highlights.append({
            'track': track['label'],
            'best_name': top['employee_name'],
            'best_pct': top['score_pct'],
            'best_breakdown': top['breakdown'],
            'worst_name': bottom['employee_name'] if bottom else '—',
            'worst_pct': bottom['score_pct'] if bottom else 0,
            'worst_breakdown': bottom['breakdown'] if bottom else '—',
        })

    avg_pct = round(sum(r['overall_pct'] for r in overall) / len(overall), 1) if overall else 0
    flag = _health_flag(
        red=avg_pct < 60 and len(overall) > 0,
        yellow=avg_pct < 75 and len(overall) > 0,
    )

    best_rows = [
        {
            'cells': [
                r['employee_name'],
                r['department_name'],
                f'{r["overall_pct"]}%',
                f'P:{r["track_pcts"]["project"] or "—"} S:{r["track_pcts"]["sales"] or "—"} B:{r["track_pcts"]["purchase"] or "—"}',
            ],
        }
        for r in best
    ]
    worst_rows = [
        {
            'cells': [
                r['employee_name'],
                r['department_name'],
                f'{r["overall_pct"]}%',
                f'P:{r["track_pcts"]["project"] or "—"} S:{r["track_pcts"]["sales"] or "—"} B:{r["track_pcts"]["purchase"] or "—"}',
            ],
        }
        for r in worst
    ]

    return {
        'flag': flag,
        'flag_display': _flag_meta(flag, 'hr'),
        'headline': f'{len(overall)} staff scored · avg {avg_pct}%',
        'url': reverse('hr:kpi_dashboard'),
        'track_highlights': track_highlights,
        'best': best_rows,
        'worst': worst_rows,
        'watch': [
            f'Top performer: {best[0]["employee_name"]} ({best[0]["overall_pct"]}%)' if best else 'No KPI data yet',
            f'Needs support: {worst[0]["employee_name"]} ({worst[0]["overall_pct"]}%)' if worst else '—',
        ],
    }
