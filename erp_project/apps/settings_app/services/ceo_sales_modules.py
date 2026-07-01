"""CEO sales module cards — same metrics as Sales/CRM dashboards (read-only)."""
from __future__ import annotations

from collections import Counter
from datetime import date
from urllib.parse import urlencode

from django.db.models import Count, Sum
from django.urls import reverse

from apps.crm.lead_dashboard import (
    _delta_meta as lead_delta_meta,
    _filter_leads_by_created,
    _kpi_snapshot,
    _stage_donut,
    base_leads_queryset,
    infer_lead_source,
    previous_period as lead_previous_period,
)
from apps.sales.estimate_dashboard import (
    DASHBOARD_MODES,
    _delta_meta,
    _filter_by_created_date,
    _filter_by_estimate_date,
    _kpi_block,
    _status_bucket,
    base_estimates_queryset,
    previous_period,
)
from apps.sales.models import EstimateRevisionSnapshot

from .ceo_executive_reports import (
    CeoFilters,
    _apply_client_type,
    _apply_salesperson_filter,
    _apply_salesperson_to_estimates,
    _apply_service_line_to_estimates,
    _money,
    _quote_48h_stats,
    _site_visit_stats,
)
from .ceo_module_reports import _flag_meta, _health_flag, _module_shell, _status_chip

# Primary KPIs shown on CEO cards (full set lives on each module dashboard).
LEAD_KPI_KEYS = (
    'total_leads',
    'open_deals',
    'pipeline_value',
    'won_deals',
    'conversion_rate',
)
ESTIMATE_KPI_KEYS = (
    'total_estimations',
    'estimation_value',
    'approved_estimations',
    'pending_estimations',
    'rejected_estimations',
    'conversion_rate',
)
QUOTATION_KPI_KEYS = (
    'total_estimations',
    'estimation_value',
    'approved_estimations',
    'pending_estimations',
    'lost_estimations',
    'won_value',
)
SALES_ORDER_KPI_KEYS = (
    'approved_estimations',
    'won_value',
    'total_estimations',
    'conversion_rate',
)

STATUS_CHIP_TONES = {
    'approved': 'success',
    'won': 'success',
    'rejected': 'danger',
    'lost': 'danger',
    'pending': 'warning',
    'negotiation': 'warning',
}


def _dashboard_url(url_name: str, filters: CeoFilters) -> str:
    qs = urlencode({
        'date_from': filters.date_from.isoformat(),
        'date_to': filters.date_to.isoformat(),
    })
    return f'{reverse(url_name)}?{qs}'


def _period_label(date_from: date, date_to: date) -> str:
    return f'{date_from.strftime("%b %d")} – {date_to.strftime("%b %d, %Y")}'


def _ceo_leads_base(user, filters: CeoFilters):
    qs = base_leads_queryset(user)
    sp_ids = _apply_salesperson_filter(filters.salesperson_id, filters.department)
    if sp_ids is not None:
        qs = qs.filter(assigned_salesperson_id__in=sp_ids)
    return _apply_client_type(qs, filters.client_type, lead_mode=True)


def _ceo_estimate_base(user, filters: CeoFilters, *, mode: str):
    qs = base_estimates_queryset(user, mode=mode)
    qs = _apply_service_line_to_estimates(qs, filters.service_line)
    return _apply_salesperson_to_estimates(qs, filters.salesperson_id)


def _build_kpi_cards(
    mode_cfg: dict,
    current_kpi: dict,
    previous_kpi: dict,
    *,
    keys: tuple[str, ...],
) -> list[dict]:
    label_by_key = {key: label for key, label, _fmt in mode_cfg['kpis']}
    fmt_by_key = {key: fmt for key, label, fmt in mode_cfg['kpis']}
    cards = []
    for key in keys:
        meta = _delta_meta(float(current_kpi.get(key, 0)), float(previous_kpi.get(key, 0)))
        meta['key'] = key
        meta['label'] = label_by_key.get(key, key.replace('_', ' ').title())
        meta['format'] = fmt_by_key.get(key, 'int')
        meta['current'] = float(current_kpi.get(key, 0))
        cards.append(meta)
    return cards


def _status_chips_from_donut(status_donut: list[dict]) -> list[dict]:
    chips = []
    for row in status_donut:
        key = row.get('key', row['label'].lower().replace(' ', '_'))
        tone = STATUS_CHIP_TONES.get(key, 'info')
        chips.append(_status_chip(row['label'], row['count'], tone))
    return chips


def _estimate_status_donut(period_qs, mode: str) -> list[dict]:
    mode_cfg = DASHBOARD_MODES[mode]
    status_counts = Counter()
    for row in period_qs.values('status').annotate(c=Count('id')):
        status_counts[_status_bucket(row['status'], mode=mode)] += row['c']
    return [
        {'key': key, 'label': lbl, 'count': status_counts.get(key, 0)}
        for key, lbl in mode_cfg['status_donut']
    ]


def _build_estimate_module(
    user,
    filters: CeoFilters,
    *,
    mode: str,
    key: str,
    title: str,
    icon: str,
    url_name: str,
    dashboard_url_name: str,
    kpi_keys: tuple[str, ...],
    extra_qs_filter=None,
    build_rows,
    build_watch,
    build_flag,
    build_headline,
) -> dict:
    base = _ceo_estimate_base(user, filters, mode=mode)
    if extra_qs_filter is not None:
        base = extra_qs_filter(base)

    date_from, date_to = filters.date_from, filters.date_to
    period_estimates = _filter_by_estimate_date(base, date_from, date_to)
    prev_from, prev_to = previous_period(date_from, date_to)
    prev_estimates = _filter_by_estimate_date(base, prev_from, prev_to)

    request_qs = _filter_by_created_date(base, date_from, date_to)
    prev_requests = _filter_by_created_date(base, prev_from, prev_to)

    revised_qs = EstimateRevisionSnapshot.objects.filter(
        estimate__in=period_estimates,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    prev_revised = EstimateRevisionSnapshot.objects.filter(
        estimate__in=prev_estimates,
        created_at__date__gte=prev_from,
        created_at__date__lte=prev_to,
    )

    current_kpi = _kpi_block(period_estimates, request_qs, revised_qs, date_from, date_to, mode=mode)
    previous_kpi = _kpi_block(prev_estimates, prev_requests, prev_revised, prev_from, prev_to, mode=mode)

    mode_cfg = DASHBOARD_MODES[mode]
    kpis = _build_kpi_cards(mode_cfg, current_kpi, previous_kpi, keys=kpi_keys)
    status_donut = _estimate_status_donut(period_estimates, mode)
    status_counts = _status_chips_from_donut(status_donut)

    rows = build_rows(period_estimates)
    watch = build_watch(period_estimates, current_kpi)
    flag = build_flag(period_estimates, current_kpi)
    headline = build_headline(current_kpi, period_estimates)

    return _module_shell(
        key=key,
        title=title,
        icon=icon,
        url_name=url_name,
        flag=flag,
        headline=headline,
        watch=watch,
        status_counts=status_counts,
        metrics=[],
        columns=[],
        rows=rows,
        kpis=kpis,
        dashboard_url=_dashboard_url(dashboard_url_name, filters),
        period_label=_period_label(date_from, date_to),
        total_in_scope=period_estimates.count(),
        prev_period_label=_period_label(prev_from, prev_to),
    )


def build_leads_module(user, filters: CeoFilters) -> dict:
    base = _ceo_leads_base(user, filters)
    date_from, date_to = filters.date_from, filters.date_to
    period_leads = _filter_leads_by_created(base, date_from, date_to)
    prev_from, prev_to = lead_previous_period(date_from, date_to)
    prev_leads = _filter_leads_by_created(base, prev_from, prev_to)

    current = _kpi_snapshot(user, period_leads, date_from=date_from, date_to=date_to)
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
        if key not in LEAD_KPI_KEYS:
            continue
        meta = lead_delta_meta(float(current.get(key, 0)), float(previous.get(key, 0)))
        meta['key'] = key
        meta['label'] = label
        meta['format'] = fmt
        meta['current'] = float(current.get(key, 0))
        kpis.append(meta)

    stage_donut = _stage_donut(user, period_leads, current['total_leads'], date_from=date_from, date_to=date_to)
    status_counts = [
        _status_chip(row['label'], row['count'], 'info' if row['label'] == 'Unassigned' else 'primary')
        for row in stage_donut[:6]
    ]

    unassigned = period_leads.filter(assigned_salesperson__isnull=True).count()
    lost = period_leads.filter(lead_kanban_stage__slug='lost').count()

    from apps.crm.models import CrmLeadKanbanStage
    site_stage = CrmLeadKanbanStage.objects.filter(is_active=True, is_site_visit=True).first()
    scheduled, completed = _site_visit_stats(filters, site_stage)

    rows = []
    for lead in period_leads.select_related('assigned_salesperson', 'lead_kanban_stage').order_by('-created_at')[:10]:
        rows.append({
            'cells': [
                lead.display_name[:24],
                lead.lead_kanban_stage.name if lead.lead_kanban_stage_id else 'Unassigned',
                infer_lead_source(lead),
                str(lead.assigned_salesperson) if lead.assigned_salesperson_id else '—',
                lead.created_at.strftime('%d/%m/%Y'),
            ],
        })

    flag = _health_flag(red=unassigned >= 5 and current['total_leads'] > 0, yellow=unassigned >= 2 or lost >= 3)
    watch = []
    if unassigned:
        watch.append(f'{unassigned} lead(s) without assigned salesperson')
    if lost:
        watch.append(f'{lost} lead(s) marked lost in period')
    if scheduled:
        watch.append(f'{scheduled} site visit(s) scheduled · {completed} completed')
    if not watch:
        watch.append('Lead pipeline flowing normally')

    return _module_shell(
        key='leads',
        title='CRM leads',
        icon='fa-funnel-dollar',
        url_name='crm:lead_list',
        flag=flag,
        headline=(
            f'{int(current["total_leads"])} leads · {int(current["open_deals"])} open · '
            f'AED {current["pipeline_value"]:,.0f} pipeline'
        ),
        watch=watch,
        status_counts=status_counts,
        metrics=[],
        columns=['Lead', 'Stage', 'Source', 'Owner', 'Created'],
        rows=rows,
        kpis=kpis,
        dashboard_url=_dashboard_url('crm:lead_dashboard', filters),
        period_label=_period_label(date_from, date_to),
        total_in_scope=int(current['total_leads']),
        prev_period_label=_period_label(prev_from, prev_to),
    )


def build_estimates_module(user, filters: CeoFilters) -> dict:
    def build_rows(period_qs):
        rows = []
        for e in period_qs.select_related('customer', 'sales_engineer').order_by('-date')[:10]:
            status_label = e.get_status_display()
            if e.edit_approval_status == 'pending':
                status_label = f'{status_label} · edit pending'
            elif e.edit_approval_status == 'rejected':
                status_label = f'{status_label} · edit rejected'
            rows.append({
                'cells': [
                    e.display_estimate_number,
                    (e.customer.display_name if e.customer_id else '—')[:20],
                    status_label,
                    f'{float(e.total_amount):,.0f}',
                    str(e.sales_engineer) if e.sales_engineer_id else '—',
                ],
            })
        return rows

    def build_watch(period_qs, kpi):
        pending_edit = period_qs.filter(edit_approval_status='pending').count()
        edit_rejected = period_qs.filter(edit_approval_status='rejected').count()
        watch = []
        pending = int(kpi.get('pending_estimations', 0))
        rejected = int(kpi.get('rejected_estimations', 0))
        if pending:
            watch.append(f'{pending} pending estimate(s) (draft / sent / negotiation)')
        if pending_edit:
            watch.append(f'{pending_edit} estimate edit(s) pending approval')
        if rejected:
            watch.append(f'{rejected} rejected estimate(s)')
        if edit_rejected:
            watch.append(f'{edit_rejected} estimate edit(s) rejected')
        if not watch:
            watch.append('Estimation pipeline healthy')
        return watch

    def build_flag(period_qs, kpi):
        rejected = int(kpi.get('rejected_estimations', 0))
        pending = int(kpi.get('pending_estimations', 0))
        edit_rejected = period_qs.filter(edit_approval_status='rejected').count()
        pending_edit = period_qs.filter(edit_approval_status='pending').count()
        return _health_flag(
            red=rejected >= 3 or edit_rejected >= 2,
            yellow=pending >= 5 or pending_edit > 0,
        )

    def build_headline(kpi, period_qs):
        total = int(kpi.get('total_estimations', 0))
        value = float(kpi.get('estimation_value', 0))
        return f'{total} estimates · AED {value:,.0f} · {int(kpi.get("approved_estimations", 0))} approved'

    mod = _build_estimate_module(
        user,
        filters,
        mode='estimate',
        key='estimates',
        title='Estimates',
        icon='fa-calculator',
        url_name='sales:estimate_list',
        dashboard_url_name='sales:estimate_dashboard',
        kpi_keys=ESTIMATE_KPI_KEYS,
        build_rows=build_rows,
        build_watch=build_watch,
        build_flag=build_flag,
        build_headline=build_headline,
    )
    mod['columns'] = ['Estimate', 'Client', 'Status', 'Value', 'Sales engineer']
    return mod


def build_quotations_module(user, filters: CeoFilters) -> dict:
    today = filters.date_to

    def build_rows(period_qs):
        open_q = period_qs.filter(status='under_negotiation')
        rows = []
        for e in open_q.select_related('customer', 'sales_engineer').order_by('-total_amount')[:10]:
            blocker = (e.rejection_reason or e.notes or '—')[:30]
            rows.append({
                'cells': [
                    e.display_estimate_number,
                    (e.customer.display_name if e.customer_id else '—')[:20],
                    f'{float(e.total_amount):,.0f}',
                    e.valid_until.strftime('%d/%m/%Y') if e.valid_until else '—',
                    blocker,
                ],
            })
        return rows

    def build_watch(period_qs, kpi):
        open_q = period_qs.filter(status='under_negotiation')
        overdue = open_q.filter(valid_until__lt=today).count()
        open_val = float(_money(open_q.aggregate(t=Sum('total_amount'))['t']))
        won = int(kpi.get('approved_estimations', 0))
        lost = int(kpi.get('lost_estimations', 0))
        win_rate = round(won / (won + lost) * 100, 1) if (won + lost) else 0
        quote_48_pct, _, _ = _quote_48h_stats(
            _ceo_estimate_base(user, filters, mode='quotation').filter(
                date__gte=filters.date_from,
                date__lte=filters.date_to,
            )
        )
        watch = []
        if overdue:
            watch.append(f'{overdue} quotation(s) past valid-until date')
        if open_val:
            watch.append(f'AED {open_val:,.0f} in open quotation pipeline')
        watch.append(f'Win rate {win_rate}% · quotes ≤48h {quote_48_pct}%')
        if lost > won:
            watch.append(f'More lost ({lost}) than won ({won}) in period')
        return watch[:4]

    def build_flag(period_qs, kpi):
        open_q = period_qs.filter(status='under_negotiation')
        overdue = open_q.filter(valid_until__lt=today).count()
        won = int(kpi.get('approved_estimations', 0))
        lost = int(kpi.get('lost_estimations', 0))
        return _health_flag(red=overdue >= 3, yellow=overdue >= 1 or lost > won)

    def build_headline(kpi, period_qs):
        open_count = int(kpi.get('pending_estimations', 0))
        won = int(kpi.get('approved_estimations', 0))
        lost = int(kpi.get('lost_estimations', 0))
        return f'{open_count} open · {won} won · {lost} lost'

    mod = _build_estimate_module(
        user,
        filters,
        mode='quotation',
        key='quotations',
        title='Quotations',
        icon='fa-file-invoice',
        url_name='sales:quotation_list',
        dashboard_url_name='sales:quotation_dashboard',
        kpi_keys=QUOTATION_KPI_KEYS,
        build_rows=build_rows,
        build_watch=build_watch,
        build_flag=build_flag,
        build_headline=build_headline,
    )
    mod['columns'] = ['Quotation', 'Client', 'Value', 'Valid until', 'Notes']
    return mod


def build_sales_orders_module(user, filters: CeoFilters) -> dict:
    def extra_filter(qs):
        return qs.filter(status='quotation_won')

    def build_rows(period_qs):
        rows = []
        for e in period_qs.select_related('customer', 'sales_engineer').order_by('-date')[:10]:
            rows.append({
                'cells': [
                    e.sales_order_number or e.display_estimate_number,
                    (e.customer.display_name if e.customer_id else '—')[:20],
                    e.date.strftime('%d/%m/%Y'),
                    f'{float(e.total_amount):,.0f}',
                    str(e.sales_engineer) if e.sales_engineer_id else '—',
                ],
            })
        return rows

    def build_watch(period_qs, kpi):
        count = period_qs.count()
        value = float(kpi.get('won_value', 0))
        with_so = period_qs.exclude(sales_order_number='').exclude(sales_order_number__isnull=True).count()
        watch = []
        if count == 0:
            watch.append('No confirmed orders in selected period')
        else:
            watch.append(f'{count} order(s) · AED {value:,.0f} revenue booked')
        if with_so < count:
            watch.append(f'{count - with_so} order(s) missing sales order number')
        if not watch:
            watch.append('Order book healthy')
        return watch

    def build_flag(period_qs, kpi):
        count = period_qs.count()
        return _health_flag(red=count == 0, yellow=count < 3)

    def build_headline(kpi, period_qs):
        count = int(kpi.get('approved_estimations', 0))
        value = float(kpi.get('won_value', 0))
        return f'{count} orders · AED {value:,.0f} confirmed'

    mod = _build_estimate_module(
        user,
        filters,
        mode='quotation',
        key='sales_orders',
        title='Sales orders',
        icon='fa-shopping-bag',
        url_name='sales:sales_order_list',
        dashboard_url_name='sales:quotation_dashboard',
        kpi_keys=SALES_ORDER_KPI_KEYS,
        extra_qs_filter=extra_filter,
        build_rows=build_rows,
        build_watch=build_watch,
        build_flag=build_flag,
        build_headline=build_headline,
    )
    count = mod.get('total_in_scope', 0)
    with_so = (
        _ceo_estimate_base(user, filters, mode='quotation')
        .filter(status='quotation_won', date__gte=filters.date_from, date__lte=filters.date_to)
        .exclude(sales_order_number='')
        .exclude(sales_order_number__isnull=True)
        .count()
    )
    mod['status_counts'] = [
        _status_chip('Orders', count, 'success'),
        _status_chip('With SO #', with_so, 'info'),
    ]
    mod['columns'] = ['SO / Estimate', 'Client', 'Date', 'Value', 'Sales engineer']
    mod['flag_display'] = _flag_meta(mod['flag'], 'sales_orders')
    return mod


def build_ceo_sales_modules(user, filters: CeoFilters) -> list[dict]:
    return [
        build_leads_module(user, filters),
        build_estimates_module(user, filters),
        build_quotations_module(user, filters),
        build_sales_orders_module(user, filters),
    ]
