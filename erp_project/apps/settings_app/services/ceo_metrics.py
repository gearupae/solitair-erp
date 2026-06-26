"""Live ERP metrics for the CEO dashboard — decision-focused only."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.crm.models import Customer
from apps.finance.models import Account, BankAccount, Budget, BudgetLine
from apps.purchase.models import VendorBill
from apps.sales.models import Estimate, Invoice

INVOICE_OPEN_STATUSES = ('posted', 'sent', 'paid', 'partial', 'overdue')
INVOICE_REVENUE_STATUSES = INVOICE_OPEN_STATUSES
BILL_OPEN_STATUSES = ('posted', 'paid', 'partial', 'overdue', 'pending')
ZERO = Decimal('0.00')

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


def _month_revenue(year: int, month: int) -> Decimal:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    total = (
        Invoice.objects.filter(
            is_active=True,
            invoice_date__gte=start,
            invoice_date__lte=end,
            status__in=INVOICE_REVENUE_STATUSES,
        ).aggregate(t=Coalesce(Sum('total_amount'), ZERO))['t']
        or ZERO
    )
    return _money(total)


def _month_expense(year: int, month: int) -> Decimal:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    bills = (
        VendorBill.objects.filter(
            is_active=True,
            bill_date__gte=start,
            bill_date__lte=end,
            status__in=BILL_OPEN_STATUSES,
        ).aggregate(t=Coalesce(Sum('total_amount'), ZERO))['t']
        or ZERO
    )
    return _money(bills)


def _revenue_target_month(year: int, month: int) -> Decimal:
    """Monthly revenue target from approved budget on revenue accounts, else trailing average."""
    month_idx = month - 1
    field = MONTH_FIELDS[month_idx]
    budgets = Budget.objects.filter(is_active=True, status__in=('approved', 'locked'))
    target = ZERO
    for budget in budgets:
        lines = BudgetLine.objects.filter(
            budget=budget,
            account__account_category='operating_revenue',
        ).select_related('account')
        for line in lines:
            target += _money(getattr(line, field, ZERO))
    if target > ZERO:
        return target

    # Fallback: avg of last 3 complete months × 1.05
    today = _today()
    samples = []
    y, m = today.year, today.month
    for _ in range(3):
        m -= 1
        if m <= 0:
            m = 12
            y -= 1
        samples.append(_month_revenue(y, m))
    if samples:
        avg = sum(samples, ZERO) / len(samples)
        return _money(avg * Decimal('1.05'))
    return ZERO


def _cash_position() -> Decimal:
    total = (
        BankAccount.objects.filter(is_active=True).aggregate(
            t=Coalesce(Sum('current_balance'), ZERO),
        )['t']
        or ZERO
    )
    if total > ZERO:
        return _money(total)
    # Fallback: GL cash/bank accounts
    gl = (
        Account.objects.filter(is_active=True, is_cash_account=True).aggregate(
            t=Coalesce(Sum('balance'), ZERO),
        )['t']
        or ZERO
    )
    return _money(gl)


def _receivables_snapshot(today: date) -> dict:
    qs = (
        Invoice.objects.filter(is_active=True, status__in=INVOICE_OPEN_STATUSES)
        .annotate(
            balance=ExpressionWrapper(
                F('total_amount') - F('paid_amount'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        .filter(balance__gt=ZERO)
        .select_related('customer')
    )
    total = _money(qs.aggregate(t=Coalesce(Sum('balance'), ZERO))['t'])
    overdue = _money(
        qs.filter(due_date__lt=today).aggregate(t=Coalesce(Sum('balance'), ZERO))['t'],
    )
    return {'total': float(total), 'overdue': float(overdue), 'count': qs.count()}


def _ar_aging_buckets(today: date) -> dict:
    buckets = {'0_30': ZERO, '31_60': ZERO, '61_90': ZERO, 'over_90': ZERO}
    qs = (
        Invoice.objects.filter(is_active=True, status__in=INVOICE_OPEN_STATUSES)
        .annotate(
            balance=ExpressionWrapper(
                F('total_amount') - F('paid_amount'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        .filter(balance__gt=ZERO)
    )
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
            balance=ExpressionWrapper(
                F('total_amount') - F('paid_amount'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        .filter(balance__gt=ZERO)
    )
    total = _money(qs.aggregate(t=Coalesce(Sum('balance'), ZERO))['t'])
    return {'total': float(total), 'count': qs.count()}


def _profit_margin_trend() -> list[dict]:
    today = _today()
    rows = []
    y, m = today.year, today.month
    for _ in range(6):
        rev = _month_revenue(y, m)
        exp = _month_expense(y, m)
        margin = float((rev - exp) / rev * 100) if rev else 0.0
        rows.insert(0, {
            'month': f'{y:04d}-{m:02d}',
            'revenue': float(rev),
            'margin_pct': round(margin, 1),
        })
        m -= 1
        if m <= 0:
            m = 12
            y -= 1
    return rows


def _revenue_trend_12m() -> tuple[list[str], list[float], list[float]]:
    today = _today()
    labels = []
    actual = []
    targets = []
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
    return {
        'labels': ['Leads', 'Proposals', 'Won'],
        'values': [leads, proposals, won],
    }


def _sales_pipeline_detail(today: date) -> dict:
    month_start = today.replace(day=1)
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])

    open_estimates = Estimate.objects.filter(
        is_active=True,
        status__in=('sent', 'approved', 'under_negotiation', 'draft'),
    )

    pipeline_total = _money(
        open_estimates.aggregate(t=Coalesce(Sum('total_amount'), ZERO))['t'],
    )
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
    closing_list = [
        {
            'customer': (e.customer.name if e.customer_id else '—'),
            'amount': float(_money(e.total_amount)),
            'valid_until': e.valid_until.isoformat() if e.valid_until else '',
            'status': e.get_status_display(),
        }
        for e in closing
    ]

    won_period = Estimate.objects.filter(
        is_active=True,
        status='quotation_won',
        date__gte=month_start,
        date__lte=month_end,
    ).count()
    lost_period = Estimate.objects.filter(
        is_active=True,
        status='quotation_lost',
        date__gte=month_start - timedelta(days=90),
        date__lte=month_end,
    ).count()
    win_rate = int(won_period / (won_period + lost_period) * 100) if (won_period + lost_period) else 0

    top_deals = (
        Estimate.objects.filter(
            is_active=True,
            status__in=('sent', 'approved', 'under_negotiation', 'quotation_won'),
        )
        .select_related('customer')
        .order_by('-total_amount')[:5]
    )
    top_deals_list = [
        {
            'customer': (d.customer.name if d.customer_id else '—'),
            'amount': float(_money(d.total_amount)),
            'status': d.get_status_display(),
        }
        for d in top_deals
    ]

    return {
        'pipeline_total': float(pipeline_total),
        'weighted_forecast': float(_money(weighted)),
        'win_rate': win_rate,
        'closing_this_month': closing_list,
        'top_deals': top_deals_list,
    }


def _rule_based_alerts(today: date, metrics: dict) -> list[dict]:
    alerts: list[dict] = []

    recv = metrics.get('receivables', {})
    if recv.get('overdue', 0) > 0:
        alerts.append({
            'severity': 'high',
            'title': 'Overdue receivables',
            'detail': f"AED {recv['overdue']:,.0f} past due across open invoices.",
            'action': 'Prioritise collections on largest overdue accounts this week.',
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
    if pay.get('total', 0) > metrics.get('cash_position', 0) * 0.5:
        alerts.append({
            'severity': 'medium',
            'title': 'Payables due this week',
            'detail': f"AED {pay['total']:,.0f} due in the next 7 days.",
            'action': 'Confirm cash coverage or negotiate payment timing with vendors.',
        })

    from apps.contracts.models import Contract

    expiring_contracts = Contract.objects.filter(
        is_active=True,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=30),
    ).count()
    if expiring_contracts:
        alerts.append({
            'severity': 'medium',
            'title': 'Contracts expiring soon',
            'detail': f'{expiring_contracts} contract(s) end within 30 days.',
            'action': 'Review renewal terms and assign owners to extend or replace.',
        })

    from apps.hr.expiry_alerts import get_expiry_alerts

    hr_exp = get_expiry_alerts()
    critical_hr = [r for r in hr_exp if r.get('status') in ('expired', 'red')][:3]
    if critical_hr:
        alerts.append({
            'severity': 'high',
            'title': 'Visa / compliance documents expiring',
            'detail': f'{len(critical_hr)} employee document(s) expired or due within 7 days.',
            'action': 'Open HR compliance dashboard and initiate renewals immediately.',
        })

    from apps.fleet.models import Vehicle

    horizon = today + timedelta(days=10)
    fleet_count = Vehicle.objects.filter(is_active=True).filter(
        Q(mulkiya_expiry__lte=horizon) | Q(insurance_expiry__lte=horizon),
    ).count()
    if fleet_count:
        alerts.append({
            'severity': 'low',
            'title': 'Fleet documents due',
            'detail': f'{fleet_count} vehicle document(s) expiring within 10 days.',
            'action': 'Renew mulkiya / insurance before vehicles are grounded.',
        })

    rev = metrics.get('revenue_month', {})
    target = rev.get('target', 0)
    actual = rev.get('actual', 0)
    if target and actual < target * 0.85:
        alerts.append({
            'severity': 'high',
            'title': 'Revenue below target',
            'detail': f"Month-to-date revenue is {rev.get('pct_of_target', 0)}% of target.",
            'action': 'Focus sales on deals closing this month and accelerate invoicing.',
        })

    return alerts[:12]


def _client_concentration(today: date) -> dict | None:
    qs = (
        Invoice.objects.filter(is_active=True, status__in=INVOICE_OPEN_STATUSES)
        .annotate(
            balance=ExpressionWrapper(
                F('total_amount') - F('paid_amount'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        .filter(balance__gt=ZERO)
        .values('customer__name')
        .annotate(total=Sum('balance'))
        .order_by('-total')
    )
    rows = list(qs[:5])
    if not rows:
        return None
    grand = sum(_money(r['total']) for r in rows)
    if not grand:
        return None
    top = rows[0]
    pct = int(_money(top['total']) / grand * 100)
    if pct < 20:
        return {'name': top['customer__name'] or 'Unknown', 'pct': pct, 'warn': False}
    return {'name': top['customer__name'] or 'Unknown', 'pct': pct, 'warn': pct >= 25}


def build_ceo_metrics() -> dict:
    """Aggregate all live CEO dashboard metrics."""
    today = _today()
    cash = _cash_position()
    rev_mtd = _month_revenue(today.year, today.month)
    rev_target = _revenue_target_month(today.year, today.month)
    rev_ly = _month_revenue(today.year - 1, today.month)
    recv = _receivables_snapshot(today)
    pay_week = _payables_due_week(today)
    margin_trend = _profit_margin_trend()
    rev_labels, rev_actual, rev_targets = _revenue_trend_12m()
    funnel = _pipeline_funnel()
    pipeline = _sales_pipeline_detail(today)
    aging = _ar_aging_buckets(today)
    conc = _client_concentration(today)

    pct_target = int(rev_mtd / rev_target * 100) if rev_target else None
    pct_ly = _pct_change(rev_mtd, rev_ly)

    metrics = {
        'as_of': today.isoformat(),
        'currency': 'AED',
        'cash_position': float(cash),
        'revenue_month': {
            'actual': float(rev_mtd),
            'target': float(rev_target),
            'last_year': float(rev_ly),
            'pct_of_target': pct_target,
            'pct_vs_last_year': pct_ly,
        },
        'receivables': recv,
        'payables_week': pay_week,
        'profit_margin_latest': margin_trend[-1]['margin_pct'] if margin_trend else 0,
        'profit_margin_prev': margin_trend[-2]['margin_pct'] if len(margin_trend) > 1 else None,
        'client_concentration': conc,
        'pipeline': pipeline,
    }

    rule_alerts = _rule_based_alerts(today, metrics)

    from apps.reports.services.ai_finance.utils import payment_cash_flow_monthly

    cash_hist = payment_cash_flow_monthly(6)
    cash_hist_labels = [h['month'] for h in cash_hist]
    cash_hist_values = [h['closing_balance'] for h in cash_hist]

    return {
        'metrics': metrics,
        'money_cards': [
            {
                'key': 'cash',
                'label': 'Cash position',
                'value': float(cash),
                'delta': None,
                'direction': 'neutral',
                'hint': 'Bank + cash accounts',
            },
            {
                'key': 'revenue',
                'label': 'Revenue this month',
                'value': float(rev_mtd),
                'delta': pct_target,
                'delta_label': '% of target' if pct_target is not None else '',
                'direction': 'up' if pct_target and pct_target >= 100 else 'down',
                'hint': f"Target AED {float(rev_target):,.0f} · LY {pct_ly:+d}%" if pct_ly is not None else '',
            },
            {
                'key': 'receivables',
                'label': 'Outstanding receivables',
                'value': recv['total'],
                'delta': recv['overdue'],
                'delta_label': 'overdue',
                'direction': 'down' if recv['overdue'] > 0 else 'up',
                'hint': f"{recv['count']} open invoice(s)",
            },
            {
                'key': 'payables',
                'label': 'Payables due this week',
                'value': pay_week['total'],
                'delta': None,
                'direction': 'down' if pay_week['total'] > float(cash) * 0.3 else 'neutral',
                'hint': f"{pay_week['count']} bill(s)",
            },
            {
                'key': 'margin',
                'label': 'Profit margin (latest month)',
                'value': metrics['profit_margin_latest'],
                'value_suffix': '%',
                'delta': (
                    round(metrics['profit_margin_latest'] - metrics['profit_margin_prev'], 1)
                    if metrics['profit_margin_prev'] is not None
                    else None
                ),
                'delta_label': 'pp vs prior month',
                'direction': (
                    'up'
                    if metrics['profit_margin_prev'] is not None
                    and metrics['profit_margin_latest'] >= metrics['profit_margin_prev']
                    else 'down'
                ),
                'hint': 'Revenue minus vendor bills',
            },
        ],
        'charts': {
            'revenue_trend': {
                'labels': rev_labels,
                'actual': rev_actual,
                'target': rev_targets,
            },
            'ar_aging': {
                'labels': ['0–30 days', '31–60', '61–90', '90+'],
                'values': [
                    aging['0_30'],
                    aging['31_60'],
                    aging['61_90'],
                    aging['over_90'],
                ],
            },
            'pipeline_funnel': funnel,
            'cash_forecast': {
                'labels': cash_hist_labels,
                'values': cash_hist_values,
                'is_historical': True,
            },
        },
        'pipeline': pipeline,
        'rule_alerts': rule_alerts,
        'metrics_snapshot': metrics,
    }
