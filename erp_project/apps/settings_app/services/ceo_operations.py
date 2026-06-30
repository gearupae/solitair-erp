"""Projects and HR overview metrics for the CEO dashboard."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from django.db.models import Count, Max
from django.utils import timezone

from apps.hr.models import Employee, LeaveRequest
from apps.hr.models_extended import AttendanceRecord
from apps.projects.models import Project, Task

ACTIVE_PROJECT_STATUSES = ('planning', 'ongoing', 'on_hold', 'ongoing_payment_received')
OPEN_PROJECT_STATUSES = ACTIVE_PROJECT_STATUSES
COMPLETED_STATUSES = ('completed', 'completed_payment_pending')
STALL_DAYS = 14
MAX_PROJECTS_PER_MANAGER = 5
ABSENCE_SPIKE_PCT = 25


def _today() -> date:
    return timezone.localdate()


def _last_activity_date(project: Project) -> date | None:
    from apps.hr.models_extended import AttendanceRecord as AttRec
    from apps.projects.models import ProjectExpense, ProjectItemDelivery

    candidates: list[date] = []
    t = Task.objects.filter(project=project, is_active=True).aggregate(m=Max('updated_at'))
    if t['m']:
        candidates.append(timezone.localtime(t['m']).date())
    e = ProjectExpense.objects.filter(project=project, is_active=True).aggregate(m=Max('expense_date'))
    if e['m']:
        candidates.append(e['m'])
    d = ProjectItemDelivery.objects.filter(project=project).aggregate(m=Max('delivered_date'))
    if d['m']:
        candidates.append(d['m'])
    a = AttRec.objects.filter(project=project, is_active=True).aggregate(m=Max('date'))
    if a['m']:
        candidates.append(a['m'])
    return max(candidates) if candidates else None


def _completed_count_between(start: date, end: date) -> int:
    return Project.objects.filter(
        is_active=True,
        status__in=COMPLETED_STATUSES,
        updated_at__date__gte=start,
        updated_at__date__lte=end,
    ).count()


def _tasks_completed_on(day: date) -> int:
    return Task.objects.filter(
        is_active=True,
        status='completed',
        updated_at__date=day,
    ).count()


def _attendance_snapshot(on_date: date) -> dict:
    """Attendance counts for a given date (active employees only)."""
    from apps.hr.attendance_utils import holiday_on_date_for_employee, is_uae_weekend

    employees = Employee.objects.filter(is_active=True, status='active')
    active_ids = list(employees.values_list('pk', flat=True))
    total = len(active_ids)
    if not total:
        return {
            'total_active': 0,
            'present': 0,
            'absent': 0,
            'late': 0,
            'not_marked': 0,
            'attendance_rate': None,
        }

    records_by_emp: dict[int, list] = {}
    for r in AttendanceRecord.objects.filter(
        is_active=True, date=on_date, employee_id__in=active_ids,
    ).order_by('employee_id', '-pk'):
        records_by_emp.setdefault(r.employee_id, []).append(r)

    present = absent = late = not_marked = 0
    for emp in employees:
        sessions = records_by_emp.get(emp.pk, [])
        if not sessions:
            if is_uae_weekend(on_date) or holiday_on_date_for_employee(on_date, emp):
                continue
            not_marked += 1
            continue
        if any(s.check_in for s in sessions):
            present += 1
            if any(s.status == 'late' for s in sessions):
                late += 1
            continue
        st = sessions[0].status
        if st == 'absent':
            absent += 1
        elif st == 'late':
            late += 1
            present += 1
        elif st in ('weekend', 'holiday'):
            pass
        elif st == 'half_day':
            present += 1
        else:
            present += 1

    working = present + absent + not_marked
    rate = round(present / working * 100, 1) if working else None
    return {
        'total_active': total,
        'present': present,
        'absent': absent,
        'late': late,
        'not_marked': not_marked,
        'attendance_rate': rate,
    }


def _headcount_movement(month_start: date, month_end: date) -> dict:
    joiners = Employee.objects.filter(
        is_active=True,
        date_of_joining__gte=month_start,
        date_of_joining__lte=month_end,
    ).count()
    leavers = Employee.objects.filter(
        is_active=True,
        status='terminated',
        updated_at__date__gte=month_start,
        updated_at__date__lte=month_end,
    ).count()
    return {'joiners': joiners, 'leavers': leavers, 'net': joiners - leavers}


def _expiring_documents(within_days: int = 30) -> dict:
    from apps.hr.expiry_alerts import get_expiry_alerts

    rows = get_expiry_alerts()
    expired = [r for r in rows if r['days_remaining'] < 0]
    expiring = [r for r in rows if 0 <= r['days_remaining'] <= within_days]
    return {
        'expired_count': len(expired),
        'expiring_30d_count': len(expiring) + len(expired),
        'employees_affected': len({r['employee_id'] for r in expired + expiring}),
    }


def build_projects_overview(*, prev_snap: dict | None = None, yesterday_snap: dict | None = None) -> dict:
    today = _today()
    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)

    y, m = today.year, today.month
    m -= 1
    if m <= 0:
        m = 12
        y -= 1
    last_month_start = date(y, m, 1)
    last_month_end = date(y, m, monthrange(y, m)[1])

    active_qs = Project.objects.filter(is_active=True, status__in=OPEN_PROJECT_STATUSES)
    active_count = active_qs.count()

    delayed_qs = active_qs.filter(end_date__lt=today, end_date__isnull=False)
    delayed_count = delayed_qs.count()
    on_track_count = max(0, active_count - delayed_count)
    on_track_pct = int(on_track_count / active_count * 100) if active_count else 0
    delayed_pct = int(delayed_count / active_count * 100) if active_count else 0

    completed_mtd = _completed_count_between(month_start, today)
    completed_last_month = _completed_count_between(last_month_start, last_month_end)

    progress_vals = []
    for p in Project.objects.filter(is_active=True, status='ongoing').only('pk'):
        progress_vals.append(p.task_progress_percent)
    avg_progress = round(sum(progress_vals) / len(progress_vals), 1) if progress_vals else 0.0

    overdue_tasks = Task.objects.filter(
        is_active=True,
        project__is_active=True,
        project__status__in=OPEN_PROJECT_STATUSES,
        status__in=('pending', 'in_progress'),
        due_date__lt=today,
    ).count()

    tasks_yesterday = _tasks_completed_on(yesterday)
    tasks_day_before = _tasks_completed_on(yesterday - timedelta(days=1))

    stalled_count = 0
    for project in active_qs.filter(status__in=('planning', 'ongoing')).iterator(chunk_size=50):
        last = _last_activity_date(project)
        if last is None:
            if project.start_date and (today - project.start_date).days >= STALL_DAYS:
                stalled_count += 1
        elif (today - last).days >= STALL_DAYS:
            stalled_count += 1

    manager_loads = (
        Project.objects.filter(is_active=True, status__in=OPEN_PROJECT_STATUSES, manager_id__isnull=False)
        .values('manager_id')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=MAX_PROJECTS_PER_MANAGER)
    )
    overloaded_managers = manager_loads.count()

    prev_projects = (prev_snap or {}).get('projects') or {}
    yday_projects = (yesterday_snap or {}).get('projects') or {}

    issue_flags: list[dict] = []
    if delayed_count:
        issue_flags.append({
            'severity': 'high',
            'title': 'Projects past deadline',
            'detail': f"{delayed_count} active project(s) are past their end date.",
            'action': 'Review delayed projects with managers and reset delivery dates or escalate resources.',
        })
    if stalled_count:
        issue_flags.append({
            'severity': 'medium',
            'title': 'Stalled projects',
            'detail': f"{stalled_count} project(s) with no activity in {STALL_DAYS}+ days.",
            'action': 'Check in with project leads and unblock site or procurement issues.',
        })
    if overloaded_managers:
        issue_flags.append({
            'severity': 'medium',
            'title': 'Resource overload',
            'detail': f"{overloaded_managers} manager(s) assigned to more than {MAX_PROJECTS_PER_MANAGER} active projects.",
            'action': 'Rebalance project ownership or defer non-critical work.',
        })

    return {
        'active_count': active_count,
        'on_track_count': on_track_count,
        'on_track_pct': on_track_pct,
        'delayed_count': delayed_count,
        'delayed_pct': delayed_pct,
        'completed_mtd': completed_mtd,
        'completed_last_month': completed_last_month,
        'avg_progress_pct': avg_progress,
        'overdue_tasks': overdue_tasks,
        'tasks_completed_yesterday': tasks_yesterday,
        'tasks_completed_prev_day': tasks_day_before,
        'stalled_count': stalled_count,
        'overloaded_managers': overloaded_managers,
        'vs_last_month': {
            'completed': completed_mtd - completed_last_month,
            'active': active_count - prev_projects.get('active_count', active_count),
            'avg_progress': avg_progress - prev_projects.get('avg_progress_pct', avg_progress),
        },
        'yesterday': {
            'tasks_completed': tasks_yesterday,
            'tasks_completed_delta': tasks_yesterday - yday_projects.get('tasks_completed_yesterday', tasks_yesterday),
        },
        'issue_flags': issue_flags,
    }


def build_hr_overview(*, prev_snap: dict | None = None, yesterday_snap: dict | None = None) -> dict:
    today = _today()
    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)

    y, m = today.year, today.month
    m -= 1
    if m <= 0:
        m = 12
        y -= 1
    last_month_start = date(y, m, 1)
    last_month_end = date(y, m, monthrange(y, m)[1])

    headcount = Employee.objects.filter(is_active=True, status='active').count()
    movement_mtd = _headcount_movement(month_start, today)
    movement_last_month = _headcount_movement(last_month_start, last_month_end)

    att_yesterday = _attendance_snapshot(yesterday)
    att_day_before = _attendance_snapshot(yesterday - timedelta(days=1))

    pending_leave = LeaveRequest.objects.filter(
        is_active=True,
        status__in=('pending_manager', 'pending_hr'),
    ).count()

    docs = _expiring_documents(30)

    prev_hr = (prev_snap or {}).get('hr') or {}
    yday_hr = (yesterday_snap or {}).get('hr') or {}
    prev_headcount = prev_hr.get('headcount')

    issue_flags: list[dict] = []
    if docs['expired_count']:
        issue_flags.append({
            'severity': 'high',
            'title': 'Expired employee documents',
            'detail': f"{docs['expired_count']} document(s) already expired across {docs['employees_affected']} employee(s).",
            'action': 'Renew visas, labour cards, and insurance immediately to avoid compliance risk.',
        })
    elif docs['expiring_30d_count']:
        issue_flags.append({
            'severity': 'medium',
            'title': 'Documents expiring within 30 days',
            'detail': f"{docs['expiring_30d_count']} document(s) need renewal soon.",
            'action': 'Start renewals this week and assign owners per employee.',
        })

    absent_yesterday = att_yesterday.get('absent', 0)
    absent_prev = att_day_before.get('absent', 0)
    total_active = att_yesterday.get('total_active') or 0
    if total_active and absent_yesterday >= 3:
        absent_pct = absent_yesterday / total_active * 100
        if absent_pct >= ABSENCE_SPIKE_PCT or absent_yesterday >= absent_prev + 2:
            issue_flags.append({
                'severity': 'medium',
                'title': 'Unusual absences yesterday',
                'detail': f"{absent_yesterday} absent of {total_active} active staff ({absent_pct:.0f}%).",
                'action': 'Confirm coverage for critical roles and follow up with line managers.',
            })

    if pending_leave >= 5:
        issue_flags.append({
            'severity': 'low',
            'title': 'Leave approvals backlog',
            'detail': f"{pending_leave} leave request(s) awaiting approval.",
            'action': 'Clear pending manager and HR approvals to avoid payroll surprises.',
        })

    return {
        'headcount': headcount,
        'joiners_mtd': movement_mtd['joiners'],
        'leavers_mtd': movement_mtd['leavers'],
        'net_headcount_mtd': movement_mtd['net'],
        'joiners_last_month': movement_last_month['joiners'],
        'leavers_last_month': movement_last_month['leavers'],
        'open_positions': None,
        'open_positions_tracked': False,
        'pending_leave': pending_leave,
        'docs_expired': docs['expired_count'],
        'docs_expiring_30d': docs['expiring_30d_count'],
        'attendance_yesterday': att_yesterday,
        'vs_last_month': {
            'headcount': headcount - prev_headcount if prev_headcount is not None else None,
            'net_vs_last_month': movement_mtd['net'] - movement_last_month['net'],
        },
        'yesterday': {
            'present': att_yesterday.get('present', 0),
            'absent': att_yesterday.get('absent', 0),
            'attendance_rate': att_yesterday.get('attendance_rate'),
            'pending_leave': pending_leave,
        },
        'issue_flags': issue_flags,
    }
