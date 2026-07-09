"""CEO dashboard — purchase & inventory executive sections (read-only)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse

from apps.core.visibility import filter_purchase_orders_for_user, filter_purchase_requests_for_user
from apps.inventory.models import ConsumableRequest, Item, Stock, StockMovement
from apps.purchase.models import PurchaseOrder, PurchaseRequest, VendorBill

from .ceo_executive_reports import CeoFilters, _money
from .ceo_module_reports import _flag_meta, _health_flag

OPEN_PO_STATUSES = ('draft', 'sent', 'confirmed', 'partial_received')
UNPAID_BILL_STATUSES = ('posted', 'partial', 'overdue')
PENDING_CR_STATUSES = ('draft', 'submitted', 'pending', 'partially_issued')
CEO_TABLE_LIMIT = 12


def _status_chip(label: str, value, tone: str) -> dict:
    return {'label': label, 'value': value, 'tone': tone}


def _monthly_po_series(filters: CeoFilters, po_qs) -> list[dict]:
    end = filters.date_to
    month_keys: list[tuple[int, int]] = []
    y, m = end.year, end.month
    for _ in range(6):
        month_keys.insert(0, (y, m))
        m -= 1
        if m < 1:
            m = 12
            y -= 1

    start = date(month_keys[0][0], month_keys[0][1], 1)
    rows = (
        po_qs.filter(is_active=True, order_date__gte=start, order_date__lte=end)
        .exclude(status='cancelled')
        .annotate(month=TruncMonth('order_date'))
        .values('month')
        .annotate(total=Sum('total_amount'))
    )
    by_month: dict[tuple[int, int], float] = {}
    for row in rows:
        month_val = row.get('month')
        if month_val:
            by_month[(month_val.year, month_val.month)] = float(row['total'] or 0)

    return [
        {
            'label': date(y, m, 1).strftime('%b %Y'),
            'value': by_month.get((y, m), 0.0),
        }
        for y, m in month_keys
    ]


def build_purchase_dashboard(user, filters: CeoFilters) -> dict:
    pr_qs = filter_purchase_requests_for_user(
        PurchaseRequest.objects.filter(is_active=True),
        user,
    )
    po_qs = filter_purchase_orders_for_user(
        PurchaseOrder.objects.filter(is_active=True),
        user,
    )
    bill_qs = VendorBill.objects.filter(is_active=True)

    pr_period = pr_qs.filter(date__gte=filters.date_from, date__lte=filters.date_to)
    po_period = po_qs.filter(order_date__gte=filters.date_from, order_date__lte=filters.date_to)
    bill_period = bill_qs.filter(bill_date__gte=filters.date_from, bill_date__lte=filters.date_to)

    pending_po_qs = po_qs.filter(status__in=OPEN_PO_STATUSES)
    open_po_count = pending_po_qs.count()
    open_po_value = float(_money(pending_po_qs.aggregate(t=Sum('total_amount'))['t']))

    unpaid_bills = bill_qs.filter(status__in=UNPAID_BILL_STATUSES).filter(total_amount__gt=F('paid_amount'))
    pending_bill_count = unpaid_bills.count()
    pending_bill_value = float(
        _money(unpaid_bills.aggregate(t=Sum(F('total_amount') - F('paid_amount')))['t'])
    )

    pr_pending = pr_period.filter(status='pending').count()
    pr_approved = pr_period.filter(status__in=('approved', 'converted')).count()
    pr_rejected = pr_period.filter(status='rejected').count()
    pr_returned = pr_period.filter(status='returned').count()

    bill_summary = []
    for status_key, status_label in VendorBill.STATUS_CHOICES:
        subset = bill_period.filter(status=status_key)
        cnt = subset.count()
        if not cnt:
            continue
        bill_summary.append({
            'status': status_label,
            'status_key': status_key,
            'count': cnt,
            'value': float(_money(subset.aggregate(t=Sum('total_amount'))['t'])),
        })

    monthly_po = _monthly_po_series(filters, po_qs)
    peak = max((m['value'] for m in monthly_po), default=0) or 1
    for m in monthly_po:
        m['height_pct'] = round(m['value'] / peak * 100, 1) if peak else 0

    from apps.purchase.purchase_dashboard import build_po_invoice_gaps

    all_po_invoice_gaps = build_po_invoice_gaps(po_qs, preview_limit=None)
    po_invoice_gaps = all_po_invoice_gaps[:CEO_TABLE_LIMIT]

    pending_po_rows = []
    for row in po_invoice_gaps:
        po = row['po']
        primary_bill = row['primary_bill']
        pending_po_rows.append({
            'number': po.po_number,
            'vendor': (po.vendor.name if po.vendor_id else '—')[:28],
            'project': po.project.project_code if po.project_id else '—',
            'status': po.get_status_display(),
            'fulfillment': row['fulfillment'],
            'issue_label': row['issue_label'],
            'issue': row['issue'],
            'amount': float(po.total_amount),
            'outstanding': float(row['outstanding']),
            'order_date': po.order_date,
            'link': row['link'],
            'bill_number': primary_bill.bill_number if primary_bill else '',
            'bill_link': row['bill_link'],
        })

    today = filters.date_to

    pending_bill_rows = []
    for bill in unpaid_bills.select_related('vendor', 'purchase_order').order_by('due_date')[:CEO_TABLE_LIMIT]:
        po_number = bill.purchase_order.po_number if bill.purchase_order_id else '—'
        pending_bill_rows.append({
            'number': bill.bill_number,
            'vendor': (bill.vendor.name if bill.vendor_id else '—')[:28],
            'status': bill.get_status_display(),
            'balance': float(bill.balance),
            'total': float(bill.total_amount),
            'due_date': bill.due_date,
            'is_overdue': bool(bill.due_date and bill.due_date < today),
            'po_number': po_number,
            'link': reverse('purchase:bill_detail', args=[bill.pk]),
            'po_link': (
                reverse('purchase:po_detail', args=[bill.purchase_order_id])
                if bill.purchase_order_id else ''
            ),
        })

    flag = _health_flag(
        red=pending_bill_count >= 10 and pending_bill_value > 50000,
        yellow=open_po_count >= 5 or len(all_po_invoice_gaps) >= 3 or pending_bill_count >= 3 or pr_pending >= 5,
    )

    invoice_gap_count = len(all_po_invoice_gaps)
    invoice_gap_value = float(_money(sum((row['outstanding'] for row in all_po_invoice_gaps), Decimal('0.00'))))

    return {
        'flag': flag,
        'flag_display': _flag_meta(flag, 'purchase'),
        'headline': (
            f'{open_po_count} open PO · AED {open_po_value:,.0f} · '
            f'{pending_bill_count} unpaid bills · AED {pending_bill_value:,.0f} outstanding · '
            f'{invoice_gap_count} PO(s) awaiting invoice/payment'
        ),
        'url': reverse('purchase:po_list'),
        'status_counts': [
            _status_chip('PR pending', pr_pending, 'warning'),
            _status_chip('PR approved', pr_approved, 'success'),
            _status_chip('PR rejected', pr_rejected, 'danger'),
            _status_chip('PR returned', pr_returned, 'secondary'),
        ],
        'kpis': [
            {'label': 'Open purchase orders', 'value': open_po_count, 'format': 'int', 'hint': f'AED {open_po_value:,.0f} open PO value'},
            {'label': 'Pending vendor bills', 'value': pending_bill_count, 'format': 'int', 'hint': f'AED {pending_bill_value:,.0f} balance due'},
            {'label': 'POs awaiting invoice', 'value': invoice_gap_count, 'format': 'int', 'hint': f'AED {invoice_gap_value:,.0f} outstanding'},
            {'label': 'PO value (period)', 'value': float(_money(po_period.exclude(status='cancelled').aggregate(t=Sum('total_amount'))['t'])), 'format': 'money'},
        ],
        'vendor_bill_summary': bill_summary,
        'monthly_po': monthly_po,
        'pending_po_rows': pending_po_rows,
        'pending_po_count': invoice_gap_count,
        'pending_bill_rows': pending_bill_rows,
        'pending_bill_table_count': pending_bill_count,
        'po_list_url': reverse('purchase:po_list'),
        'bill_list_url': reverse('purchase:bill_list'),
        'purchase_dashboard_url': reverse('purchase:dashboard') + '#po-invoice-gaps',
    }


def build_inventory_dashboard(user, filters: CeoFilters) -> dict:
    stock_qs = Stock.objects.filter(
        item__is_active=True,
        item__item_type='product',
        item__status='active',
        warehouse__is_active=True,
    )
    stock_agg = stock_qs.aggregate(
        total_qty=Sum('quantity'),
        total_value=Sum(
            ExpressionWrapper(
                F('quantity') * F('item__purchase_price'),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        ),
    )
    total_qty = float(stock_agg['total_qty'] or 0)
    total_value = float(stock_agg['total_value'] or 0)

    usage_qs = StockMovement.objects.filter(
        is_active=True,
        movement_type='out',
        movement_date__gte=filters.date_from,
        movement_date__lte=filters.date_to,
    )
    usage_volume = float(usage_qs.aggregate(t=Sum('quantity'))['t'] or 0)
    usage_value = float(_money(usage_qs.aggregate(t=Sum('total_cost'))['t']))

    cr_qs = ConsumableRequest.objects.filter(is_active=True)
    cr_period = cr_qs.filter(
        created_at__date__gte=filters.date_from,
        created_at__date__lte=filters.date_to,
    )
    cr_total = cr_period.count()
    cr_pending = cr_qs.filter(status__in=PENDING_CR_STATUSES).count()
    cr_approved = cr_period.filter(status='approved').count()
    cr_rejected = cr_period.filter(status='rejected').count()
    cr_issued = cr_period.filter(status__in=('issued', 'dispensed', 'partially_issued', 'closed')).count()

    low_stock = sum(
        1 for item in Item.objects.filter(is_active=True, item_type='product', status='active').iterator(chunk_size=200)
        if item.is_low_stock
    )

    flag = _health_flag(
        red=cr_pending >= 10,
        yellow=cr_pending >= 3 or low_stock >= 5,
    )

    return {
        'flag': flag,
        'flag_display': _flag_meta(flag, 'inventory'),
        'headline': (
            f'{total_qty:,.0f} units in stock · AED {total_value:,.0f} inventory value · '
            f'{cr_pending} pending requests'
        ),
        'url': reverse('inventory:item_list'),
        'status_counts': [
            _status_chip('Pending', cr_pending, 'warning'),
            _status_chip('Approved', cr_approved, 'success'),
            _status_chip('Issued', cr_issued, 'info'),
            _status_chip('Rejected', cr_rejected, 'danger'),
        ],
        'kpis': [
            {'label': 'Stock quantity', 'value': total_qty, 'format': 'qty'},
            {'label': 'Inventory value (cost)', 'value': total_value, 'format': 'money'},
            {'label': 'Usage volume (period)', 'value': usage_volume, 'format': 'qty', 'hint': 'Stock-out movements'},
            {'label': 'Usage value (period)', 'value': usage_value, 'format': 'money', 'hint': 'Stock-out at cost'},
            {'label': 'Requests (period)', 'value': cr_total, 'format': 'int'},
            {'label': 'Pending requests', 'value': cr_pending, 'format': 'int', 'alert': cr_pending > 0},
            {'label': 'Low-stock items', 'value': low_stock, 'format': 'int', 'alert': low_stock > 0},
        ],
    }
