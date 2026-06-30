"""Live ERP metrics for the CEO dashboard — decision-focused only."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

from apps.crm.models import Customer
from apps.finance.models import Account, AccountType, BankAccount, Budget, BudgetLine
from apps.hr.models import Payroll
from apps.purchase.models import VendorBill
from apps.sales.models import Estimate, Invoice

INVOICE_OPEN_STATUSES = ('posted', 'sent', 'paid', 'partial', 'overdue')
INVOICE_REVENUE_STATUSES = INVOICE_OPEN_STATUSES
BILL_OPEN_STATUSES = ('posted', 'paid', 'partial', 'overdue', 'pending')
PAYROLL_PAID_STATUSES = ('processed', 'paid')
ZERO = Decimal('0.00')
SNAPSHOT_PREFIX = 'ceo:snap:'
SNAPSHOT_TTL = 86400 * 40

MONTH_FIELDS = (
    'jan', 'feb', 'mar', 'apr', 'may', 'jun',
    'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
)


def _today() -> date:
    return timezone.localdate()


def _money(val) -> Decimal:
    if val is None:
        return ZERO
    return Decimal(str(val)).quantize(Decimal('0.01'))


def _pct_change(current: Decimal, previous: Decimal) -> int | None:
    if not previous:
        return None
    return int(((current - previous) / previous * Decimal('100')).quantize(Decimal('1')))


def _vs_last_month(current: float, previous: float | None, *, bad_when_up: bool = False) -> dict:
    if previous is None:
        return {'pct': None, 'direction': 'neutral', 'label': 'vs last month'}
    pct = _pct_change(Decimal(str(current)), Decimal(str(previous)))
    if pct is None:
        return {'pct': None, 'direction': 'neutral', 'label': 'vs last month'}
    raw_up = pct > 0
    if bad_when_up:
        direction = 'down' if raw_up else ('up' if pct < 0 else 'neutral')
    else:
        direction = 'up' if raw_up else ('down' if pct < 0 else 'neutral')
    return {'pct': pct, 'direction': direction, 'label': 'vs last month'}


def _customer_label(customer_id: int | None, name: str | None) -> str:
    label = (name or '').strip()
    if label:
        return label
    if customer_id:
        return f'Client #{customer_id}'
    return 'Unassigned'


def _invoice_balance_qs():
    return Invoice.objects.filter(is_active=True, status__in=INVOICE_OPEN_STATUSES).annotate(
        outstanding=ExpressionWrapper(
            F('total_amount') - F('paid_amount'),
            output_field=DecimalField(max_digits=15, decimal_places=2),
        ),
    ).filter(outstanding__gt=ZERO)


def _revenue_between(start: date, end: date) -> Decimal:
    total = (
        Invoice.objects.filter(
            is_active=True,
            invoice_date__gte=start,
            invoice_date__lte=end,
            status__in=INVOICE_REVENUE_STATUSES,
        ).aggregate(t=Sum('total_amount'))['t']
        or ZERO
    )
    return _money(total)


def _mtd_revenue(today: date) -> Decimal:
    return _revenue_between(today.replace(day=1), today)


def _month_revenue(year: int, month: int) -> Decimal:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return _revenue_between(start, end)


def _month_expense(year: int, month: int) -> Decimal:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    bills = (
        VendorBill.objects.filter(
            is_active=True,
            bill_date__gte=start,
            bill_date__lte=end,
            status__in=BILL_OPEN_STATUSES,
        ).aggregate(t=Sum('total_amount'))['t']
        or ZERO
    )
    return _money(bills)


def _month_payroll(year: int, month: int) -> Decimal:
    start = date(year, month, 1)
    total = (
        Payroll.objects.filter(
            is_active=True,
            month=start,
            status__in=PAYROLL_PAID_STATUSES,
        ).aggregate(t=Sum('net_salary'))['t']
        or ZERO
    )
    return _money(total)


def _revenue_target_month(year: int, month: int) -> Decimal:
    """Single approved budget for the fiscal year; monthly column or amount/12."""
    month_start = date(year, month, 1)
    field = MONTH_FIELDS[month - 1]
    budget = (
        Budget.objects.filter(
            is_active=True,
            status__in=('approved', 'locked'),
            fiscal_year__start_date__lte=month_start,
            fiscal_year__end_date__gte=month_start,
        )
        .order_by('-approved_date', '-id')
        .first()
    )
    target = ZERO
    if budget:
        lines = budget.lines.filter(
            Q(account__account_category='operating_revenue')
            | Q(account__account_type=AccountType.INCOME),
        )
        for line in lines:
            monthly = _money(getattr(line, field, ZERO))
            if monthly <= ZERO and line.amount > ZERO:
                monthly = _money(line.amount / Decimal('12'))
            target += monthly
    if target > ZERO:
        return target

    samples = []
    y, m = year, month
    for _ in range(3):
        m -= 1
        if m <= 0:
            m = 12
            y -= 1
        samples.append(_month_revenue(y, m))
    if samples:
        return _money(sum(samples, ZERO) / len(samples))
    return ZERO


def _revenue_target_mtd(year: int, month: int, today: date) -> Decimal:
    """Prorate full-month target to MTD for fair comparison."""
    full = _revenue_target_month(year, month)
    if not full:
        return ZERO
    days_in_month = monthrange(year, month)[1]
    return _money(full * Decimal(today.day) / Decimal(days_in_month))


def _revenue_vs_target(actual_mtd: Decimal, target_mtd: Decimal) -> dict:
    actual_f = float(actual_mtd)
    target_f = float(target_mtd)
    full_target = float(_revenue_target_month(_today().year, _today().month))
    if not target_mtd:
        return {
            'pct': None,
            'pct_raw': None,
            'bar_pct': 0,
            'over_target': False,
            'actual': actual_f,
            'target_mtd': target_f,
            'target_month': full_target,
        }
    pct_raw = int(actual_mtd / target_mtd * 100)
    return {
        'pct': pct_raw,
        'pct_raw': pct_raw,
        'bar_pct': min(pct_raw, 100),
        'over_target': pct_raw > 100,
        'actual': actual_f,
        'target_mtd': target_f,
        'target_month': full_target,
    }


def _cash_position() -> Decimal:
    total = (
        BankAccount.objects.filter(is_active=True).aggregate(t=Sum('current_balance'))['t']
        or ZERO
    )
    if total > ZERO:
        return _money(total)
    gl = (
        Account.objects.filter(is_active=True, is_cash_account=True).aggregate(t=Sum('balance'))['t']
        or ZERO
    )
    return _money(gl)


def _average_monthly_burn() -> Decimal:
    today = _today()
    y, m = today.year, today.month
    samples = []
    for _ in range(3):
        bills = _month_expense(y, m)
        payroll = _month_payroll(y, m)
        total = bills + payroll
        if total > ZERO:
            samples.append(total)
        m -= 1
        if m <= 0:
            m = 12
            y -= 1
    if not samples:
        return ZERO
    return _money(sum(samples, ZERO) / len(samples))


def _cash_runway(cash: Decimal, burn: Decimal) -> dict:
    if burn <= ZERO:
        return {'weeks': None, 'months': None, 'burn': float(burn), 'critical': False}
    months = float(cash / burn)
    weeks = round(months * 4.33, 1)
    return {
        'weeks': weeks,
        'months': round(months, 1),
        'burn': float(burn),
        'critical': weeks < 4,
    }


def _receivables_snapshot(today: date) -> dict:
    qs = _invoice_balance_qs().select_related('customer')
    total = _money(qs.aggregate(t=Sum('outstanding'))['t'])
    overdue = _money(
        qs.filter(due_date__lt=today).aggregate(t=Sum('outstanding'))['t'],
    )
    return {'total': float(total), 'overdue': float(overdue), 'count': qs.count()}


def _dso(outstanding: Decimal, today: date, *, period_days: int = 90) -> float | None:
    start = today - timedelta(days=period_days)
    revenue = _revenue_between(start, today)
    if not revenue:
        return None
    return round(float(outstanding / revenue * period_days), 1)


def _payables_due_week(today: date) -> dict:
    week_end = today + timedelta(days=7)
    qs = (
        VendorBill.objects.filter(
            is_active=True,
            status__in=BILL_OPEN_STATUSES,
            due_date__gte=today,
            due_date__lte=week_end,
        )
        .annotate(
            outstanding=ExpressionWrapper(
                F('total_amount') - F('paid_amount'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        .filter(outstanding__gt=ZERO)
    )
    total = _money(qs.aggregate(t=Sum('outstanding'))['t'])
    return {'total': float(total), 'count': qs.count()}


def _profit_for_month(year: int, month: int) -> dict:
    rev = _month_revenue(year, month)
    exp = _month_expense(year, month)
    profit = rev - exp
    margin = float(profit / rev * 100) if rev else 0.0
    return {'revenue': rev, 'expense': exp, 'profit': profit, 'margin_pct': round(margin, 1)}


def _client_concentration(today: date) -> dict | None:
    rows = (
        _invoice_balance_qs()
        .values('customer_id')
        .annotate(total=Sum('outstanding'))
        .order_by('-total')[:5]
    )
    rows = list(rows)
    if not rows:
        return None
    grand = sum(_money(r['total']) for r in rows)
    if not grand:
        return None
    top = rows[0]
    customer_ids = [r['customer_id'] for r in rows if r['customer_id']]
    names = {
        c.pk: c.name
        for c in Customer.objects.filter(pk__in=customer_ids).only('pk', 'name')
    }
    top_name = _customer_label(top['customer_id'], names.get(top['customer_id']))
    pct = int(_money(top['total']) / grand * 100)
    return {
        'name': top_name,
        'customer_id': top['customer_id'],
        'pct': pct,
        'warn': pct >= 25,
        'amount': float(_money(top['total'])),
    }


def _customer_slowness_factor(customer_id: int | None) -> float:
    if not customer_id:
        return 1.0
    paid = Invoice.objects.filter(
        is_active=True,
        customer_id=customer_id,
        status__in=('paid', 'partial'),
        paid_amount__gt=ZERO,
    ).only('due_date', 'invoice_date', 'paid_amount', 'total_amount')[:20]
    delays = []
    for inv in paid:
        ref = inv.due_date or inv.invoice_date
        if not ref:
            continue
        if inv.paid_amount >= inv.total_amount:
            delays.append(max(0, 30))
        else:
            delays.append(max(0, (_today() - ref).days))
    if not delays:
        return 1.0
    avg = sum(delays) / len(delays)
    return min(3.0, 1.0 + avg / 30.0)


def build_collection_candidates(limit: int = 5) -> list[dict]:
    """Rank overdue clients for collections (deterministic score)."""
    today = _today()
    qs = (
        _invoice_balance_qs()
        .filter(due_date__lt=today)
        .select_related('customer')
        .order_by('-outstanding')
    )
    by_customer: dict[int | None, dict] = {}
    for inv in qs:
        cid = inv.customer_id
        days = (today - inv.due_date).days if inv.due_date else 0
        bal = float(_money(inv.outstanding))
        if cid not in by_customer:
            by_customer[cid] = {
                'customer_id': cid,
                'name': _customer_label(cid, inv.customer.name if inv.customer_id else None),
                'amount': 0.0,
                'max_days_overdue': 0,
            }
        row = by_customer[cid]
        row['amount'] += bal
        row['max_days_overdue'] = max(row['max_days_overdue'], days)

    ranked = []
    for row in by_customer.values():
        slowness = _customer_slowness_factor(row['customer_id'])
        score = row['amount'] * max(1, row['max_days_overdue']) * slowness
        ranked.append({**row, 'score': score, 'slowness': round(slowness, 2)})

    ranked.sort(key=lambda r: r['score'], reverse=True)
    return ranked[:limit]


def _persist_snapshot(today: date, snap: dict) -> None:
    cache.set(f'{SNAPSHOT_PREFIX}{today.isoformat()}', snap, SNAPSHOT_TTL)


def _load_snapshot(on_date: date) -> dict | None:
    return cache.get(f'{SNAPSHOT_PREFIX}{on_date.isoformat()}')


def build_yesterday_deltas(current: dict) -> list[dict]:
    """Deltas vs yesterday's cached snapshot for CEO daily check."""
    today = _today()
    yesterday = today - timedelta(days=1)
    prev = _load_snapshot(yesterday)
    if not prev:
        return []

    deltas: list[dict] = []

    def _delta(label, cur, old, fmt='money', bad_up=False):
        if old is None:
            return
        change = cur - old
        if abs(change) < 0.01:
            return
        direction = 'up' if change > 0 else 'down'
        severity = 'high' if bad_up and change > 0 else ('medium' if abs(change) > 0 else 'low')
        if fmt == 'money':
            detail = f"AED {old:,.0f} → AED {cur:,.0f} ({change:+,.0f})"
        elif fmt == 'pct':
            detail = f"{old:.1f}% → {cur:.1f}% ({change:+.1f} pp)"
        else:
            detail = f"{old} → {cur} ({change:+})"
        deltas.append({
            'label': label,
            'detail': detail,
            'direction': direction,
            'severity': severity,
            'action': 'Review in dashboard' if not bad_up else 'Act today',
        })

    _delta('Cash', current['cash_position'], prev.get('cash_position'), bad_up=False)
    _delta('Receivables', current['receivables']['total'], prev.get('receivables', {}).get('total'), bad_up=True)
    _delta('Overdue AR', current['receivables']['overdue'], prev.get('receivables', {}).get('overdue'), bad_up=True)
    _delta('Pipeline', current['pipeline']['pipeline_total'], prev.get('pipeline', {}).get('pipeline_total'))

    cur_overdue_cnt = current.get('overdue_invoice_count', 0)
    prev_overdue_cnt = prev.get('overdue_invoice_count', 0)
    if cur_overdue_cnt > prev_overdue_cnt:
        deltas.append({
            'label': 'New overdue invoices',
            'detail': f"{prev_overdue_cnt} → {cur_overdue_cnt} overdue invoice(s)",
            'direction': 'up',
            'severity': 'high',
            'action': 'Start collections on newly overdue accounts.',
        })

    proj = current.get('projects') or {}
    prev_proj = prev.get('projects') or {}
    if proj.get('delayed_count', 0) > prev_proj.get('delayed_count', 0):
        deltas.append({
            'label': 'More delayed projects',
            'detail': f"{prev_proj.get('delayed_count', 0)} → {proj.get('delayed_count', 0)} delayed",
            'direction': 'up',
            'severity': 'high',
            'action': 'Review delayed projects with operations leads today.',
        })

    hr = current.get('hr') or {}
    prev_hr = prev.get('hr') or {}
    if hr.get('pending_leave', 0) > prev_hr.get('pending_leave', 0):
        deltas.append({
            'label': 'Leave backlog grew',
            'detail': f"{prev_hr.get('pending_leave', 0)} → {hr.get('pending_leave', 0)} pending leave",
            'direction': 'up',
            'severity': 'medium',
            'action': 'Clear pending leave approvals.',
        })

    return deltas


def _rule_based_alerts(today: date, metrics: dict) -> list[dict]:
    alerts: list[dict] = []

    cash = metrics.get('cash_position', 0)
    runway = metrics.get('runway', {})
    if runway.get('critical'):
        alerts.append({
            'severity': 'high',
            'title': 'Cash runway critical',
            'detail': f"Only {runway.get('weeks', 0):.0f} weeks of cash at current burn (AED {cash:,.0f} on hand).",
            'action': 'Accelerate collections and defer non-essential payables immediately.',
        })

    recv = metrics.get('receivables', {})
    if recv.get('overdue', 0) > 0:
        alerts.append({
            'severity': 'high',
            'title': 'Overdue receivables',
            'detail': f"AED {recv['overdue']:,.0f} past due across open invoices.",
            'action': 'Use the ranked collections list and call top debtors today.',
        })

    conc = metrics.get('client_concentration')
    if conc and conc.get('pct', 0) >= 25:
        alerts.append({
            'severity': 'medium',
            'title': 'Client concentration risk',
            'detail': f"{conc['name']} is {conc['pct']}% of outstanding receivables.",
            'action': 'Diversify revenue and review credit terms for this client.',
        })

    pay = metrics.get('payables_week', {})
    if pay.get('total', 0) > cash * 0.5:
        alerts.append({
            'severity': 'medium',
            'title': 'Payables due this week',
            'detail': f"AED {pay['total']:,.0f} due in the next 7 days.",
            'action': 'Confirm cash coverage or negotiate payment timing with vendors.',
        })

    rev = metrics.get('revenue_month', {})
    tgt = rev.get('target_mtd') or rev.get('target_month')
    actual = rev.get('actual', 0)
    if tgt and actual < float(tgt) * 0.85:
        alerts.append({
            'severity': 'high',
            'title': 'Revenue below target',
            'detail': f"MTD AED {actual:,.0f} vs prorated target AED {float(tgt):,.0f}.",
            'action': 'Focus sales on deals closing this month and accelerate invoicing.',
        })

    dso = metrics.get('dso')
    dso_prev = metrics.get('dso_prev')
    if dso and dso_prev and dso > dso_prev + 5:
        alerts.append({
            'severity': 'medium',
            'title': 'DSO rising',
            'detail': f"Average days to get paid increased to {dso:.0f} (was {dso_prev:.0f}).",
            'action': 'Tighten payment terms and follow up on slow-paying clients.',
        })

    return alerts[:12]


def _ar_aging_buckets(today: date) -> dict:
    buckets = {'0_30': ZERO, '31_60': ZERO, '61_90': ZERO, 'over_90': ZERO}
    qs = _invoice_balance_qs()
    for inv in qs.values('due_date', 'invoice_date', 'total_amount', 'paid_amount'):
        bal = _money(inv['total_amount']) - _money(inv['paid_amount'])
        if bal <= ZERO:
            continue
        ref = inv['due_date'] or inv['invoice_date']
        if not ref:
            continue
        days = (today - ref).days
        if days <= 30:
            buckets['0_30'] += bal
        elif days <= 60:
            buckets['31_60'] += bal
        elif days <= 90:
            buckets['61_90'] += bal
        else:
            buckets['over_90'] += bal
    return {k: float(v) for k, v in buckets.items()}


def _revenue_trend_12m() -> tuple[list[str], list[float], list[float]]:
    today = _today()
    labels, actual, targets = [], [], []
    y, m = today.year, today.month
    for _ in range(12):
        labels.insert(0, f'{y:04d}-{m:02d}')
        actual.insert(0, float(_month_revenue(y, m)))
        targets.insert(0, float(_revenue_target_month(y, m)))
        m -= 1
        if m <= 0:
            m = 12
            y -= 1
    return labels, actual, targets


def _pipeline_funnel() -> dict:
    leads = Customer.objects.filter(is_active=True, customer_type='lead').count()
    proposals = Estimate.objects.filter(
        is_active=True,
        status__in=('sent', 'approved', 'under_negotiation'),
    ).count()
    won = Estimate.objects.filter(is_active=True, status='quotation_won').count()
    return {'labels': ['Leads', 'Proposals', 'Won'], 'values': [leads, proposals, won]}


def _sales_pipeline_detail(today: date) -> dict:
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    open_estimates = Estimate.objects.filter(
        is_active=True,
        status__in=('sent', 'approved', 'under_negotiation', 'draft'),
    )
    pipeline_total = _money(open_estimates.aggregate(t=Sum('total_amount'))['t'])
    weights = {
        'draft': Decimal('0.15'),
        'sent': Decimal('0.35'),
        'approved': Decimal('0.55'),
        'under_negotiation': Decimal('0.70'),
    }
    weighted = ZERO
    for est in open_estimates.values('status', 'total_amount'):
        weighted += _money(est['total_amount']) * weights.get(est['status'], Decimal('0.25'))

    closing = (
        Estimate.objects.filter(
            is_active=True,
            status__in=('sent', 'approved', 'under_negotiation'),
            valid_until__gte=today,
            valid_until__lte=month_end,
        )
        .select_related('customer')
        .order_by('valid_until')[:8]
    )
    top_deals = (
        Estimate.objects.filter(
            is_active=True,
            status__in=('sent', 'approved', 'under_negotiation', 'quotation_won'),
        )
        .select_related('customer')
        .order_by('-total_amount')[:5]
    )
    month_start = today.replace(day=1)
    won_period = Estimate.objects.filter(
        is_active=True, status='quotation_won', date__gte=month_start, date__lte=month_end,
    ).count()
    lost_period = Estimate.objects.filter(
        is_active=True,
        status='quotation_lost',
        date__gte=month_start - timedelta(days=90),
        date__lte=month_end,
    ).count()
    win_rate = int(won_period / (won_period + lost_period) * 100) if (won_period + lost_period) else 0

    return {
        'pipeline_total': float(pipeline_total),
        'weighted_forecast': float(_money(weighted)),
        'win_rate': win_rate,
        'closing_this_month': [
            {
                'customer': _customer_label(e.customer_id, e.customer.name if e.customer_id else None),
                'amount': float(_money(e.total_amount)),
                'valid_until': e.valid_until.isoformat() if e.valid_until else '',
                'status': e.get_status_display(),
            }
            for e in closing
        ],
        'top_deals': [
            {
                'customer': _customer_label(d.customer_id, d.customer.name if d.customer_id else None),
                'amount': float(_money(d.total_amount)),
                'status': d.get_status_display(),
            }
            for d in top_deals
        ],
    }


def _prev_month_same_day(today: date) -> date:
    y, m = today.year, today.month
    m -= 1
    if m <= 0:
        m = 12
        y -= 1
    day = min(today.day, monthrange(y, m)[1])
    return date(y, m, day)


def build_ceo_metrics() -> dict:
    today = _today()
    cash = _cash_position()
    burn = _average_monthly_burn()
    runway = _cash_runway(cash, burn)

    rev_mtd = _mtd_revenue(today)
    target_month = _revenue_target_month(today.year, today.month)
    target_mtd = _revenue_target_mtd(today.year, today.month, today)
    rev_vs = _revenue_vs_target(rev_mtd, target_mtd)

    prev_day = _prev_month_same_day(today)
    rev_prev_mtd = _revenue_between(prev_day.replace(day=1), prev_day)

    recv = _receivables_snapshot(today)
    prev_snap = _load_snapshot(prev_day) or _load_snapshot(today - timedelta(days=30))
    recv_prev = (prev_snap or {}).get('receivables', {}).get('total')

    pay_week = _payables_due_week(today)
    profit_cur = _profit_for_month(today.year, today.month)
    y, m = today.year, today.month
    m -= 1
    if m <= 0:
        m = 12
        y -= 1
    profit_prev = _profit_for_month(y, m)

    outstanding = _money(Decimal(str(recv['total'])))
    dso = _dso(outstanding, today)
    dso_prev = (prev_snap or {}).get('dso')

    from apps.reports.services.ai_finance.utils import payment_cash_flow_monthly

    cash_hist = payment_cash_flow_monthly(3)
    cash_prev = cash_hist[-2]['closing_balance'] if len(cash_hist) >= 2 else None

    pipeline = _sales_pipeline_detail(today)
    conc = _client_concentration(today)
    aging = _ar_aging_buckets(today)
    rev_labels, rev_actual, rev_targets = _revenue_trend_12m()

    overdue_count = _invoice_balance_qs().filter(due_date__lt=today).count()
    payables_week_prev = (prev_snap or {}).get('payables_week', {}).get('total')

    yesterday_snap = _load_snapshot(today - timedelta(days=1))
    from apps.settings_app.services.ceo_operations import build_hr_overview, build_projects_overview

    projects_overview = build_projects_overview(prev_snap=prev_snap, yesterday_snap=yesterday_snap)
    hr_overview = build_hr_overview(prev_snap=prev_snap, yesterday_snap=yesterday_snap)

    metrics = {
        'as_of': today.isoformat(),
        'currency': 'AED',
        'cash_position': float(cash),
        'runway': runway,
        'revenue_month': {
            'actual': rev_vs['actual'],
            'target_mtd': rev_vs['target_mtd'],
            'target_month': rev_vs['target_month'],
            'pct_of_target': rev_vs['pct'],
            'pct_raw': rev_vs['pct_raw'],
            'bar_pct': rev_vs['bar_pct'],
            'over_target': rev_vs['over_target'],
        },
        'receivables': recv,
        'payables_week': pay_week,
        'profit': {
            'amount': float(profit_cur['profit']),
            'margin_pct': profit_cur['margin_pct'],
            'prev_amount': float(profit_prev['profit']),
            'prev_margin_pct': profit_prev['margin_pct'],
        },
        'dso': dso,
        'dso_prev': dso_prev,
        'client_concentration': conc,
        'pipeline': pipeline,
        'overdue_invoice_count': overdue_count,
        'collection_candidates': build_collection_candidates(5),
        'monthly_burn': float(burn),
        'payables_week_prev': payables_week_prev,
        'projects': projects_overview,
        'hr': hr_overview,
    }

    _persist_snapshot(today, metrics)
    rule_alerts = _rule_based_alerts(today, metrics)
    yesterday_deltas = build_yesterday_deltas(metrics)

    def _card(key, label, value, *, suffix='', hint='', vs=None, bad_when_up=False, alert=False, extra=None):
        card = {
            'key': key,
            'label': label,
            'value': value,
            'value_suffix': suffix,
            'hint': hint,
            'alert': alert,
            'bad_when_up': bad_when_up,
        }
        if extra:
            card.update(extra)
        if vs:
            card['vs_pct'] = vs.get('pct')
            card['delta_label'] = vs.get('label', 'vs last month')
            card['direction'] = vs.get('direction', 'neutral')
        return card

    money_cards = [
        _card(
            'cash', 'Cash position', float(cash),
            hint='Bank + cash accounts',
            vs=_vs_last_month(float(cash), cash_prev),
        ),
        _card(
            'runway', 'Cash runway at current burn',
            runway['weeks'] if runway['weeks'] is not None else 0,
            suffix=' wks' if runway['weeks'] is not None else '',
            hint=f"Burn ~AED {runway['burn']:,.0f}/mo · {runway.get('months', 0)} mo" if runway['burn'] else 'Set payroll/bills history',
            alert=runway.get('critical', False),
        ),
        _card(
            'receivables', 'Outstanding receivables', recv['total'],
            hint=f"{recv['count']} open · AED {recv['overdue']:,.0f} overdue",
            vs=_vs_last_month(recv['total'], recv_prev, bad_when_up=True),
            bad_when_up=True,
        ),
        _card(
            'revenue', 'Revenue this month (MTD)', rev_vs['actual'],
            hint=(
                f"Target AED {rev_vs['target_mtd']:,.0f} MTD · "
                f"{'Ahead of plan' if rev_vs['over_target'] else 'full month target AED {0:,.0f}'.format(rev_vs['target_month'])}"
            ),
            vs=_vs_last_month(rev_vs['actual'], float(rev_prev_mtd)),
        ),
        _card(
            'dso', 'Avg days to get paid', dso or 0,
            suffix=' days' if dso else '',
            hint='DSO (90-day basis)',
            vs=_vs_last_month(dso or 0, dso_prev, bad_when_up=True) if dso and dso_prev else {'pct': None, 'direction': 'neutral', 'label': 'vs last month'},
            alert=bool(dso and dso_prev and dso > dso_prev),
        ),
        _card(
            'payables', 'Payables due this week', pay_week['total'],
            hint=f"{pay_week['count']} bill(s)",
            vs=_vs_last_month(pay_week['total'], payables_week_prev, bad_when_up=True),
            bad_when_up=True,
        ),
        _card(
            'profit', 'Profit this month', float(profit_cur['profit']),
            hint=(
                f"Margin {profit_cur['margin_pct']}% "
                f"({profit_cur['margin_pct'] - profit_prev['margin_pct']:+.1f} pp vs last month)"
            ),
            vs=_vs_last_month(float(profit_cur['profit']), float(profit_prev['profit'])),
            extra={'margin_pct': profit_cur['margin_pct']},
        ),
    ]

    if rev_vs['pct_raw'] is not None:
        money_cards[3]['target_pct'] = rev_vs['pct_raw']
        money_cards[3]['target_bar_pct'] = rev_vs['bar_pct']
        money_cards[3]['over_target'] = rev_vs['over_target']
        money_cards[3]['target_label'] = (
            f"{rev_vs['pct_raw']}% of MTD target (AED {rev_vs['actual']:,.0f} / {rev_vs['target_mtd']:,.0f})"
        )

    return {
        'metrics': metrics,
        'money_cards': money_cards,
        'charts': {
            'revenue_trend': {'labels': rev_labels, 'actual': rev_actual, 'target': rev_targets},
            'ar_aging': {
                'labels': ['0–30 days', '31–60', '61–90', '90+'],
                'values': [aging['0_30'], aging['31_60'], aging['61_90'], aging['over_90']],
            },
            'pipeline_funnel': _pipeline_funnel(),
            'cash_forecast': {
                'labels': [h['month'] for h in payment_cash_flow_monthly(6)],
                'values': [h['closing_balance'] for h in payment_cash_flow_monthly(6)],
                'is_historical': True,
            },
        },
        'pipeline': pipeline,
        'rule_alerts': rule_alerts,
        'yesterday_deltas': yesterday_deltas,
        'metrics_snapshot': metrics,
        'projects_overview': projects_overview,
        'hr_overview': hr_overview,
    }
