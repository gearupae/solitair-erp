"""HR KPI scoring — projects, sales, and purchase tracks per employee."""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, Q

from apps.hr.models import Employee, EmployeeRemark

PROJECT_DEPT_KEYWORDS = ('project', 'operation', 'engineering', 'site', 'techn')
SALES_DEPT_KEYWORDS = ('sales', 'business', 'bd', 'commercial')
PURCHASE_DEPT_KEYWORDS = ('purchase', 'procurement', 'procure')

PROJECT_COMPLETED = ('completed', 'completed_payment_pending')
PROJECT_OPEN = ('planning', 'ongoing', 'on_hold', 'ongoing_payment_received')
PR_SUCCESS = ('converted',)
PR_TOTAL_EXCLUDE = ('draft',)
PO_SUCCESS = ('received',)
PO_TOTAL_EXCLUDE = ('cancelled', 'draft')


@dataclass
class KpiRow:
    employee_id: int
    employee_name: str
    employee_code: str
    department_name: str
    user_id: int | None
    completed: int
    total: int
    in_progress: int
    work_pct: float
    score_pct: float
    work_points: int
    remark_points: int
    total_score: int
    breakdown: str
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            'employee_id': self.employee_id,
            'employee_name': self.employee_name,
            'employee_code': self.employee_code,
            'department_name': self.department_name,
            'user_id': self.user_id,
            'completed': self.completed,
            'total': self.total,
            'in_progress': self.in_progress,
            'work_pct': self.work_pct,
            'score_pct': self.score_pct,
            'work_points': self.work_points,
            'remark_points': self.remark_points,
            'total_score': self.total_score,
            'breakdown': self.breakdown,
            'detail': self.detail,
        }


def _dept_matches(dept, keywords: tuple[str, ...]) -> bool:
    if not dept:
        return False
    blob = f'{(dept.name or "").lower()} {(getattr(dept, "code", "") or "").lower()}'
    return any(k in blob for k in keywords)


def _pct(completed: int, total: int, remark_points: int = 0) -> float:
    """Score % = (work done + HR points) ÷ total × 100."""
    if not total:
        return 0.0
    adjusted = completed + remark_points
    return round(max(0.0, adjusted / total * 100), 1)


def _remark_points(employee_id: int) -> int:
    return EmployeeRemark.score_for_employee(employee_id)


def _project_metrics(user) -> dict:
    from apps.projects.models import Project, Task
    from django.utils import timezone

    today = timezone.localdate()

    if not user:
        return {'completed': 0, 'total': 0, 'in_progress': 0, 'breakdown': '—', 'detail': {}}

    tasks = Task.objects.filter(is_active=True, assigned_to=user)
    t_done = tasks.filter(status='completed').count()
    t_total = tasks.count()
    t_ip = tasks.filter(status='in_progress').count()
    t_pending = tasks.filter(status='pending').count()
    t_overdue = tasks.filter(
        status__in=('pending', 'in_progress'),
        due_date__lt=today,
    ).count()

    projects = Project.objects.filter(is_active=True, manager=user).exclude(status__in=('draft', 'cancelled'))
    p_done = projects.filter(status__in=PROJECT_COMPLETED).count()
    p_total = projects.count()
    p_open = projects.filter(status__in=PROJECT_OPEN).count()
    p_delayed = projects.filter(
        status__in=PROJECT_OPEN,
        end_date__lt=today,
        end_date__isnull=False,
    ).count()

    completed = t_done + p_done
    total = t_total + p_total
    # Prefer dominant assignment type (PM = projects only, engineer = tasks only)
    if p_total > 0 and t_total == 0:
        completed, total = p_done, p_total
    elif t_total > 0 and p_total == 0:
        completed, total = t_done, t_total

    in_progress = t_ip + t_pending + p_open

    parts = []
    if t_total:
        tp = round(t_done / t_total * 100, 1) if t_total else 0
        parts.append(f'{t_done}/{t_total} tasks ({tp}%)')
    if p_total:
        pp = round(p_done / p_total * 100, 1) if p_total else 0
        parts.append(f'{p_done}/{p_total} projects ({pp}%)')
    if t_overdue or p_delayed:
        parts.append(f'{t_overdue + p_delayed} delayed')
    breakdown = ' · '.join(parts) if parts else 'No assigned work'

    return {
        'completed': completed,
        'total': total,
        'in_progress': in_progress,
        'breakdown': breakdown,
        'detail': {
            'tasks_completed': t_done,
            'tasks_total': t_total,
            'tasks_in_progress': t_ip,
            'tasks_pending': t_pending,
            'tasks_overdue': t_overdue,
            'projects_completed': p_done,
            'projects_total': p_total,
            'projects_open': p_open,
            'projects_delayed': p_delayed,
        },
    }


def _sales_metrics(user) -> dict:
    from apps.crm.models import Customer
    from apps.sales.models import Estimate

    if not user:
        return {'completed': 0, 'total': 0, 'in_progress': 0, 'breakdown': '—', 'detail': {}}

    leads = Customer.objects.filter(is_active=True, assigned_salesperson__user=user)
    leads_won = leads.filter(
        Q(lead_kanban_stage__converts_to_customer=True) | Q(customer_type='customer'),
    ).distinct().count()
    leads_total = leads.count()
    leads_open = max(0, leads_total - leads_won)

    estimates = Estimate.objects.filter(is_active=True, assigned_to=user)
    est_won = estimates.filter(status='quotation_won').count()
    est_approved = estimates.filter(status='approved').count()
    est_total = estimates.count()
    est_success = est_won + est_approved
    est_open = max(0, est_total - est_success)

    # Leads: converted/total · Quotes: (won+approved)/total
    completed = leads_won + est_success
    total = leads_total + est_total
    in_progress = leads_open + est_open

    parts = []
    if leads_total:
        lp = round(leads_won / leads_total * 100, 1) if leads_total else 0
        parts.append(f'{leads_won}/{leads_total} leads ({lp}%)')
    if est_total:
        ep = round(est_success / est_total * 100, 1) if est_total else 0
        parts.append(f'{est_success}/{est_total} quotes ({ep}%)')
    breakdown = ' · '.join(parts) if parts else 'No assigned work'

    return {
        'completed': completed,
        'total': total,
        'in_progress': in_progress,
        'breakdown': breakdown,
        'detail': {
            'leads_won': leads_won,
            'leads_total': leads_total,
            'quotations_won': est_won,
            'quotations_approved': est_approved,
            'quotations_success': est_success,
            'quotations_total': est_total,
        },
    }


def _purchase_metrics(user) -> dict:
    from apps.purchase.models import PurchaseOrder, PurchaseRequest

    if not user:
        return {'completed': 0, 'total': 0, 'in_progress': 0, 'breakdown': '—', 'detail': {}}

    prs = PurchaseRequest.objects.filter(is_active=True, requested_by=user).exclude(status__in=PR_TOTAL_EXCLUDE)
    pr_done = prs.filter(status__in=PR_SUCCESS).count()
    pr_total = prs.count()
    pr_open = prs.exclude(status__in=PR_SUCCESS + ('rejected',)).count()

    pos = PurchaseOrder.objects.filter(is_active=True).filter(
        Q(created_by=user) | Q(purchase_request__requested_by=user),
    ).exclude(status__in=PO_TOTAL_EXCLUDE)
    po_done = pos.filter(status__in=PO_SUCCESS).count()
    po_total = pos.count()
    po_open = pos.exclude(status__in=PO_SUCCESS + ('cancelled',)).count()

    completed = pr_done + po_done
    total = pr_total + po_total
    in_progress = pr_open + po_open

    parts = []
    if pr_total:
        pp = round(pr_done / pr_total * 100, 1) if pr_total else 0
        parts.append(f'{pr_done}/{pr_total} PRs ({pp}%)')
    if po_total:
        pop = round(po_done / po_total * 100, 1) if po_total else 0
        parts.append(f'{po_done}/{po_total} POs ({pop}%)')
    breakdown = ' · '.join(parts) if parts else 'No assigned work'

    return {
        'completed': completed,
        'total': total,
        'in_progress': in_progress,
        'breakdown': breakdown,
        'detail': {
            'pr_converted': pr_done,
            'pr_total': pr_total,
            'po_received': po_done,
            'po_total': po_total,
        },
    }


TRACK_METRICS = {
    'project': _project_metrics,
    'sales': _sales_metrics,
    'purchase': _purchase_metrics,
}

TRACK_LABELS = {
    'project': 'Projects & operations',
    'sales': 'Sales',
    'purchase': 'Purchase & procurement',
}

TRACK_DEPT_KEYWORDS = {
    'project': PROJECT_DEPT_KEYWORDS,
    'sales': SALES_DEPT_KEYWORDS,
    'purchase': PURCHASE_DEPT_KEYWORDS,
}


def _employees_for_track(track: str) -> list[Employee]:
    from apps.hr.models import Department

    keywords = TRACK_DEPT_KEYWORDS[track]
    dept_match_ids = [d.pk for d in Department.objects.filter(is_active=True) if _dept_matches(d, keywords)]

    qs = Employee.objects.filter(is_active=True, status='active').select_related('department', 'user')

    activity_ids: set[int] = set()
    metric_fn = TRACK_METRICS[track]
    for emp in qs.filter(user__isnull=False):
        m = metric_fn(emp.user)
        if m['total'] > 0 or m['completed'] > 0:
            activity_ids.add(emp.pk)

    combined = qs.filter(Q(department_id__in=dept_match_ids) | Q(pk__in=activity_ids)).distinct()
    return list(combined.order_by('department__name', 'first_name', 'last_name'))


def _build_row(emp: Employee, track: str) -> KpiRow:
    metric_fn = TRACK_METRICS[track]
    m = metric_fn(emp.user)
    remark = _remark_points(emp.pk)
    work_points = m['completed']
    raw_work_pct = _pct(m['completed'], m['total'], 0)
    score_pct = _pct(m['completed'], m['total'], remark)
    return KpiRow(
        employee_id=emp.pk,
        employee_name=emp.full_name,
        employee_code=emp.employee_code,
        department_name=emp.department.name if emp.department_id else '—',
        user_id=emp.user_id,
        completed=m['completed'],
        total=m['total'],
        in_progress=m['in_progress'],
        work_pct=raw_work_pct,
        score_pct=score_pct,
        work_points=work_points,
        remark_points=remark,
        total_score=int(round(score_pct)),
        breakdown=m['breakdown'],
        detail=m['detail'],
    )


def build_track_rows(track: str) -> list[dict]:
    rows = [_build_row(emp, track).as_dict() for emp in _employees_for_track(track)]
    rows.sort(key=lambda r: (-r['score_pct'], r['employee_name']))
    return rows


def build_kpi_dashboard() -> dict:
    tracks = {}
    for key in ('project', 'sales', 'purchase'):
        tracks[key] = {
            'key': key,
            'label': TRACK_LABELS[key],
            'rows': build_track_rows(key),
        }

    overall_map: dict[int, dict] = {}
    for track_key, track_data in tracks.items():
        for row in track_data['rows']:
            eid = row['employee_id']
            if eid not in overall_map:
                overall_map[eid] = {
                    'employee_id': eid,
                    'employee_name': row['employee_name'],
                    'employee_code': row['employee_code'],
                    'department_name': row['department_name'],
                    'track_pcts': {'project': None, 'sales': None, 'purchase': None},
                    'completed_sum': 0,
                    'total_sum': 0,
                    'remark_points': row['remark_points'],
                }
            rec = overall_map[eid]
            if row['total'] > 0:
                rec['track_pcts'][track_key] = row['score_pct']
                rec['completed_sum'] += row['completed']
                rec['total_sum'] += row['total']
            rec['remark_points'] = row['remark_points']

    overall = []
    for rec in overall_map.values():
        rec['overall_pct'] = _pct(rec['completed_sum'], rec['total_sum'], rec['remark_points'])
        overall.append(rec)

    overall.sort(key=lambda r: (-r['overall_pct'], r['employee_name']))
    return {'tracks': tracks, 'overall': overall}
