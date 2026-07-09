"""Operations dashboard — summary metrics, alerts, and completed schedule reporting."""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from apps.crm.models import Customer

from .models import StaffDutySchedule
from .utils import get_amc_contract_queryset, get_hr_employee_queryset

UPCOMING_HORIZON_DAYS = 14
ALERT_PREVIEW_LIMIT = 12
COMPLETED_DEFAULT_DAYS = 30


def _parse_date(raw: str | None) -> date | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_dashboard_filters(params) -> dict:
    today = timezone.localdate()
    date_from = _parse_date(params.get('date_from'))
    date_to = _parse_date(params.get('date_to'))
    if not date_from and not date_to:
        date_from = today - timedelta(days=COMPLETED_DEFAULT_DAYS)
        date_to = today
    elif date_from and not date_to:
        date_to = today
    elif date_to and not date_from:
        date_from = date_to - timedelta(days=COMPLETED_DEFAULT_DAYS)
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    contract = (params.get('contract') or '').strip()
    customer = (params.get('customer') or '').strip()
    technician = (params.get('technician') or '').strip()

    return {
        'date_from': date_from,
        'date_to': date_to,
        'contract': contract,
        'customer': customer,
        'technician': technician,
    }


def _apply_date_range(qs, date_from: date | None, date_to: date | None, field='duty_date'):
    if date_from:
        qs = qs.filter(**{f'{field}__gte': date_from})
    if date_to:
        qs = qs.filter(**{f'{field}__lte': date_to})
    return qs


def build_summary(today: date, date_from: date | None, date_to: date | None) -> dict:
    """Status counts aligned with the project hub operations section."""
    qs = StaffDutySchedule.objects.filter(is_active=True).select_related(
        'employee', 'project', 'amc_contract'
    )
    qs = _apply_date_range(qs, date_from, date_to)

    status_counts = {
        value: qs.filter(status=value).count()
        for value, _ in StaffDutySchedule.STATUS_CHOICES
    }
    on_duty_today = StaffDutySchedule.objects.filter(
        is_active=True,
        duty_date=today,
        status=StaffDutySchedule.STATUS_SCHEDULED,
    ).count()

    hub_base = reverse('projects:project_dashboard')
    date_qs = ''
    if date_from and date_to:
        date_qs = f'&date_from={date_from.isoformat()}&date_to={date_to.isoformat()}'

    return {
        'total_scheduled': qs.filter(status=StaffDutySchedule.STATUS_SCHEDULED).count(),
        'total_duties': qs.count(),
        'status_counts': status_counts,
        'on_duty_today': on_duty_today,
        'hub_links': {
            'pending': f'{hub_base}?duty_status=pending{date_qs}',
            'overdue': f'{hub_base}?duty_status=overdue{date_qs}',
            'scheduled': f'{hub_base}?duty_status=scheduled{date_qs}',
            'in_progress': f'{hub_base}?duty_status=in_progress{date_qs}',
        },
        'list_links': {
            'pending': f'{reverse("operations:schedule_list")}?status=pending',
            'overdue': f'{reverse("operations:schedule_list")}?status=overdue',
            'unassigned': f'{reverse("operations:schedule_list")}?status=pending',
        },
    }


def _schedule_customer_name(schedule: StaffDutySchedule) -> str:
    if schedule.link_type == 'project' and schedule.project_id and schedule.project.customer_id:
        return schedule.project.customer.name
    if schedule.link_type == 'amc' and schedule.amc_contract_id and schedule.amc_contract.customer_id:
        return schedule.amc_contract.customer.name
    return '—'


def build_alerts(today: date) -> dict:
    horizon = today + timedelta(days=UPCOMING_HORIZON_DAYS)

    upcoming = list(
        StaffDutySchedule.objects.filter(
            is_active=True,
            duty_date__gte=today,
            duty_date__lte=horizon,
            status__in=(
                StaffDutySchedule.STATUS_SCHEDULED,
                StaffDutySchedule.STATUS_PENDING,
                StaffDutySchedule.STATUS_IN_PROGRESS,
            ),
        )
        .select_related('employee', 'project', 'amc_contract', 'amc_contract__customer', 'project__customer')
        .order_by('duty_date', 'start_time')[:ALERT_PREVIEW_LIMIT]
    )

    unassigned = list(
        StaffDutySchedule.objects.filter(
            is_active=True,
            employee__isnull=True,
            status__in=(
                StaffDutySchedule.STATUS_PENDING,
                StaffDutySchedule.STATUS_SCHEDULED,
            ),
        )
        .select_related('project', 'amc_contract', 'amc_contract__customer', 'project__customer')
        .order_by('duty_date', 'start_time')[:ALERT_PREVIEW_LIMIT]
    )

    overdue_past = list(
        StaffDutySchedule.objects.filter(
            is_active=True,
            duty_date__lt=today,
            status__in=(
                StaffDutySchedule.STATUS_SCHEDULED,
                StaffDutySchedule.STATUS_PENDING,
                StaffDutySchedule.STATUS_IN_PROGRESS,
            ),
        )
        .select_related('employee', 'project', 'amc_contract')
        .order_by('duty_date')[:ALERT_PREVIEW_LIMIT]
    )

    marked_overdue = list(
        StaffDutySchedule.objects.filter(
            is_active=True,
            status=StaffDutySchedule.STATUS_OVERDUE,
        )
        .select_related('employee', 'project', 'amc_contract')
        .order_by('duty_date')[:ALERT_PREVIEW_LIMIT]
    )

    conflict_pairs = (
        StaffDutySchedule.objects.filter(
            is_active=True,
            employee_id__isnull=False,
            status__in=StaffDutySchedule.ACTIVE_DUTY_STATUSES,
        )
        .values('employee_id', 'duty_date')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
        .order_by('-duty_date')[:20]
    )
    conflicts: list[dict] = []
    for row in conflict_pairs:
        rows = list(
            StaffDutySchedule.objects.filter(
                is_active=True,
                employee_id=row['employee_id'],
                duty_date=row['duty_date'],
                status__in=StaffDutySchedule.ACTIVE_DUTY_STATUSES,
            ).select_related('employee', 'project', 'amc_contract')
        )
        if rows:
            conflicts.append({'employee': rows[0].employee, 'duty_date': row['duty_date'], 'schedules': rows})

    return {
        'upcoming': upcoming,
        'upcoming_total': StaffDutySchedule.objects.filter(
            is_active=True,
            duty_date__gte=today,
            duty_date__lte=horizon,
            status__in=(
                StaffDutySchedule.STATUS_SCHEDULED,
                StaffDutySchedule.STATUS_PENDING,
                StaffDutySchedule.STATUS_IN_PROGRESS,
            ),
        ).count(),
        'unassigned': unassigned,
        'unassigned_total': StaffDutySchedule.objects.filter(
            is_active=True,
            employee__isnull=True,
            status__in=(StaffDutySchedule.STATUS_PENDING, StaffDutySchedule.STATUS_SCHEDULED),
        ).count(),
        'overdue_past': overdue_past,
        'marked_overdue': marked_overdue,
        'conflicts': conflicts[:ALERT_PREVIEW_LIMIT],
        'conflicts_total': len(conflicts),
        'has_alerts': bool(
            upcoming or unassigned or overdue_past or marked_overdue or conflicts
        ),
    }


def completed_schedules_queryset(filters: dict):
    qs = (
        StaffDutySchedule.objects.filter(
            is_active=True,
            status=StaffDutySchedule.STATUS_COMPLETED,
        )
        .select_related(
            'employee',
            'project',
            'project__customer',
            'amc_contract',
            'amc_contract__customer',
        )
        .order_by('-duty_date', 'start_time')
    )
    qs = _apply_date_range(qs, filters.get('date_from'), filters.get('date_to'))

    contract = filters.get('contract')
    if contract:
        try:
            cid = int(contract)
            qs = qs.filter(amc_contract_id=cid)
        except (TypeError, ValueError):
            pass

    customer = filters.get('customer')
    if customer:
        try:
            cust_id = int(customer)
            qs = qs.filter(
                Q(project__customer_id=cust_id) | Q(amc_contract__customer_id=cust_id)
            )
        except (TypeError, ValueError):
            pass

    technician = filters.get('technician')
    if technician:
        try:
            qs = qs.filter(employee_id=int(technician))
        except (TypeError, ValueError):
            pass

    return qs


def schedule_row_export_dict(schedule: StaffDutySchedule) -> dict:
    contract_label = '—'
    if schedule.link_type == 'amc' and schedule.amc_contract_id:
        contract_label = schedule.amc_contract.contract_number
    elif schedule.link_type == 'project' and schedule.project_id:
        contract_label = schedule.project.project_code

    return {
        'duty_date': schedule.duty_date.strftime('%d/%m/%Y'),
        'time': schedule.time_display,
        'technician': schedule.employee.full_name if schedule.employee_id else 'Unassigned',
        'customer': _schedule_customer_name(schedule),
        'link_type': schedule.get_link_type_display(),
        'contract': contract_label,
        'target': schedule.target_label,
        'location': schedule.location or '—',
        'status': schedule.get_status_display(),
    }


def completed_export_payload(schedules, *, title: str) -> dict:
    return {
        'title': title,
        'columns': [
            {'key': 'duty_date', 'label': 'Date'},
            {'key': 'time', 'label': 'Time'},
            {'key': 'technician', 'label': 'Technician'},
            {'key': 'customer', 'label': 'Customer'},
            {'key': 'link_type', 'label': 'Link type'},
            {'key': 'contract', 'label': 'Contract / Project'},
            {'key': 'target', 'label': 'Assignment'},
            {'key': 'location', 'label': 'Location'},
            {'key': 'status', 'label': 'Status'},
        ],
        'rows': [schedule_row_export_dict(s) for s in schedules],
    }


def build_dashboard_context(params) -> dict:
    today = timezone.localdate()
    filters = parse_dashboard_filters(params)
    summary = build_summary(today, filters['date_from'], filters['date_to'])
    alerts = build_alerts(today)
    completed = list(completed_schedules_queryset(filters)[:200])

    return {
        'today': today,
        'filters': filters,
        'summary': summary,
        'alerts': alerts,
        'completed_schedules': completed,
        'filter_contracts': get_amc_contract_queryset(),
        'filter_customers': Customer.objects.filter(is_active=True).order_by('name', 'company'),
        'filter_technicians': get_hr_employee_queryset(),
    }
