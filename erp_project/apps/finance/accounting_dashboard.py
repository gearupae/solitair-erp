"""Read-only Accounting Dashboard — queries existing finance data only."""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce, ExtractMonth
from django.utils import timezone

from apps.finance.models import (
    Account,
    AccountCategory,
    AccountMapping,
    AccountType,
    BankAccount,
    Budget,
    FiscalYear,
    JournalEntryLine,
)

ZERO = Decimal('0.00')
MONTH_FIELDS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

REVENUE_ACCOUNT_CODES = ('4000', '4100')
COGS_ACCOUNT_CODES = ('5000', '5100')
CASH_ACCOUNT_CODES = ('1000', '1010')


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _money(value) -> Decimal:
    if value is None:
        return ZERO
    return _quantize(Decimal(value))


def resolve_fiscal_year(fy_id=None, today: date | None = None) -> FiscalYear | None:
    today = today or timezone.localdate()
    qs = FiscalYear.objects.filter(is_active=True)
    if fy_id:
        return qs.filter(pk=fy_id).first()
    current = qs.filter(start_date__lte=today, end_date__gte=today).first()
    return current or qs.order_by('-start_date').first()


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _accounts_by_code_prefix(prefixes: tuple[str, ...]):
    q = Q()
    for prefix in prefixes:
        q |= Q(code=prefix) | Q(code__startswith=f'{prefix}-')
    return list(Account.objects.filter(is_active=True).filter(q))


def _account_ids_with_descendants(roots: list[Account]) -> list[int]:
    if not roots:
        return []
    root_ids = {a.id for a in roots}
    all_accounts = list(Account.objects.filter(is_active=True).only('id', 'parent_id'))
    children: dict[int | None, list[int]] = {}
    for acc in all_accounts:
        children.setdefault(acc.parent_id, []).append(acc.id)

    ids: set[int] = set()

    def walk(aid: int):
        ids.add(aid)
        for cid in children.get(aid, []):
            walk(cid)

    for rid in root_ids:
        walk(rid)
    return list(ids)


def _resolve_ar_accounts():
    """Trade receivables — AccountMapping first, then category/name (matches CoA setup)."""
    mapped_ids = list(
        AccountMapping.objects.filter(
            transaction_type__in=('sales_invoice_receivable', 'customer_receipt_ar_clear'),
            account__is_active=True,
        ).values_list('account_id', flat=True)
    )
    if mapped_ids:
        return Account.objects.filter(id__in=set(mapped_ids), is_active=True)
    return Account.objects.filter(is_active=True, account_type=AccountType.ASSET).filter(
        Q(account_category=AccountCategory.TRADE_RECEIVABLES)
        | Q(name__icontains='accounts receivable')
        | Q(name__icontains='trade debtor')
    ).exclude(
        Q(name__icontains='pdc') | Q(account_category=AccountCategory.INVENTORY)
    )


def _resolve_ap_account_ids() -> list[int]:
    """AP clearing / payable accounts from AccountMapping, fallback to trade payables."""
    mapped_ids = list(
        AccountMapping.objects.filter(
            transaction_type__in=('vendor_bill_payable', 'vendor_payment_ap_clear'),
            account__is_active=True,
        ).values_list('account_id', flat=True)
    )
    if mapped_ids:
        return list(set(mapped_ids))
    return list(
        Account.objects.filter(is_active=True, account_type=AccountType.LIABILITY).filter(
            Q(account_category=AccountCategory.TRADE_PAYABLES)
            | Q(code='2000')
            | Q(name__icontains='accounts payable')
        )
        .exclude(name__icontains='grn clearing')
        .values_list('id', flat=True)
    )


def _all_income_account_ids() -> list[int]:
    return list(Account.objects.filter(is_active=True, account_type=AccountType.INCOME).values_list('id', flat=True))


def _all_expense_account_ids() -> list[int]:
    return list(Account.objects.filter(is_active=True, account_type=AccountType.EXPENSE).values_list('id', flat=True))


def _cogs_account_ids() -> list[int]:
    roots = list(
        Account.objects.filter(is_active=True, account_type=AccountType.EXPENSE).filter(
            Q(code__in=COGS_ACCOUNT_CODES)
            | Q(code__startswith='5000')
            | Q(code__startswith='5100')
            | Q(account_category=AccountCategory.COST_OF_SALES)
            | Q(name__icontains='cost of goods')
            | Q(name__icontains='cost of sales')
        )
    )
    ids = _account_ids_with_descendants(roots)
    return ids if ids else []


def _overhead_account_ids(cogs_ids: list[int]) -> list[int]:
    cogs_set = set(cogs_ids)
    return [aid for aid in _all_expense_account_ids() if aid not in cogs_set]


def _gl_income_total(start_date: date, end_date: date) -> Decimal:
    """Posted GL income (credit − debit) — same basis as Profit & Loss report."""
    return _sum_pl_accounts(_all_income_account_ids(), start_date, end_date, income=True)


def _account_balance_as_of(account: Account, as_of_date: date) -> Decimal:
    """Opening balance + posted activity through as_of_date (matches GL)."""
    agg = JournalEntryLine.objects.filter(
        account=account,
        journal_entry__status='posted',
        journal_entry__date__lte=as_of_date,
    ).aggregate(total_debit=Coalesce(Sum('debit'), ZERO), total_credit=Coalesce(Sum('credit'), ZERO))
    debit = agg['total_debit']
    credit = agg['total_credit']
    if account.debit_increases:
        return _money(account.opening_balance + debit - credit)
    return _money(account.opening_balance + credit - debit)


def _pl_aggregate_direct_balances(account_ids, start_date, end_date, income_side: bool):
    """Same logic as finance.views._pl_aggregate_direct_balances (read-only copy)."""
    if not account_ids:
        return {}
    rows = (
        JournalEntryLine.objects.filter(
            account_id__in=account_ids,
            journal_entry__status='posted',
            journal_entry__date__gte=start_date,
            journal_entry__date__lte=end_date,
        )
        .values('account_id')
        .annotate(total_debit=Sum('debit'), total_credit=Sum('credit'))
    )
    out = {}
    for row in rows:
        d = row['total_debit'] or ZERO
        c = row['total_credit'] or ZERO
        out[row['account_id']] = (c - d) if income_side else (d - c)
    return out


def _sum_pl_accounts(account_ids: list[int], start_date: date, end_date: date, *, income: bool) -> Decimal:
    if not account_ids:
        return ZERO
    direct = _pl_aggregate_direct_balances(account_ids, start_date, end_date, income_side=income)
    return _money(sum(direct.values(), ZERO))


def _compute_ar_aging_totals(as_of_date: date) -> dict[str, Decimal]:
    """FIFO AR aging on mapped trade receivable accounts (not inventory)."""
    ar_accounts = _resolve_ar_accounts()
    totals = {
        'days_30': ZERO,
        'days_60': ZERO,
        'days_90': ZERO,
        'above_90': ZERO,
    }
    if not ar_accounts.exists():
        return totals

    ar_lines = JournalEntryLine.objects.filter(
        account__in=ar_accounts,
        journal_entry__status='posted',
        journal_entry__date__lte=as_of_date,
        debit__gt=0,
    ).select_related('journal_entry').order_by('journal_entry__date')

    invoice_balances: dict[str, dict] = {}
    for line in ar_lines:
        ref = line.journal_entry.reference
        if ref not in invoice_balances:
            invoice_balances[ref] = {
                'date': line.journal_entry.date,
                'debit': ZERO,
                'credit': ZERO,
            }
        invoice_balances[ref]['debit'] += line.debit

    ar_credits = JournalEntryLine.objects.filter(
        account__in=ar_accounts,
        journal_entry__status='posted',
        journal_entry__date__lte=as_of_date,
        credit__gt=0,
    ).select_related('journal_entry')

    unmatched_credits = ZERO
    for line in ar_credits:
        ref = line.journal_entry.reference
        if ref in invoice_balances:
            invoice_balances[ref]['credit'] += line.credit
        else:
            unmatched_credits += line.credit

    if unmatched_credits > 0:
        sorted_refs = sorted(invoice_balances.keys(), key=lambda r: invoice_balances[r]['date'])
        remaining = unmatched_credits
        for ref in sorted_refs:
            if remaining <= 0:
                break
            data = invoice_balances[ref]
            outstanding = data['debit'] - data['credit']
            if outstanding <= 0:
                continue
            apply = min(remaining, outstanding)
            data['credit'] += apply
            remaining -= apply

    for data in invoice_balances.values():
        outstanding = data['debit'] - data['credit']
        if outstanding <= 0:
            continue
        days_old = (as_of_date - data['date']).days
        if days_old <= 30:
            totals['days_30'] += outstanding
        elif days_old <= 60:
            totals['days_60'] += outstanding
        elif days_old <= 90:
            totals['days_90'] += outstanding
        else:
            totals['above_90'] += outstanding

    for key in totals:
        totals[key] = _money(totals[key])
    return totals


def _fleet_expense_account_ids() -> list[int]:
    fleet_q = (
        Q(code='500037')
        | Q(name__icontains='vehicle')
        | Q(name__icontains='fleet')
        | Q(name__icontains='petrol')
        | Q(name__icontains='fuel')
        | Q(name__icontains='motor')
        | Q(account_category='fixed_vehicles')
    )
    roots = list(Account.objects.filter(is_active=True, account_type=AccountType.EXPENSE).filter(fleet_q))
    return _account_ids_with_descendants(roots)


def _posted_invoice_revenue(start_date: date, end_date: date) -> Decimal:
    """GL income for period (primary); falls back to posted invoice subtotals if no GL activity."""
    gl_total = _gl_income_total(start_date, end_date)
    if gl_total:
        return gl_total
    from apps.sales.models import Invoice

    agg = (
        Invoice.objects.filter(is_active=True)
        .exclude(status__in=('draft', 'cancelled'))
        .filter(journal_entry__isnull=False)
        .filter(invoice_date__gte=start_date, invoice_date__lte=end_date)
        .aggregate(total=Coalesce(Sum('subtotal'), ZERO))
    )
    return _money(agg['total'])


def _expense_total(start_date: date, end_date: date) -> Decimal:
    return _sum_pl_accounts(_all_expense_account_ids(), start_date, end_date, income=False)


def _build_cash_bank_section(as_of_date: date) -> dict:
    rows = []
    bank_gl_ids: set[int] = set()

    for bank in BankAccount.objects.filter(is_active=True).select_related('gl_account').order_by('name'):
        bank_gl_ids.add(bank.gl_account_id)
        rows.append(
            {
                'label': f'{bank.name} ({bank.gl_account.code})',
                'balance': _account_balance_as_of(bank.gl_account, as_of_date),
                'kind': 'bank',
            }
        )

    cash_accounts = (
        Account.objects.filter(is_active=True, account_type=AccountType.ASSET)
        .filter(
            Q(is_cash_account=True)
            | Q(account_category=AccountCategory.CASH_BANK)
            | Q(code__in=CASH_ACCOUNT_CODES)
        )
        .exclude(id__in=bank_gl_ids)
        .exclude(
            Q(name__icontains='receivable')
            | Q(name__icontains='pdc')
            | Q(account_category=AccountCategory.TRADE_RECEIVABLES)
        )
        .order_by('code')
        .distinct()
    )

    seen_ids: set[int] = set(bank_gl_ids)
    for account in cash_accounts:
        if account.id in seen_ids:
            continue
        seen_ids.add(account.id)
        rows.append(
            {
                'label': f'{account.code} — {account.name}',
                'balance': _account_balance_as_of(account, as_of_date),
                'kind': 'cash',
            }
        )

    fuel_accounts = (
        Account.objects.filter(is_active=True, account_type=AccountType.ASSET)
        .filter(Q(name__icontains='petrol') | Q(name__icontains='fuel') | Q(name__icontains='chip'))
        .exclude(id__in=seen_ids)
        .order_by('code')
    )
    for account in fuel_accounts:
        rows.append(
            {
                'label': account.name,
                'balance': _account_balance_as_of(account, as_of_date),
                'kind': 'fuel',
            }
        )

    pdc_payment = ZERO
    pdc_receipt = ZERO
    try:
        from apps.advances.models import SecurityChequeOutward

        pdc_payment = _money(
            SecurityChequeOutward.objects.filter(is_active=True, status='issued').aggregate(
                s=Coalesce(Sum('amount'), ZERO)
            )['s']
        )
    except Exception:
        pass

    try:
        from apps.property.models import PDCCheque

        pdc_receipt = _money(
            PDCCheque.objects.filter(is_active=True, status='received').aggregate(
                s=Coalesce(Sum('amount'), ZERO)
            )['s']
        )
    except Exception:
        pass

    rows.append({'label': 'PDC Payment', 'balance': pdc_payment, 'kind': 'pdc'})
    rows.append({'label': 'PDC Receipt', 'balance': pdc_receipt, 'kind': 'pdc'})

    return {'rows': rows, 'total': _money(sum((r['balance'] for r in rows), ZERO))}


def _build_revenue_expense_kpis(today: date) -> tuple[dict, dict]:
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    month_start = today.replace(day=1)
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])

    revenue = {
        'daily': _gl_income_total(today, today),
        'weekly': _gl_income_total(week_start, week_end),
        'monthly': _gl_income_total(month_start, month_end),
    }
    expense = {
        'daily': _expense_total(today, today),
        'weekly': _expense_total(week_start, week_end),
        'monthly': _expense_total(month_start, month_end),
    }
    return revenue, expense


def _build_ap_top_vendors(limit: int = 5) -> list[dict]:
    from apps.purchase.models import VendorBill

    bills = (
        VendorBill.objects.filter(is_active=True)
        .exclude(status__in=('draft', 'paid'))
        .annotate(balance_due=F('total_amount') - F('paid_amount'))
        .filter(balance_due__gt=0)
        .values('vendor_id', 'vendor__name')
        .annotate(outstanding=Sum('balance_due'))
        .order_by('-outstanding')[:limit]
    )
    return [
        {'vendor_id': row['vendor_id'], 'name': row['vendor__name'], 'outstanding': _money(row['outstanding'])}
        for row in bills
    ]


def _months_in_fiscal_year(fy: FiscalYear) -> list[tuple[int, int, str]]:
    months = []
    cursor = fy.start_date.replace(day=1)
    while cursor <= fy.end_date:
        months.append((cursor.year, cursor.month, MONTH_LABELS[cursor.month - 1]))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    while len(months) < 12:
        if not months:
            break
        y, m, _ = months[-1]
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        if date(y, m, 1) > fy.end_date:
            break
        months.append((y, m, MONTH_LABELS[m - 1]))
    return months[:12]


def _last_n_calendar_months(end: date, n: int = 12) -> list[tuple[int, int, str]]:
    months = []
    y, m = end.year, end.month
    for _ in range(n):
        months.append((y, m, MONTH_LABELS[m - 1]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()
    return months


def _monthly_net_profit(year: int, month: int) -> Decimal:
    start, end = _month_bounds(year, month)
    income = _gl_income_total(start, end)
    expense = _sum_pl_accounts(_all_expense_account_ids(), start, end, income=False)
    return _money(income - expense)


def _monthly_fleet_expense(year: int, month: int) -> Decimal:
    start, end = _month_bounds(year, month)
    fleet_ids = _fleet_expense_account_ids()
    return _sum_pl_accounts(fleet_ids, start, end, income=False)


def _monthly_pl_row(year: int, month: int) -> dict:
    start, end = _month_bounds(year, month)
    cogs_ids = _cogs_account_ids()
    overhead_ids = _overhead_account_ids(cogs_ids)

    invoice_value = _gl_income_total(start, end)
    cogs = _sum_pl_accounts(cogs_ids, start, end, income=False) if cogs_ids else ZERO
    gp = _money(invoice_value - cogs)
    gp_pct = _money(gp / invoice_value * Decimal('100')) if invoice_value else ZERO

    overhead = _sum_pl_accounts(overhead_ids, start, end, income=False) if overhead_ids else ZERO
    np = _money(gp - overhead)
    np_pct = _money(np / invoice_value * Decimal('100')) if invoice_value else ZERO

    return {
        'label': MONTH_LABELS[month - 1],
        'year': year,
        'month': month,
        'invoice_value': invoice_value,
        'cogs': cogs,
        'gp': gp,
        'gp_pct': gp_pct,
        'overhead': overhead,
        'np': np,
        'np_pct': np_pct,
    }


def _budget_vs_actual_monthly(fy: FiscalYear) -> tuple[list[dict], Budget | None]:
    base_qs = Budget.objects.filter(is_active=True, fiscal_year=fy, status__in=('approved', 'locked'))
    budget = base_qs.filter(name__icontains='operating').order_by('-created_at').first()
    if not budget:
        budget = base_qs.annotate(line_count=Count('lines')).order_by('-line_count', '-created_at').first()
    rows = []
    if not budget:
        for i in range(12):
            rows.append({'label': MONTH_LABELS[i], 'estimated': ZERO, 'actual': ZERO, 'variation': ZERO})
        return rows, None

    account_ids = list(budget.lines.values_list('account_id', flat=True))
    actuals_by_account: dict[int, list[Decimal]] = {}
    if account_ids:
        gl_rows = (
            JournalEntryLine.objects.filter(
                journal_entry__status='posted',
                journal_entry__date__gte=fy.start_date,
                journal_entry__date__lte=fy.end_date,
                account_id__in=account_ids,
            )
            .annotate(month=ExtractMonth('journal_entry__date'))
            .values('account_id', 'month')
            .annotate(
                total_debit=Coalesce(Sum('debit'), ZERO),
                total_credit=Coalesce(Sum('credit'), ZERO),
            )
        )
        for row in gl_rows:
            acct_id = row['account_id']
            m = row['month']
            net = abs(row['total_debit'] - row['total_credit'])
            actuals_by_account.setdefault(acct_id, [ZERO] * 12)
            if 1 <= m <= 12:
                actuals_by_account[acct_id][m - 1] = _money(net)

    monthly_estimated = [ZERO] * 12
    monthly_actual = [ZERO] * 12
    for line in budget.lines.all():
        budget_months = [_money(getattr(line, f)) for f in MONTH_FIELDS]
        actual_months = actuals_by_account.get(line.account_id, [ZERO] * 12)
        for i in range(12):
            monthly_estimated[i] += budget_months[i]
            monthly_actual[i] += actual_months[i]

    for i in range(12):
        est = _money(monthly_estimated[i])
        act = _money(monthly_actual[i])
        rows.append(
            {
                'label': MONTH_LABELS[i],
                'estimated': est,
                'actual': act,
                'variation': _money(act - est),
            }
        )
    return rows, budget


def build_accounting_dashboard_context(params) -> dict:
    today = timezone.localdate()
    fy = resolve_fiscal_year(params.get('fiscal_year'))
    as_of_date = today

    revenue_kpi, expense_kpi = _build_revenue_expense_kpis(today)
    cash_bank = _build_cash_bank_section(as_of_date)
    ar_aging = _compute_ar_aging_totals(as_of_date)
    ap_vendors = _build_ap_top_vendors()

    chart_months = _last_n_calendar_months(today, 12)
    operational_profit = [
        {'label': f"{lbl} {str(year)[2:]}", 'value': float(_monthly_net_profit(year, month))}
        for year, month, lbl in chart_months
    ]
    fleet_expense = [
        {'label': f"{lbl} {str(year)[2:]}", 'value': float(_monthly_fleet_expense(year, month))}
        for year, month, lbl in chart_months
    ]

    pl_rows = []
    budget_rows = []
    selected_budget = None
    if fy:
        fy_months = _months_in_fiscal_year(fy)
        for year, month, lbl in fy_months:
            row = _monthly_pl_row(year, month)
            row['label'] = f'{lbl} {year}'
            pl_rows.append(row)
        while len(pl_rows) < 12:
            pl_rows.append(
                {
                    'label': MONTH_LABELS[len(pl_rows)],
                    'invoice_value': ZERO,
                    'cogs': ZERO,
                    'gp': ZERO,
                    'gp_pct': ZERO,
                    'overhead': ZERO,
                    'np': ZERO,
                    'np_pct': ZERO,
                }
            )
        budget_rows, selected_budget = _budget_vs_actual_monthly(fy)
    else:
        pl_rows = [
            {
                'label': MONTH_LABELS[i],
                'invoice_value': ZERO,
                'cogs': ZERO,
                'gp': ZERO,
                'gp_pct': ZERO,
                'overhead': ZERO,
                'np': ZERO,
                'np_pct': ZERO,
            }
            for i in range(12)
        ]
        budget_rows = [
            {'label': MONTH_LABELS[i], 'estimated': ZERO, 'actual': ZERO, 'variation': ZERO} for i in range(12)
        ]

    fiscal_years = list(FiscalYear.objects.filter(is_active=True).order_by('-start_date'))

    return {
        'today': today,
        'as_of_date': as_of_date,
        'fiscal_year': fy,
        'fiscal_years': fiscal_years,
        'selected_budget': selected_budget,
        'cash_bank': cash_bank,
        'revenue_kpi': revenue_kpi,
        'expense_kpi': expense_kpi,
        'ar_aging': ar_aging,
        'ap_vendors': ap_vendors,
        'operational_profit_chart_json': json.dumps(operational_profit),
        'fleet_expense_chart_json': json.dumps(fleet_expense),
        'pl_rows': pl_rows,
        'budget_rows': budget_rows,
        'budget_available': selected_budget is not None,
    }
