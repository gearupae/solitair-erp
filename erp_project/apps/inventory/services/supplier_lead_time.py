"""Supplier lead-time intelligence from PO receipt history."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F
from django.db.models.functions import Coalesce

from apps.purchase.models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderReceiptLine


def _lead_time_rows_for_item(item_id: int) -> list[int]:
    deltas = []
    lines = (
        PurchaseOrderReceiptLine.objects.filter(
            purchase_order_item__inventory_item_id=item_id,
        )
        .select_related('receipt__purchase_order')[:80]
    )
    for ln in lines:
        po = ln.receipt.purchase_order
        if po and po.order_date and ln.receipt.received_on:
            deltas.append((ln.receipt.received_on - po.order_date).days)
    return deltas


def effective_lead_time_days(item) -> tuple[int, str]:
    """
    Return (days, source) — learned from PO history or item default.
    """
    deltas = _lead_time_rows_for_item(item.pk)
    if deltas:
        avg = max(1, int(sum(deltas) / len(deltas)))
        return avg, 'learned'
    static = int(item.lead_time_days or 7)
    return max(1, static), 'static'


def build_supplier_lead_time_report(*, rising_only=False) -> dict:
    """Per-vendor avg lead time with trend (recent 90d vs prior 90d)."""
    today = date.today()
    recent_start = today - timedelta(days=90)
    prior_start = today - timedelta(days=180)

    rows = []
    pos = (
        PurchaseOrder.objects.filter(
            is_active=True,
            status__in=['confirmed', 'partial_received', 'received'],
        )
        .select_related('vendor')
        .prefetch_related('goods_receipts')
    )

    vendor_stats: dict[int, dict] = {}
    for po in pos:
        if not po.vendor_id or not po.order_date:
            continue
        vid = po.vendor_id
        bucket = vendor_stats.setdefault(
            vid,
            {
                'vendor_name': po.vendor.name,
                'recent': [],
                'prior': [],
                'all': [],
            },
        )
        for receipt in po.goods_receipts.all():
            if not receipt.received_on:
                continue
            delta = (receipt.received_on - po.order_date).days
            if delta < 0:
                continue
            bucket['all'].append(delta)
            if receipt.received_on >= recent_start:
                bucket['recent'].append(delta)
            elif receipt.received_on >= prior_start:
                bucket['prior'].append(delta)

    for vid, st in vendor_stats.items():
        if not st['all']:
            continue
        avg_all = int(sum(st['all']) / len(st['all']))
        avg_recent = int(sum(st['recent']) / len(st['recent'])) if st['recent'] else avg_all
        avg_prior = int(sum(st['prior']) / len(st['prior'])) if st['prior'] else avg_all
        rising = avg_recent > avg_prior + 2 if st['prior'] and st['recent'] else False
        if rising_only and not rising:
            continue
        rows.append(
            {
                'vendor': st['vendor_name'],
                'avg_lead_days': avg_all,
                'recent_avg_days': avg_recent,
                'prior_avg_days': avg_prior if st['prior'] else None,
                'po_count': len(st['all']),
                'trend': 'Rising' if rising else 'Stable',
                'trend_class': 'fc-trend-down' if rising else 'fc-trend-stable',
                'flag': rising,
            }
        )

    rows.sort(key=lambda r: (-int(r['flag']), -r['avg_lead_days']))
    return {
        'title': 'Supplier Lead-Time Intelligence',
        'columns': [
            {'key': 'vendor', 'label': 'Supplier'},
            {'key': 'avg_lead_days', 'label': 'Avg Lead (days)'},
            {'key': 'recent_avg_days', 'label': 'Recent 90d'},
            {'key': 'prior_avg_days', 'label': 'Prior 90d'},
            {'key': 'po_count', 'label': 'Receipts'},
            {'key': 'trend', 'label': 'Trend'},
        ],
        'rows': rows,
        'summary': {
            'vendor_count': len(rows),
            'rising_count': sum(1 for r in rows if r['flag']),
        },
    }
