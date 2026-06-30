"""Estimation dashboard metrics and chart payloads."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.crm.models import Customer
from apps.hr.models import Employee
from apps.sales.models import Estimate, EstimateRevisionSnapshot

ZERO = Decimal('0.00')

QUOTATION_PIPELINE_STATUSES = frozenset({
    'under_negotiation',
    'quotation_won',
    'quotation_lost',
})

DASHBOARD_MODES = {
    'estimate': {
        'title': 'Estimation Dashboard',
        'list_url_name': 'sales:estimate_list',
        'list_link_label': 'Estimates',
        'all_time_label': 'All estimates (same as Estimates list)',
        'record_label': 'estimate',
        'record_label_plural': 'estimates',
        'charts': {
            'over_time': 'Estimations Over Time',
            'status': 'Estimation Status',
            'revised': 'Revised Estimations Overview',
            'source': 'Estimations by Request Source',
            'project_type': 'Estimations by Project Type',
            'estimator': 'Estimations by Estimator',
            'lost_reason': 'Lost Estimations by Reason',
        },
        'kpis': (
            ('estimation_requests', 'Estimation Requests', 'int'),
            ('total_estimations', 'Total Estimations', 'int'),
            ('estimation_value', 'Estimation Value', 'money'),
            ('revised_estimations', 'Revised Estimations', 'int'),
            ('conversion_rate', 'Conversion Rate', 'pct'),
            ('approved_estimations', 'Approved Estimations', 'int'),
            ('rejected_estimations', 'Rejected Estimations', 'int'),
            ('pending_estimations', 'Pending Estimations', 'int'),
            ('lost_estimations', 'Lost Estimations', 'int'),
        ),
        'status_donut': (
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('pending', 'Pending'),
            ('lost', 'Lost'),
        ),
    },
    'quotation': {
        'title': 'Quotation Dashboard',
        'list_url_name': 'sales:quotation_list',
        'list_link_label': 'Quotations',
        'all_time_label': 'All quotations (same as Quotations list)',
        'record_label': 'quotation',
        'record_label_plural': 'quotations',
        'charts': {
            'over_time': 'Quotations Over Time',
            'status': 'Quotation Status',
            'revised': 'Revised Quotations Overview',
            'source': 'Quotations by Request Source',
            'project_type': 'Quotations by Project Type',
            'estimator': 'Quotations by Estimator',
            'lost_reason': 'Lost Quotations by Reason',
        },
        'kpis': (
            ('estimation_requests', 'Quotation Requests', 'int'),
            ('total_estimations', 'Total Quotations', 'int'),
            ('estimation_value', 'Quotation Value', 'money'),
            ('revised_estimations', 'Revised Quotations', 'int'),
            ('conversion_rate', 'Conversion Rate', 'pct'),
            ('approved_estimations', 'Quot Won', 'int'),
            ('pending_estimations', 'Under Negotiation', 'int'),
            ('lost_estimations', 'Quot Lost', 'int'),
            ('won_value', 'Won Value', 'money'),
        ),
        'status_donut': (
            ('won', 'Quot Won'),
            ('negotiation', 'Under Negotiation'),
            ('lost', 'Quot Lost'),
        ),
    },
}

PROJECT_TYPE_LABELS = {
    'residential': 'Residential',
    'villa': 'Residential',
    'commercial': 'Commercial',
    'restaurants': 'Commercial',
    'factories_industries': 'Industrial',
    'labour_accommodation': 'Infrastructure',
    '': 'Others',
}

LOST_REASON_RULES = (
    ('price', 'Price High'),
    ('high', 'Price High'),
    ('expensive', 'Price High'),
    ('competitor', 'Competitor'),
    ('competition', 'Competitor'),
    ('requirement', 'Requirement Change'),
    ('scope', 'Requirement Change'),
    ('change', 'Requirement Change'),
    ('no response', 'No Response'),
    ('unresponsive', 'No Response'),
    ('ghost', 'No Response'),
)

REQUEST_SOURCE_RULES = (
    ('email', 'Email'),
    ('@', 'Email'),
    ('phone', 'Phone Call'),
    ('call', 'Phone Call'),
    ('mobile', 'Phone Call'),
    ('walk-in', 'Walk-in'),
    ('walk in', 'Walk-in'),
    ('visit', 'Walk-in'),
    ('website', 'Website'),
    ('online', 'Website'),
    ('web', 'Website'),
)


def default_week_range(today: date | None = None) -> tuple[date, date]:
    today = today or timezone.localdate()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def base_estimates_queryset(user, *, mode: str = 'estimate'):
    """Same visible scope as Sales → Estimates / Quotations list."""
    from apps.core.visibility import filter_estimates_for_user

    qs = filter_estimates_for_user(
        Estimate.objects.filter(is_active=True),
        user,
    )
    if mode == 'quotation':
        qs = qs.filter(status__in=QUOTATION_PIPELINE_STATUSES)
    return qs.select_related('customer', 'assigned_to', 'created_by', 'sales_engineer')


def resolve_date_range(
    user,
    date_from_raw: str | None,
    date_to_raw: str | None,
    *,
    today: date | None = None,
) -> tuple[date | None, date | None, bool]:
    """
    Return (date_from, date_to, all_time).
    When no dates in the query string, show all estimates like the list page.
    """
    today = today or timezone.localdate()
    from_raw = (date_from_raw or '').strip()
    to_raw = (date_to_raw or '').strip()
    if not from_raw and not to_raw:
        return None, None, True

    default_start, default_end = default_week_range(today)

    def _parse(raw, fallback):
        if not raw:
            return fallback
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return fallback

    start = _parse(from_raw, default_start)
    end = _parse(to_raw, default_end)
    if end < start:
        start, end = end, start
    return start, end, False


def parse_date_range(
    date_from_raw: str | None,
    date_to_raw: str | None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """Legacy helper — bounded range only."""
    today = today or timezone.localdate()
    default_start, default_end = default_week_range(today)
    start, end, _ = resolve_date_range(user=None, date_from_raw=date_from_raw, date_to_raw=date_to_raw, today=today)
    if start is None or end is None:
        return default_start, default_end
    return start, end


def previous_period(date_from: date, date_to: date) -> tuple[date, date]:
    days = (date_to - date_from).days + 1
    prev_end = date_from - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return prev_start, prev_end


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100.0


def _delta_meta(current: float, previous: float) -> dict:
    change = _pct_change(current, previous)
    if change is None:
        direction = 'neutral'
    elif change > 0.05:
        direction = 'up'
    elif change < -0.05:
        direction = 'down'
    else:
        direction = 'neutral'
    return {
        'current': current,
        'previous': previous,
        'change_pct': round(change or 0.0, 1),
        'direction': direction,
    }


def _money(val) -> float:
    if val is None:
        return 0.0
    return float(Decimal(str(val)).quantize(Decimal('0.01')))


def map_project_type(occupancy: str) -> str:
    return PROJECT_TYPE_LABELS.get((occupancy or '').strip(), 'Others')


def infer_request_source(estimate: Estimate) -> str:
    if estimate.submitted_via_public_link:
        return 'Website'
    blob = ' '.join(
        filter(
            None,
            [
                estimate.notes or '',
                estimate.client_note or '',
                getattr(estimate.customer, 'notes', '') or '',
            ],
        )
    ).lower()
    for keyword, label in REQUEST_SOURCE_RULES:
        if keyword in blob:
            return label
    if estimate.created_by_id and not estimate.submitted_via_public_link:
        return 'Walk-in'
    return 'Other'


def infer_lost_reason(text: str) -> str:
    blob = (text or '').lower()
    for keyword, label in LOST_REASON_RULES:
        if keyword in blob:
            return label
    return 'Other'


def _estimator_label(estimate: Estimate) -> str:
    prepared = (estimate.prepared_by or '').strip()
    if prepared:
        return prepared
    if estimate.created_by_id:
        u = estimate.created_by
        return (u.get_full_name() or u.username).strip()
    return 'Unassigned'


def _salesman_label(estimate: Estimate) -> str:
    if estimate.assigned_to_id:
        u = estimate.assigned_to
        return (u.get_full_name() or u.username).strip()
    return 'Unassigned'


def _sales_person_label(estimate: Estimate) -> str:
    if estimate.sales_engineer_id:
        return estimate.sales_engineer.full_name
    return 'Unassigned'


def _apply_filters(qs, *, estimator, sales_person, project_type, customer_id):
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if project_type:
        if project_type == 'Residential':
            qs = qs.filter(type_of_occupancy__in=['residential', 'villa'])
        elif project_type == 'Commercial':
            qs = qs.filter(type_of_occupancy__in=['commercial', 'restaurants'])
        elif project_type == 'Industrial':
            qs = qs.filter(type_of_occupancy='factories_industries')
        elif project_type == 'Infrastructure':
            qs = qs.filter(type_of_occupancy='labour_accommodation')
        elif project_type == 'Others':
            qs = qs.filter(
                Q(type_of_occupancy='') | Q(type_of_occupancy__isnull=True)
            )
    if sales_person:
        qs = qs.filter(sales_engineer_id=sales_person)
    if estimator:
        qs = qs.filter(
            Q(prepared_by__icontains=estimator)
            | Q(created_by__first_name__icontains=estimator)
            | Q(created_by__last_name__icontains=estimator)
            | Q(created_by__username__icontains=estimator)
        )
    return qs


def _status_bucket(status: str, *, mode: str = 'estimate') -> str:
    if mode == 'quotation':
        if status == 'quotation_won':
            return 'won'
        if status == 'under_negotiation':
            return 'negotiation'
        if status == 'quotation_lost':
            return 'lost'
        return 'negotiation'
    if status == 'approved':
        return 'approved'
    if status == 'rejected':
        return 'rejected'
    if status == 'quotation_lost':
        return 'lost'
    if status in ('draft', 'sent', 'under_negotiation'):
        return 'pending'
    if status == 'quotation_won':
        return 'approved'
    return 'pending'


def _kpi_block(qs_estimates, qs_requests, qs_revised, date_from=None, date_to=None, *, mode: str = 'estimate') -> dict:
    total = qs_estimates.count()
    requests = qs_requests.count()
    revised = qs_estimates.filter(revision_count__gt=0).count()
    if qs_revised.exists():
        revised = max(revised, qs_revised.values('estimate_id').distinct().count())
    value = _money(qs_estimates.aggregate(t=Sum('total_amount'))['t'])

    won = qs_estimates.filter(status='quotation_won').count()
    lost = qs_estimates.filter(status='quotation_lost').count()
    closed = won + lost
    conversion = (won / closed * 100.0) if closed else 0.0

    if mode == 'quotation':
        negotiation = qs_estimates.filter(status='under_negotiation').count()
        won_value = _money(
            qs_estimates.filter(status='quotation_won').aggregate(t=Sum('total_amount'))['t']
        )
        return {
            'estimation_requests': requests,
            'total_estimations': total,
            'estimation_value': value,
            'revised_estimations': revised,
            'conversion_rate': round(conversion, 1),
            'approved_estimations': won,
            'rejected_estimations': 0,
            'pending_estimations': negotiation,
            'lost_estimations': lost,
            'won_value': won_value,
        }

    approved = qs_estimates.filter(status__in=['approved', 'quotation_won']).count()
    rejected = qs_estimates.filter(status='rejected').count()
    pending = qs_estimates.filter(status__in=['draft', 'sent', 'under_negotiation']).count()
    lost_count = qs_estimates.filter(status='quotation_lost').count()

    return {
        'estimation_requests': requests,
        'total_estimations': total,
        'estimation_value': value,
        'revised_estimations': revised,
        'conversion_rate': round(conversion, 1),
        'approved_estimations': approved,
        'rejected_estimations': rejected,
        'pending_estimations': pending,
        'lost_estimations': lost_count,
        'won_value': _money(
            qs_estimates.filter(status__in=['approved', 'quotation_won']).aggregate(t=Sum('total_amount'))['t']
        ),
    }


def _filter_by_estimate_date(qs, date_from: date | None, date_to: date | None):
    if date_from is not None:
        qs = qs.filter(date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(date__lte=date_to)
    return qs


def _filter_by_created_date(qs, date_from: date | None, date_to: date | None):
    if date_from is not None:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


def _comparison_period(today: date | None = None) -> tuple[date, date, date, date]:
    """Last 30 days vs prior 30 days — used for KPI deltas in all-time mode."""
    today = today or timezone.localdate()
    current_end = today
    current_start = today - timedelta(days=29)
    prev_end = current_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=29)
    return current_start, current_end, prev_start, prev_end


def _timeline_buckets(qs, date_from: date | None, date_to: date | None) -> tuple[list[str], list[int]]:
    """Build chart labels/counts from estimate dates (daily, weekly, or monthly)."""
    bounds = qs.aggregate(min_d=Min('date'), max_d=Max('date'))
    min_d = bounds['min_d']
    max_d = bounds['max_d']
    if not min_d or not max_d:
        return [], []

    start = date_from or min_d
    end = date_to or max(max_d, timezone.localdate())
    span_days = (end - start).days + 1

    if span_days <= 31:
        labels = _daily_labels(start, end)
        counts = _daily_counts(qs, start, end, 'date')
        return labels, counts

    if span_days <= 120:
        labels = []
        counts = []
        week_start = start
        while week_start <= end:
            week_end = min(week_start + timedelta(days=6), end)
            labels.append(f'{week_start.strftime("%b %d")}–{week_end.strftime("%d")}')
            counts.append(qs.filter(date__gte=week_start, date__lte=week_end).count())
            week_start += timedelta(days=7)
        return labels, counts

    labels = []
    counts = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        month_end = min(next_month - timedelta(days=1), end)
        if month_end >= start:
            labels.append(cursor.strftime('%b %Y'))
            counts.append(qs.filter(date__gte=max(cursor, start), date__lte=month_end).count())
        cursor = next_month
    return labels, counts


def _revised_timeline(revised_qs, date_from: date | None, date_to: date | None) -> tuple[list[int], list[float]]:
    revised_by_day = defaultdict(lambda: {'count': 0, 'value': ZERO})
    snap_rows = (
        revised_qs.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(c=Count('id'), v=Sum('total_amount'))
    )
    for row in snap_rows:
        if row['day']:
            revised_by_day[row['day']] = {'count': row['c'], 'value': row['v'] or ZERO}

    if not revised_by_day:
        return [], []

    start = date_from or min(revised_by_day.keys())
    end = date_to or max(revised_by_day.keys())
    revised_counts = []
    revised_values = []
    d = start
    while d <= end:
        bucket = revised_by_day.get(d, {'count': 0, 'value': ZERO})
        revised_counts.append(bucket['count'])
        revised_values.append(_money(bucket['value']))
        d += timedelta(days=1)
    return revised_counts, revised_values


def _daily_labels(date_from: date, date_to: date) -> list[str]:
    labels = []
    d = date_from
    while d <= date_to:
        labels.append(d.strftime('%b %d'))
        d += timedelta(days=1)
    return labels


def _daily_counts(qs, date_from: date, date_to: date, date_field: str = 'date') -> list[int]:
    lookup = {date_from + timedelta(days=i): 0 for i in range((date_to - date_from).days + 1)}
    rows = (
        qs.filter(**{f'{date_field}__gte': date_from, f'{date_field}__lte': date_to})
        .values(date_field)
        .annotate(c=Count('id'))
    )
    for row in rows:
        lookup[row[date_field]] = row['c']
    return [lookup[date_from + timedelta(days=i)] for i in range((date_to - date_from).days + 1)]


def build_dashboard_context(
    *,
    user,
    date_from: date | None,
    date_to: date | None,
    all_time: bool = False,
    estimator: str = '',
    sales_person: str = '',
    project_type: str = '',
    customer_id: str = '',
    mode: str = 'estimate',
) -> dict:
    mode_cfg = DASHBOARD_MODES.get(mode, DASHBOARD_MODES['estimate'])
    base = base_estimates_queryset(user, mode=mode)

    filters = {
        'estimator': estimator.strip(),
        'sales_person': int(sales_person) if str(sales_person).isdigit() else '',
        'project_type': project_type.strip(),
        'customer_id': int(customer_id) if str(customer_id).isdigit() else '',
    }

    period_estimates = _apply_filters(
        _filter_by_estimate_date(base, date_from, date_to),
        **filters,
    )

    if all_time:
        cmp_cur_start, cmp_cur_end, cmp_prev_start, cmp_prev_end = _comparison_period()
        prev_estimates = _apply_filters(
            _filter_by_estimate_date(base, cmp_prev_start, cmp_prev_end),
            **filters,
        )
        delta_estimates = _apply_filters(
            _filter_by_estimate_date(base, cmp_cur_start, cmp_cur_end),
            **filters,
        )
        prev_from, prev_to = cmp_prev_start, cmp_prev_end
    else:
        prev_from, prev_to = previous_period(date_from, date_to)
        prev_estimates = _apply_filters(
            _filter_by_estimate_date(base, prev_from, prev_to),
            **filters,
        )
        delta_estimates = period_estimates

    request_qs = _apply_filters(
        _filter_by_created_date(base, date_from, date_to),
        **filters,
    )
    prev_requests = _apply_filters(
        _filter_by_created_date(base, prev_from, prev_to),
        **filters,
    )

    revised_filter = {'estimate__in': period_estimates}
    if not all_time and date_from and date_to:
        revised_filter['created_at__date__gte'] = date_from
        revised_filter['created_at__date__lte'] = date_to
    revised_qs = EstimateRevisionSnapshot.objects.filter(**revised_filter)

    prev_revised_filter = {'estimate__in': prev_estimates}
    if not all_time:
        prev_revised_filter['created_at__date__gte'] = prev_from
        prev_revised_filter['created_at__date__lte'] = prev_to
    prev_revised = EstimateRevisionSnapshot.objects.filter(**prev_revised_filter)

    current_kpi = _kpi_block(period_estimates, request_qs, revised_qs, date_from, date_to, mode=mode)
    if all_time:
        delta_kpi = _kpi_block(
            delta_estimates,
            _apply_filters(_filter_by_created_date(base, cmp_cur_start, cmp_cur_end), **filters),
            EstimateRevisionSnapshot.objects.filter(
                estimate__in=delta_estimates,
                created_at__date__gte=cmp_cur_start,
                created_at__date__lte=cmp_cur_end,
            ),
            cmp_cur_start,
            cmp_cur_end,
            mode=mode,
        )
        previous_kpi = _kpi_block(prev_estimates, prev_requests, prev_revised, prev_from, prev_to, mode=mode)
    else:
        delta_kpi = current_kpi
        previous_kpi = _kpi_block(prev_estimates, prev_requests, prev_revised, prev_from, prev_to, mode=mode)

    kpis = []
    for key, label, fmt in mode_cfg['kpis']:
        meta = _delta_meta(
            float(delta_kpi.get(key, 0) if all_time else current_kpi.get(key, 0)),
            float(previous_kpi.get(key, 0)),
        )
        meta['key'] = key
        meta['label'] = label
        meta['format'] = fmt
        meta['current'] = float(current_kpi.get(key, 0))
        kpis.append(meta)

    day_labels, over_time = _timeline_buckets(period_estimates, date_from, date_to)
    revised_counts, revised_values = _revised_timeline(revised_qs, date_from, date_to)
    if day_labels and len(revised_counts) != len(day_labels):
        # Align revised chart to main timeline length when sparse revision data
        revised_counts = revised_counts or [0] * len(day_labels)
        revised_values = revised_values or [0.0] * len(day_labels)
        if len(revised_counts) > len(day_labels):
            revised_counts = revised_counts[: len(day_labels)]
            revised_values = revised_values[: len(day_labels)]
        elif len(revised_counts) < len(day_labels):
            revised_counts = revised_counts + [0] * (len(day_labels) - len(revised_counts))
            revised_values = revised_values + [0.0] * (len(day_labels) - len(revised_values))

    status_counts = Counter()
    for row in period_estimates.values('status').annotate(c=Count('id')):
        status_counts[_status_bucket(row['status'], mode=mode)] += row['c']
    status_total = sum(status_counts.values()) or 1
    status_donut = [
        {
            'label': lbl,
            'count': status_counts.get(key, 0),
            'pct': round(status_counts.get(key, 0) / status_total * 100, 1),
        }
        for key, lbl in mode_cfg['status_donut']
    ]

    source_counter = Counter()
    for estimate in request_qs.iterator(chunk_size=500):
        source_counter[infer_request_source(estimate)] += 1
    source_total = sum(source_counter.values()) or 1
    source_donut = [
        {
            'label': lbl,
            'count': source_counter.get(lbl, 0),
            'pct': round(source_counter.get(lbl, 0) / source_total * 100, 1),
        }
        for lbl in ('Email', 'Phone Call', 'Website', 'Walk-in', 'Other')
    ]

    project_counter = Counter()
    for row in period_estimates.values('type_of_occupancy').annotate(c=Count('id')):
        project_counter[map_project_type(row['type_of_occupancy'])] += row['c']
    project_total = sum(project_counter.values()) or 1
    project_donut = [
        {
            'label': lbl,
            'count': project_counter.get(lbl, 0),
            'pct': round(project_counter.get(lbl, 0) / project_total * 100, 1),
        }
        for lbl in ('Residential', 'Commercial', 'Industrial', 'Infrastructure', 'Others')
    ]

    estimator_counter = Counter()
    for estimate in period_estimates.iterator(chunk_size=500):
        estimator_counter[_estimator_label(estimate)] += 1
    estimator_bars = [[name, count] for name, count in estimator_counter.most_common(12)]

    lost_estimates = period_estimates.filter(status='quotation_lost')
    lost_reason_counter = Counter()
    for estimate in lost_estimates.iterator(chunk_size=200):
        lost_reason_counter[infer_lost_reason(estimate.rejection_reason or estimate.notes)] += 1
    lost_total = sum(lost_reason_counter.values()) or 1
    lost_donut = [
        {
            'label': lbl,
            'count': lost_reason_counter.get(lbl, 0),
            'pct': round(lost_reason_counter.get(lbl, 0) / lost_total * 100, 1),
        }
        for lbl in ('Price High', 'Competitor', 'Requirement Change', 'No Response', 'Other')
        if lost_reason_counter.get(lbl, 0) > 0 or lbl != 'Other'
    ]
    if not lost_donut:
        lost_donut = [{'label': 'Other', 'count': 0, 'pct': 0.0}]

    # Filter option lists (same scope as list page)
    all_estimates = base_estimates_queryset(user, mode=mode)
    estimators = sorted(
        {
            lbl
            for lbl in (_estimator_label(e) for e in all_estimates.select_related('created_by')[:2000])
            if lbl and lbl != 'Unassigned'
        }
    )
    sales_persons = Employee.objects.filter(
        pk__in=all_estimates.exclude(sales_engineer__isnull=True).values_list('sales_engineer_id', flat=True).distinct(),
        is_active=True,
    ).order_by('first_name', 'last_name')
    customers = Customer.objects.filter(
        pk__in=all_estimates.values_list('customer_id', flat=True).distinct(),
        is_active=True,
    ).order_by('name', 'company')

    if all_time:
        period_label = mode_cfg['all_time_label']
        prev_label = 'Previous 30 days'
    else:
        period_label = f'{date_from.strftime("%b %d")} – {date_to.strftime("%b %d, %Y")}'
        prev_label = f'{prev_from.strftime("%b %d")} – {prev_to.strftime("%b %d, %Y")}'

    return {
        'date_from': date_from,
        'date_to': date_to,
        'date_from_iso': date_from.isoformat() if date_from else '',
        'date_to_iso': date_to.isoformat() if date_to else '',
        'all_time': all_time,
        'dashboard_mode': mode,
        'dashboard_ui': mode_cfg,
        'period_label': period_label,
        'prev_period_label': prev_label,
        'total_visible_estimates': period_estimates.count(),
        'filters': filters,
        'kpis': kpis,
        'day_labels': day_labels,
        'charts': {
            'over_time': over_time,
            'status_donut': status_donut,
            'status_total': status_total if status_total else 0,
            'revised_counts': revised_counts,
            'revised_values': revised_values,
            'source_donut': source_donut,
            'source_total': source_total,
            'project_donut': project_donut,
            'project_total': project_total,
            'estimator_bars': estimator_bars,
            'lost_donut': lost_donut,
            'lost_total': lost_total if lost_total else 0,
        },
        'filter_options': {
            'estimators': estimators,
            'sales_persons': sales_persons,
            'project_types': ['Residential', 'Commercial', 'Industrial', 'Infrastructure', 'Others'],
            'customers': customers,
        },
    }
