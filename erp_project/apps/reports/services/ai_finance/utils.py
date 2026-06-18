"""Data aggregation helpers for AI Finance reports."""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.finance.models import JournalEntryLine, Payment
from apps.purchase.models import ExpenseClaim, VendorBill
from apps.sales.models import Invoice


def today() -> date:
    return timezone.localdate()


def history_start(months: int = 12) -> date:
    end = today()
    y, m = end.year, end.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def month_add(y: int, m: int, delta: int) -> tuple[int, int]:
    m += delta
    while m > 12:
        m -= 12
        y += 1
    while m <= 0:
        m += 12
        y -= 1
    return y, m


def month_range_keys(start: date, end: date) -> list[str]:
    keys = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        keys.append(f'{y:04d}-{m:02d}')
        m += 1
        if m > 12:
            m = 1
            y += 1
    return keys


def next_month_keys(count: int, after: date | None = None) -> list[str]:
    ref = after or today()
    y, m = ref.year, ref.month
    m += 1
    if m > 12:
        m = 1
        y += 1
    keys = []
    for _ in range(count):
        keys.append(f'{y:04d}-{m:02d}')
        y, m = month_add(y, m, 1)
    return keys


def _decimal_sum(v) -> float:
    if v is None:
        return 0.0
    return float(Decimal(str(v)).quantize(Decimal('0.01')))


def payment_cash_flow_monthly(months: int = 12) -> list[dict]:
    """Monthly cash inflows (received) and outflows (made) from confirmed payments."""
    start = history_start(months)
    end = today()
    keys = month_range_keys(start, end)
    in_map = {k: 0.0 for k in keys}
    out_map = {k: 0.0 for k in keys}

    qs = Payment.objects.filter(
        is_active=True,
        status__in=['confirmed', 'reconciled'],
        payment_date__gte=start,
        payment_date__lte=end,
    )
    for row in qs.values('payment_date', 'payment_type').annotate(total=Sum('amount')):
        key = row['payment_date'].strftime('%Y-%m')
        if key not in in_map:
            continue
        amt = _decimal_sum(row['total'])
        if row['payment_type'] == 'received':
            in_map[key] += amt
        else:
            out_map[key] += amt

    balance = 0.0
    series = []
    for key in keys:
        inflow = in_map[key]
        outflow = out_map[key]
        net = inflow - outflow
        balance += net
        series.append({
            'month': key,
            'inflow': round(inflow, 2),
            'outflow': round(outflow, 2),
            'net': round(net, 2),
            'closing_balance': round(balance, 2),
            'actual': True,
        })
    return series


def invoice_revenue_monthly(months: int = 12) -> list[dict]:
    start = history_start(months)
    end = today()
    keys = month_range_keys(start, end)
    rev_map = {k: 0.0 for k in keys}

    qs = Invoice.objects.filter(
        is_active=True,
        status__in=['posted', 'sent', 'paid', 'partial', 'overdue'],
        invoice_date__gte=start,
        invoice_date__lte=end,
    )
    for row in qs.annotate(m=TruncMonth('invoice_date')).values('m').annotate(total=Sum('total_amount')):
        key = row['m'].strftime('%Y-%m')
        if key in rev_map:
            rev_map[key] = _decimal_sum(row['total'])

    return [{'month': k, 'value': round(rev_map[k], 2), 'actual': True} for k in keys]


def expense_by_category_monthly(months: int = 12) -> tuple[list[str], dict[str, dict[str, float]]]:
    """Vendor bills grouped by vendor name as category proxy."""
    start = history_start(months)
    end = today()
    keys = month_range_keys(start, end)
    cat_data: dict[str, dict[str, float]] = defaultdict(lambda: {k: 0.0 for k in keys})

    bills = (
        VendorBill.objects.filter(
            is_active=True,
            status__in=['posted', 'paid', 'partial', 'overdue', 'pending'],
            bill_date__gte=start,
            bill_date__lte=end,
        )
        .select_related('vendor')
    )
    for bill in bills:
        key = bill.bill_date.strftime('%Y-%m')
        if key not in keys:
            continue
        cat = (bill.vendor.name if bill.vendor_id else 'Other')[:80]
        cat_data[cat][key] += _decimal_sum(bill.total_amount)

    claims = ExpenseClaim.objects.filter(
        is_active=True,
        status__in=['approved', 'paid'],
        claim_date__gte=start,
        claim_date__lte=end,
    )
    for row in claims.annotate(m=TruncMonth('claim_date')).values('m').annotate(total=Sum('total_amount')):
        key = row['m'].strftime('%Y-%m')
        if key in keys:
            cat_data['Expense claims'][key] += _decimal_sum(row['total'])

    categories = sorted(cat_data.keys())[:12]
    return keys, {c: cat_data[c] for c in categories}


def open_invoices_for_collection() -> list[dict]:
    qs = (
        Invoice.objects.filter(
            is_active=True,
            status__in=['posted', 'sent', 'partial', 'overdue'],
        )
        .select_related('customer')
        .order_by('due_date')
    )
    rows = []
    for inv in qs:
        balance = _decimal_sum(inv.balance)
        if balance <= 0:
            continue
        rows.append({
            'invoice_id': inv.pk,
            'invoice_number': inv.invoice_number,
            'customer': inv.customer.name if inv.customer_id else '',
            'customer_id': inv.customer_id,
            'invoice_date': inv.invoice_date.isoformat(),
            'due_date': inv.due_date.isoformat(),
            'amount': balance,
            'days_overdue': max(0, (today() - inv.due_date).days),
        })
    return rows


def customer_avg_days_to_pay() -> dict[int, float]:
    """Historical average days from invoice date to last payment for paid invoices."""
    paid = Invoice.objects.filter(
        is_active=True,
        status='paid',
        paid_amount__gt=0,
    ).select_related('customer')
    buckets: dict[int, list[int]] = defaultdict(list)
    for inv in paid:
        if not inv.customer_id:
            continue
        days = max(0, (inv.due_date - inv.invoice_date).days + 30)
        buckets[inv.customer_id].append(days)
    return {
        cid: sum(vals) / len(vals)
        for cid, vals in buckets.items()
        if vals
    }


def recent_transactions_for_anomaly(days: int = 90) -> list[dict]:
    start = today() - timedelta(days=days)
    rows = []

    for pay in Payment.objects.filter(
        is_active=True,
        status__in=['confirmed', 'reconciled'],
        payment_date__gte=start,
    ).order_by('-payment_date')[:200]:
        rows.append({
            'type': 'payment',
            'date': pay.payment_date.isoformat(),
            'reference': pay.payment_number,
            'party': pay.party_name,
            'amount': _decimal_sum(pay.amount),
            'direction': pay.payment_type,
        })

    for bill in VendorBill.objects.filter(
        is_active=True,
        status__in=['posted', 'paid', 'partial'],
        bill_date__gte=start,
    ).select_related('vendor').order_by('-bill_date')[:150]:
        rows.append({
            'type': 'vendor_bill',
            'date': bill.bill_date.isoformat(),
            'reference': bill.bill_number,
            'party': bill.vendor.name if bill.vendor_id else '',
            'amount': _decimal_sum(bill.total_amount),
            'direction': 'outflow',
        })

    for line in (
        JournalEntryLine.objects.filter(
            journal_entry__date__gte=start,
            journal_entry__status='posted',
        )
        .select_related('account', 'journal_entry')
        .order_by('-journal_entry__date')[:100]
    ):
        amt = _decimal_sum(line.debit or line.credit)
        if amt < 1000:
            continue
        rows.append({
            'type': 'journal',
            'date': line.journal_entry.date.isoformat(),
            'reference': line.journal_entry.entry_number,
            'party': line.account.name if line.account_id else '',
            'amount': amt,
            'direction': 'debit' if line.debit else 'credit',
        })

    return rows[:250]
