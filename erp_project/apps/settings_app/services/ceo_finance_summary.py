"""CEO executive summary — read-only finance module metrics (no writes)."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from apps.finance.accounting_dashboard import (
    MONTH_FIELDS,
    ZERO,
    _all_income_account_ids,
    _cogs_account_ids,
    _compute_ar_aging_totals,
    _gl_income_total,
    _money,
    _overhead_account_ids,
    _resolve_ar_accounts,
    _sum_pl_accounts,
)
from apps.finance.models import AccountType, Budget, Payment
from apps.sales.models import Invoice

PAYMENT_CONFIRMED = ('confirmed', 'reconciled')
INVOICE_POSTED_STATUSES = ('posted', 'sent', 'paid', 'partial', 'overdue')


def _budget_revenue_target_month(year: int, month: int) -> Decimal | None:
    """Monthly revenue target from approved finance budget income lines only."""
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
    if not budget:
        return None

    lines = budget.lines.filter(
        Q(account__account_category='operating_revenue')
        | Q(account__account_type=AccountType.INCOME),
    )
    if not lines.exists():
        return None

    target = ZERO
    for line in lines:
        monthly = _money(getattr(line, field, ZERO))
        if monthly <= ZERO and line.amount > ZERO:
            monthly = _money(line.amount / Decimal('12'))
        target += monthly
    return target if target > ZERO else None


def _prorate_target(full_target: Decimal | None, date_from: date, date_to: date, *, period: str) -> Decimal | None:
    if full_target is None:
        return None
    if period == 'month' and date_from.year == date_to.year and date_from.month == date_to.month:
        days_in_month = monthrange(date_to.year, date_to.month)[1]
        return _money(full_target * Decimal(date_to.day) / Decimal(days_in_month))
    days = (date_to - date_from).days + 1
    days_in_month = monthrange(date_to.year, date_to.month)[1]
    return _money(full_target * Decimal(days) / Decimal(days_in_month))


def _pl_for_period(date_from: date, date_to: date) -> dict:
    """Gross / net profit from posted GL (same basis as accounting dashboard P&L)."""
    if not _all_income_account_ids():
        return {'revenue': None, 'gross_profit_pct': None, 'net_profit_pct': None}

    revenue = _gl_income_total(date_from, date_to)
    cogs_ids = _cogs_account_ids()
    overhead_ids = _overhead_account_ids(cogs_ids)
    cogs = _sum_pl_accounts(cogs_ids, date_from, date_to, income=False) if cogs_ids else ZERO
    overhead = _sum_pl_accounts(overhead_ids, date_from, date_to, income=False) if overhead_ids else ZERO
    gp = _money(revenue - cogs)
    np = _money(gp - overhead)

    gross_pct = float(gp / revenue * 100) if revenue > ZERO else None
    net_pct = float(np / revenue * 100) if revenue > ZERO else None
    return {
        'revenue': revenue,
        'gross_profit_pct': round(gross_pct, 1) if gross_pct is not None else None,
        'net_profit_pct': round(net_pct, 1) if net_pct is not None else None,
    }


def _invoiced_in_period(date_from: date, date_to: date) -> Decimal | None:
    """Posted sales invoices in period (finance-linked)."""
    if not Invoice.objects.filter(is_active=True).exclude(status='cancelled').exists():
        return None
    qs = (
        Invoice.objects.filter(is_active=True)
        .exclude(status__in=('draft', 'cancelled'))
        .filter(invoice_date__gte=date_from, invoice_date__lte=date_to)
    )
    if not qs.exists():
        return ZERO
    posted = qs.filter(journal_entry__isnull=False)
    if posted.exists():
        return _money(posted.aggregate(t=Sum('total_amount'))['t'])
    return _money(qs.aggregate(t=Sum('total_amount'))['t'])


def _collections_in_period(date_from: date, date_to: date) -> Decimal | None:
    """Customer receipts recorded in finance Payment module."""
    if not Payment.objects.filter(is_active=True).exists():
        return None
    total = (
        Payment.objects.filter(
            is_active=True,
            payment_type='received',
            status__in=PAYMENT_CONFIRMED,
            payment_date__gte=date_from,
            payment_date__lte=date_to,
        ).aggregate(t=Sum('amount'))['t']
    )
    return _money(total)


def _cash_outflow_in_period(date_from: date, date_to: date) -> Decimal | None:
    if not Payment.objects.filter(is_active=True).exists():
        return None
    total = (
        Payment.objects.filter(
            is_active=True,
            payment_type='made',
            status__in=PAYMENT_CONFIRMED,
            payment_date__gte=date_from,
            payment_date__lte=date_to,
        ).aggregate(t=Sum('amount'))['t']
    )
    return _money(total)


def _overdue_receivables_finance(as_of: date) -> Decimal | None:
    """Outstanding trade receivables from finance GL aging (not sales invoice UI)."""
    if not _resolve_ar_accounts().exists():
        return None
    aging = _compute_ar_aging_totals(as_of)
    total = _money(sum(aging.values(), ZERO))
    return total


def build_finance_summary_cards(date_from: date, date_to: date, *, period: str) -> dict:
    """
    Finance-sourced KPI values for the CEO executive summary.
    Values are None when the finance source is not configured or not applicable.
    """
    today = date_to
    full_rev_target = _budget_revenue_target_month(today.year, today.month)
    rev_target = _prorate_target(full_rev_target, date_from, date_to, period=period)

    pl = _pl_for_period(date_from, date_to)
    revenue_achieved = pl['revenue']

    revenue_gap = None
    if rev_target is not None and revenue_achieved is not None:
        revenue_gap = max(ZERO, rev_target - revenue_achieved)

    invoiced = _invoiced_in_period(date_from, date_to)
    collected = _collections_in_period(date_from, date_to)
    paid_out = _cash_outflow_in_period(date_from, date_to)

    net_cash = None
    if collected is not None and paid_out is not None:
        net_cash = collected - paid_out

    overdue_recv = _overdue_receivables_finance(today)

    return {
        'rev_target_full': full_rev_target,
        'rev_target': rev_target,
        'revenue_achieved': revenue_achieved,
        'revenue_gap': revenue_gap,
        'invoiced': invoiced,
        'collected': collected,
        'paid_out': paid_out,
        'net_cash': net_cash,
        'gross_profit_pct': pl['gross_profit_pct'],
        'net_profit_pct': pl['net_profit_pct'],
        'overdue_receivables': overdue_recv,
        'revenue_achieved_hint': 'Posted GL income (Finance)',
        'collection_target_hint': 'Posted invoices in period',
        'collection_achieved_hint': 'Finance · payments received',
        'cash_hint': 'Finance · confirmed payments',
        'gross_hint': 'GL income − COGS (Finance P&L)',
        'net_hint': 'GL gross profit − overhead (Finance P&L)',
        'overdue_hint': 'Trade receivables · GL aging',
        'rev_target_hint': (
            f'Budget · full month AED {float(full_rev_target):,.0f}'
            if full_rev_target is not None
            else 'No revenue budget configured'
        ),
    }
