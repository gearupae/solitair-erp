"""CRM leads pipeline dashboard — KPIs and charts."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.crm.models import CrmLeadKanbanStage, Customer
from apps.crm.utils import annotate_latest_estimate_value
from apps.sales.models import Estimate
from apps.settings_app.models import AuditLog

ZERO = Decimal('0.00')

SOURCE_BUCKETS = (
    ('Website', ('website', 'web', 'online', 'public form', 'public')),
    ('Referral', ('reference', 'referral', 'refer')),
    ('Social Media', ('facebook', 'whatsapp', 'instagram', 'linkedin', 'social', 'twitter')),
    ('Email Campaign', ('email', '@', 'campaign', 'newsletter')),
)


def default_week_range(today: date | None = None) -> tuple[date, date]:
    today = today or timezone.localdate()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def resolve_date_range(
    date_from_raw: str | None,
    date_to_raw: str | None,
    *,
    today: date | None = None,
) -> tuple[date | None, date | None, bool]:
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


def previous_period(date_from: date, date_to: date) -> tuple[date, date]:
    days = (date_to - date_from).days + 1
    prev_end = date_from - timedelta(days=1)
    return prev_end - timedelta(days=days - 1), prev_end


def _comparison_period(today: date | None = None) -> tuple[date, date, date, date]:
    today = today or timezone.localdate()
    current_end = today
    current_start = today - timedelta(days=29)
    prev_end = current_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=29)
    return current_start, current_end, prev_start, prev_end


def _money(val) -> float:
    if val is None:
        return 0.0
    return float(Decimal(str(val)).quantize(Decimal('0.01')))


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100.0


def _delta_meta(current: float, previous: float) -> dict:
    change = _pct_change(current, previous)
    if change > 0.05:
        direction = 'up'
    elif change < -0.05:
        direction = 'down'
    else:
        direction = 'neutral'
    return {
        'current': current,
        'previous': previous,
        'change_pct': round(change, 1),
        'direction': direction,
    }


def base_leads_queryset(user):
    from apps.core.visibility import filter_customers_for_user

    return filter_customers_for_user(
        Customer.objects.filter(is_active=True, customer_type='lead'),
        user,
    ).select_related('lead_kanban_stage', 'assigned_salesperson')


def _visible_customer_ids(user):
    from apps.core.visibility import filter_customers_for_user

    return filter_customers_for_user(
        Customer.objects.filter(is_active=True),
        user,
    ).values_list('pk', flat=True)


def _filter_leads_by_created(qs, date_from: date | None, date_to: date | None):
    if date_from is not None:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


def _lost_stage_filter() -> Q:
    return Q(lead_kanban_stage__slug='lost') | Q(lead_kanban_stage__name__iexact='lost')


def _open_leads_qs(leads_qs):
    """Active pipeline leads — excludes Lost stage (matches open deals)."""
    return leads_qs.exclude(_lost_stage_filter())


def _won_audit_qs(user, date_from: date | None = None, date_to: date | None = None):
    visible_ids = _visible_customer_ids(user)
    qs = AuditLog.objects.filter(
        model='Customer',
        record_id__in=visible_ids,
    ).filter(
        Q(changes__action='kanban_won')
        | Q(changes__converted_to_customer=True)
        | Q(changes__action='converted_to_customer')
    )
    if date_from is not None:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(timestamp__date__lte=date_to)
    return qs


def _won_customer_ids(user, date_from: date | None, date_to: date | None) -> set[int]:
    ids: set[int] = set()
    for row in _won_audit_qs(user, date_from, date_to).values_list('record_id', flat=True):
        try:
            ids.add(int(row))
        except (TypeError, ValueError):
            continue
    return ids


def _won_deals_count(user, date_from: date | None, date_to: date | None) -> int:
    return len(_won_customer_ids(user, date_from, date_to))


def _won_deals_value(user, date_from: date | None, date_to: date | None) -> float:
    ids = _won_customer_ids(user, date_from, date_to)
    if not ids:
        return 0.0
    val = ZERO
    for cid in ids:
        est = (
            Estimate.objects.filter(is_active=True, customer_id=cid)
            .order_by('-date', '-id')
            .values_list('total_amount', flat=True)
            .first()
        )
        if est:
            val += est
    return _money(val)


def _pipeline_customer_ids(leads_qs, user, date_from: date | None, date_to: date | None) -> list[int]:
    ids = set(leads_qs.values_list('pk', flat=True))
    ids.update(_won_customer_ids(user, date_from, date_to))
    return list(ids)


def _sales_trend(
    leads_qs,
    user,
    date_from: date | None,
    date_to: date | None,
) -> tuple[list[str], list[float]]:
    from django.db.models import Min, Max

    customer_ids = _pipeline_customer_ids(leads_qs, user, date_from, date_to)
    if not customer_ids:
        return [], []

    est_qs = Estimate.objects.filter(is_active=True, customer_id__in=customer_ids)
    bounds = est_qs.aggregate(min_d=Min('date'), max_d=Max('date'))
    min_d = bounds['min_d']
    max_d = bounds['max_d']
    if not min_d or not max_d:
        bounds = leads_qs.aggregate(min_d=Min('created_at__date'), max_d=Max('created_at__date'))
        min_d = bounds['min_d']
        max_d = bounds['max_d']
    if not min_d or not max_d:
        return [], []

    start = date_from or min_d
    end = date_to or max(max_d, timezone.localdate())
    span = (end - start).days + 1

    daily = defaultdict(lambda: ZERO)
    for row in est_qs.filter(date__gte=start, date__lte=end).values('date').annotate(t=Sum('total_amount')):
        daily[row['date']] = row['t'] or ZERO

    if span <= 31:
        labels = []
        values = []
        d = start
        while d <= end:
            labels.append(d.strftime('%b %d'))
            values.append(_money(daily.get(d, ZERO)))
            d += timedelta(days=1)
        return labels, values

    labels = []
    values = []
    week_start = start
    while week_start <= end:
        week_end = min(week_start + timedelta(days=6), end)
        labels.append(f'{week_start.strftime("%b %d")}–{week_end.strftime("%d")}')
        total = ZERO
        d = week_start
        while d <= week_end:
            total += daily.get(d, ZERO)
            d += timedelta(days=1)
        values.append(_money(total))
        week_start += timedelta(days=7)
    return labels, values


def infer_lead_source(lead: Customer) -> str:
    if lead.lead_source:
        return lead.lead_source_display_label or lead.lead_source
    blob = ' '.join(
        filter(
            None,
            [
                (lead.notes or '').lower(),
                (lead.company or '').lower(),
                (lead.website or '').lower(),
            ],
        )
    )
    for label, keywords in SOURCE_BUCKETS:
        if any(k in blob for k in keywords):
            return label
    if lead.public_uploads.filter(is_active=True).exists():
        return 'Website'
    return 'Other'


def _pipeline_value(qs) -> float:
    annotated = annotate_latest_estimate_value(qs)
    total = annotated.aggregate(t=Sum('latest_estimate_value'))['t']
    return _money(total)


def _open_deals_count(qs) -> int:
    return _open_leads_qs(qs).count()


def _conversion_rate(total_leads: int, won: int) -> float:
    denominator = total_leads + won
    if not denominator:
        return 0.0
    return round(won / denominator * 100.0, 2)


def _kpi_snapshot(
    user,
    leads_qs,
    *,
    date_from: date | None,
    date_to: date | None,
) -> dict:
    total = leads_qs.count()
    open_deals = _open_deals_count(leads_qs)
    pipeline_value = _pipeline_value(_open_leads_qs(leads_qs))
    won = _won_deals_count(user, date_from, date_to)
    return {
        'total_leads': total,
        'open_deals': open_deals,
        'pipeline_value': pipeline_value,
        'won_deals': won,
        'conversion_rate': _conversion_rate(total, won),
    }


def _active_stages():
    return list(
        CrmLeadKanbanStage.objects.filter(is_active=True, converts_to_customer=False).order_by(
            'sort_order', 'id'
        )
    )


def _stage_distribution(leads_qs) -> list[tuple[str, int, Q]]:
    """Current exclusive stage counts for active leads (non-zero only)."""
    rows: list[tuple[str, int, Q]] = []
    unassigned = leads_qs.filter(lead_kanban_stage__isnull=True).count()
    if unassigned:
        rows.append(('Unassigned', unassigned, Q(lead_kanban_stage__isnull=True)))
    for stage in _active_stages():
        count = leads_qs.filter(lead_kanban_stage_id=stage.pk).count()
        if count:
            rows.append((stage.name, count, Q(lead_kanban_stage_id=stage.pk)))
    return rows


def _funnel_rows(
    user,
    leads_qs,
    total_leads: int,
    *,
    date_from: date | None,
    date_to: date | None,
) -> list[dict]:
    """Pipeline funnel: total leads, current stage breakdown, then won conversions."""
    rows = []
    won = _won_deals_count(user, date_from, date_to)
    lead_base = max(total_leads, 1)
    deal_base = max(total_leads + won, 1)

    rows.append(
        {
            'label': 'Leads',
            'count': total_leads,
            'pct': 100.0 if total_leads else 0.0,
            'value': _pipeline_value(_open_leads_qs(leads_qs)),
        }
    )

    for label, count, stage_q in _stage_distribution(leads_qs):
        stage_qs = leads_qs.filter(stage_q)
        rows.append(
            {
                'label': label,
                'count': count,
                'pct': round(count / lead_base * 100, 1) if total_leads else 0.0,
                'value': _pipeline_value(stage_qs),
            }
        )

    if won:
        rows.append(
            {
                'label': 'Won',
                'count': won,
                'pct': round(won / deal_base * 100, 2),
                'value': _won_deals_value(user, date_from, date_to),
            }
        )
    return rows


def _stage_donut(
    user,
    leads_qs,
    total_leads: int,
    *,
    date_from: date | None,
    date_to: date | None,
) -> list[dict]:
    slices = []
    for label, count, _stage_q in _stage_distribution(leads_qs):
        slices.append({'label': label, 'count': count})

    won = _won_deals_count(user, date_from, date_to)
    if won:
        slices.append({'label': 'Won', 'count': won})

    total = sum(s['count'] for s in slices)
    if not total:
        return []

    for item in slices:
        item['pct'] = round(item['count'] / total * 100, 1)
    return slices


def _source_donut(leads_qs) -> list[dict]:
    if not leads_qs.exists():
        return []

    counter = Counter()
    for lead in leads_qs.iterator(chunk_size=500):
        counter[infer_lead_source(lead)] += 1
    total = sum(counter.values()) or 1
    order = ['Website', 'Referral', 'Social Media', 'Email Campaign', 'Other']
    slices = []
    for lbl in order:
        count = counter.get(lbl, 0)
        if count:
            slices.append(
                {
                    'label': lbl,
                    'count': count,
                    'pct': round(count / total * 100, 1),
                }
            )
    return slices


def build_lead_dashboard_context(
    *,
    user,
    date_from: date | None,
    date_to: date | None,
    all_time: bool = False,
) -> dict:
    base = base_leads_queryset(user)
    period_leads = _filter_leads_by_created(base, date_from, date_to)

    if all_time:
        cmp_cur_start, cmp_cur_end, cmp_prev_start, cmp_prev_end = _comparison_period()
        prev_leads = _filter_leads_by_created(base, cmp_prev_start, cmp_prev_end)
        delta_leads = _filter_leads_by_created(base, cmp_cur_start, cmp_cur_end)
        prev_from, prev_to = cmp_prev_start, cmp_prev_end
        won_from, won_to = None, None
    else:
        prev_from, prev_to = previous_period(date_from, date_to)
        prev_leads = _filter_leads_by_created(base, prev_from, prev_to)
        delta_leads = period_leads
        won_from, won_to = date_from, date_to

    current = _kpi_snapshot(user, period_leads, date_from=won_from, date_to=won_to)
    if all_time:
        delta = _kpi_snapshot(user, delta_leads, date_from=cmp_cur_start, date_to=cmp_cur_end)
        previous = _kpi_snapshot(user, prev_leads, date_from=cmp_prev_start, date_to=cmp_prev_end)
    else:
        delta = current
        previous = _kpi_snapshot(user, prev_leads, date_from=prev_from, date_to=prev_to)

    kpi_defs = (
        ('total_leads', 'Total Leads', 'int'),
        ('open_deals', 'Open Deals', 'int'),
        ('pipeline_value', 'Pipeline Value', 'money'),
        ('won_deals', 'Won Deals', 'int'),
        ('conversion_rate', 'Conversion Rate', 'pct'),
    )
    kpis = []
    for key, label, fmt in kpi_defs:
        meta = _delta_meta(
            float(delta.get(key, 0) if all_time else current.get(key, 0)),
            float(previous.get(key, 0)),
        )
        meta['key'] = key
        meta['label'] = label
        meta['format'] = fmt
        meta['current'] = float(current.get(key, 0))
        kpis.append(meta)

    total_leads = current['total_leads']
    funnel = _funnel_rows(user, period_leads, total_leads, date_from=won_from, date_to=won_to)
    stage_donut = _stage_donut(user, period_leads, total_leads, date_from=won_from, date_to=won_to)
    source_donut = _source_donut(period_leads)
    trend_labels, trend_values = _sales_trend(period_leads, user, date_from, date_to)

    stage_total = sum(s['count'] for s in stage_donut)

    if all_time:
        period_label = 'All leads (same as Leads list)'
        prev_label = 'Previous 30 days'
        month_label = 'All time'
    else:
        period_label = f'{date_from.strftime("%b %d")} – {date_to.strftime("%b %d, %Y")}'
        prev_label = f'{prev_from.strftime("%b %d")} – {prev_to.strftime("%b %d, %Y")}'
        month_label = date_to.strftime('%B %Y') if date_to else timezone.localdate().strftime('%B %Y')

    return {
        'date_from': date_from,
        'date_to': date_to,
        'date_from_iso': date_from.isoformat() if date_from else '',
        'date_to_iso': date_to.isoformat() if date_to else '',
        'all_time': all_time,
        'period_label': period_label,
        'prev_period_label': prev_label,
        'month_label': month_label,
        'total_visible_leads': total_leads,
        'pipeline_value_total': current['pipeline_value'],
        'kpis': kpis,
        'funnel': funnel,
        'trend_labels': trend_labels,
        'charts': {
            'stage_donut': stage_donut,
            'stage_total': stage_total,
            'source_donut': source_donut,
            'source_total': sum(s['count'] for s in source_donut),
            'sales_trend': trend_values,
            'sales_trend_peak': max(trend_values) if trend_values else 0,
        },
    }
