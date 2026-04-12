"""
Consumables / inventory report data builders (JSON-friendly structures for UI + exports).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from dateutil.relativedelta import relativedelta
from django.db.models import (
    Case,
    Count,
    DecimalField,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.inventory.models import Item, StockMovement
from apps.settings_app.models import CompanySettings


def signed_qty_case():
    return Case(
        When(movement_type='in', then=F('quantity')),
        When(movement_type='adjustment_plus', then=F('quantity')),
        When(movement_type='out', then=-F('quantity')),
        When(movement_type='adjustment_minus', then=-F('quantity')),
        When(movement_type='transfer', then=Value(Decimal('0'))),
        default=Value(Decimal('0')),
        output_field=DecimalField(max_digits=24, decimal_places=6),
    )


def _opening_map(date_from) -> dict[int, Decimal]:
    qs = (
        StockMovement.objects.filter(movement_date__lt=date_from, item__is_active=True, item__item_type='product')
        .values('item_id')
        .annotate(o=Coalesce(Sum(signed_qty_case()), Value(Decimal('0')), output_field=DecimalField(max_digits=24, decimal_places=6)))
    )
    return {r['item_id']: (r['o'] or Decimal('0')).quantize(Decimal('0.01')) for r in qs}


def _period_received_map(date_from, date_to) -> dict[int, Decimal]:
    qs = (
        StockMovement.objects.filter(
            movement_date__gte=date_from,
            movement_date__lte=date_to,
            movement_type__in=['in', 'adjustment_plus'],
            item__is_active=True,
            item__item_type='product',
        )
        .values('item_id')
        .annotate(r=Coalesce(Sum('quantity'), Value(Decimal('0')), output_field=DecimalField(max_digits=24, decimal_places=6)))
    )
    return {r['item_id']: (r['r'] or Decimal('0')).quantize(Decimal('0.01')) for r in qs}


def _period_issued_map(date_from, date_to) -> dict[int, Decimal]:
    qs = (
        StockMovement.objects.filter(
            movement_date__gte=date_from,
            movement_date__lte=date_to,
            movement_type__in=['out', 'adjustment_minus'],
            item__is_active=True,
            item__item_type='product',
        )
        .values('item_id')
        .annotate(r=Coalesce(Sum('quantity'), Value(Decimal('0')), output_field=DecimalField(max_digits=24, decimal_places=6)))
    )
    return {r['item_id']: (r['r'] or Decimal('0')).quantize(Decimal('0.01')) for r in qs}


def _unit_cost(item: Item) -> Decimal:
    if item.purchase_price and item.purchase_price > 0:
        return item.purchase_price.quantize(Decimal('0.01'))
    agg = StockMovement.objects.filter(item=item, movement_type='in', quantity__gt=0).aggregate(
        t=Sum('total_cost'), q=Sum('quantity')
    )
    t, q = agg['t'], agg['q']
    if t and q and q > 0:
        return (t / q).quantize(Decimal('0.01'))
    return Decimal('0.00')


def _stock_status(closing: Decimal, minimum: Decimal) -> tuple[str, str]:
    minimum = minimum or Decimal('0')
    if closing < minimum:
        return 'Low', 'danger'
    if minimum > 0 and closing > minimum * Decimal('3'):
        return 'Excess', 'warning'
    if minimum == 0 and closing > Decimal('500'):
        return 'Excess', 'warning'
    return 'OK', 'success'


def _item_base_qs():
    """Same scope as consumable dashboard / request forms: active stock items only."""
    return Item.objects.filter(
        is_active=True,
        item_type='product',
        status='active',
    ).select_related('category', 'storage_location_master')


def report_stock_summary(date_from: date, date_to: date) -> dict[str, Any]:
    opening_m = _opening_map(date_from)
    recv_m = _period_received_map(date_from, date_to)
    iss_m = _period_issued_map(date_from, date_to)
    rows = []
    for item in _item_base_qs().order_by('name'):
        oid = item.id
        opening = opening_m.get(oid, Decimal('0'))
        received = recv_m.get(oid, Decimal('0'))
        issued = iss_m.get(oid, Decimal('0'))
        closing = (opening + received - issued).quantize(Decimal('0.01'))
        status, status_key = _stock_status(closing, item.minimum_stock)
        rows.append(
            {
                'item_id': item.id,
                'item_name': item.name,
                'category': item.category.name if item.category_id else '',
                'unit': item.unit,
                'barcode': item.barcode or '',
                'location': item.get_storage_shelf_label(),
                'opening': float(opening),
                'received': float(received),
                'issued': float(issued),
                'closing': float(closing),
                'minimum': float(item.minimum_stock or 0),
                'status': status,
                'status_key': status_key,
            }
        )
    return {
        'report': 'stock_summary',
        'title': 'Stock Summary Report',
        'columns': [
            {'key': 'item_name', 'label': 'Item Name'},
            {'key': 'category', 'label': 'Category'},
            {'key': 'location', 'label': 'Location / Shelf'},
            {'key': 'barcode', 'label': 'Barcode / Asset Code'},
            {'key': 'unit', 'label': 'Unit'},
            {'key': 'opening', 'label': 'Opening Stock', 'format': 'number'},
            {'key': 'received', 'label': 'Received', 'format': 'number'},
            {'key': 'issued', 'label': 'Issued', 'format': 'number'},
            {'key': 'closing', 'label': 'Closing Stock', 'format': 'number'},
            {'key': 'minimum', 'label': 'Min Level', 'format': 'number'},
            {'key': 'status', 'label': 'Status'},
        ],
        'rows': rows,
    }


def report_stock_balance(date_from: date, date_to: date) -> dict[str, Any]:
    base = report_stock_summary(date_from, date_to)
    rows = []
    for r in base['rows']:
        rows.append(
            {
                'item_id': r['item_id'],
                'item_name': r['item_name'],
                'category': r['category'],
                'location': r['location'],
                'opening': r['opening'],
                'received': r['received'],
                'issued': r['issued'],
                'closing': r['closing'],
                'unit': r['unit'],
                'barcode': r['barcode'],
            }
        )
    return {
        'report': 'stock_balance',
        'title': 'Stock Balance Report',
        'columns': [
            {'key': 'item_name', 'label': 'Item Name'},
            {'key': 'category', 'label': 'Category'},
            {'key': 'location', 'label': 'Location / Shelf'},
            {'key': 'barcode', 'label': 'Barcode / Asset Code'},
            {'key': 'opening', 'label': 'Opening Balance', 'format': 'number'},
            {'key': 'received', 'label': 'Total In', 'format': 'number'},
            {'key': 'issued', 'label': 'Total Out', 'format': 'number'},
            {'key': 'closing', 'label': 'Closing Balance', 'format': 'number'},
            {'key': 'unit', 'label': 'Unit'},
        ],
        'rows': rows,
    }


def report_inventory_valuation(date_from: date, date_to: date) -> dict[str, Any]:
    cs = CompanySettings.get_settings()
    method_label = cs.get_inventory_valuation_method_display()
    summary = report_stock_summary(date_from, date_to)
    rows = []
    grand = Decimal('0')
    for r in summary['rows']:
        item = Item.objects.filter(pk=r['item_id']).first()
        if not item:
            continue
        uc = _unit_cost(item)
        closing = Decimal(str(r['closing']))
        total_val = (closing * uc).quantize(Decimal('0.01'))
        grand += total_val
        rows.append(
            {
                'item_id': r['item_id'],
                'item_name': r['item_name'],
                'category': r['category'],
                'unit': r['unit'],
                'barcode': r['barcode'],
                'location': r['location'],
                'qty': float(closing),
                'unit_cost': float(uc),
                'total_value': float(total_val),
                'last_updated': item.updated_at.date().isoformat() if item.updated_at else '',
            }
        )
    return {
        'report': 'inventory_valuation',
        'title': 'Inventory Valuation Report',
        'valuation_method': method_label,
        'columns': [
            {'key': 'item_name', 'label': 'Item Name'},
            {'key': 'category', 'label': 'Category'},
            {'key': 'location', 'label': 'Location / Shelf'},
            {'key': 'barcode', 'label': 'Barcode / Asset Code'},
            {'key': 'unit', 'label': 'Unit'},
            {'key': 'qty', 'label': 'Qty in Hand', 'format': 'number'},
            {'key': 'unit_cost', 'label': 'Unit Cost', 'format': 'money'},
            {'key': 'total_value', 'label': 'Total Value', 'format': 'money'},
            {'key': 'last_updated', 'label': 'Last Updated'},
        ],
        'rows': rows,
        'footer': {'grand_total_value': float(grand), 'valuation_method': method_label},
    }


def report_warranty(date_from: date, date_to: date, warranty_filter: str) -> dict[str, Any]:
    del date_from, date_to  # filter is snapshot-oriented; period still shown in header
    today = timezone.localdate()
    qs = _item_base_qs()
    rows = []
    for item in qs.order_by('name'):
        exp = item.warranty_expiry
        if not exp:
            if warranty_filter != 'all':
                continue
            rows.append(
                {
                    'item_name': item.name,
                    'brand': item.brand or '',
                    'serial_batch': item.serial_batch_number or '',
                    'purchase_date': item.purchase_date.isoformat() if item.purchase_date else '',
                    'warranty_expiry': '',
                    'days_remaining': '',
                    'status': 'N/A',
                    'status_key': 'secondary',
                    'barcode': item.barcode or '',
                    'location': item.get_storage_shelf_label(),
                }
            )
            continue
        days_left = (exp - today).days
        if days_left < 0:
            status, sk = 'Expired', 'danger'
        elif days_left < 30:
            status, sk = 'Expiring Soon', 'warning'
        else:
            status, sk = 'Active', 'success'
        if warranty_filter == 'expired' and status != 'Expired':
            continue
        if warranty_filter == 'expiring_soon' and status != 'Expiring Soon':
            continue
        rows.append(
            {
                'item_name': item.name,
                'brand': item.brand or '',
                'serial_batch': item.serial_batch_number or '',
                'purchase_date': item.purchase_date.isoformat() if item.purchase_date else '',
                'warranty_expiry': exp.isoformat(),
                'days_remaining': days_left,
                'status': status,
                'status_key': sk,
                'barcode': item.barcode or '',
                'location': item.get_storage_shelf_label(),
            }
        )
    return {
        'report': 'warranty',
        'title': 'Warranty Period Report',
        'columns': [
            {'key': 'item_name', 'label': 'Item Name'},
            {'key': 'brand', 'label': 'Brand'},
            {'key': 'location', 'label': 'Location / Shelf'},
            {'key': 'barcode', 'label': 'Barcode / Asset Code'},
            {'key': 'serial_batch', 'label': 'Serial / Batch No'},
            {'key': 'purchase_date', 'label': 'Purchase Date'},
            {'key': 'warranty_expiry', 'label': 'Warranty Expiry'},
            {'key': 'days_remaining', 'label': 'Days Remaining', 'format': 'number'},
            {'key': 'status', 'label': 'Status'},
        ],
        'rows': rows,
    }


def _movement_type_label(m: StockMovement) -> str:
    if m.movement_type == 'in':
        return 'Returned' if m.source == 'return' else 'Received'
    if m.movement_type == 'out':
        return 'Issued'
    if m.movement_type == 'adjustment_plus':
        return 'Adjusted (+)'
    if m.movement_type == 'adjustment_minus':
        return 'Adjusted (-)'
    if m.movement_type == 'transfer':
        return 'Transfer'
    return m.get_movement_type_display()


def report_stock_movement(date_from: date, date_to: date, group_by: str) -> dict[str, Any]:
    qs = (
        StockMovement.objects.filter(
            movement_date__gte=date_from,
            movement_date__lte=date_to,
            item__is_active=True,
            item__item_type='product',
        )
        .select_related('item', 'item__category', 'item__storage_location_master', 'created_by')
        .order_by('movement_date', 'id')
    )
    raw_rows = []
    for m in qs:
        user = m.created_by
        moved_by = user.get_full_name().strip() if user and user.get_full_name() else (user.username if user else '')
        raw_rows.append(
            {
                'date': m.movement_date.isoformat(),
                'item_name': m.item.name,
                'barcode': m.item.barcode or '',
                'location': m.item.get_storage_shelf_label(),
                'type': _movement_type_label(m),
                'quantity': float(abs(m.quantity)),
                'reference': m.reference or '',
                'moved_by': moved_by,
                'remarks': m.notes or '',
            }
        )
    rows = raw_rows
    if group_by == 'item':
        buckets: dict[str, list] = defaultdict(list)
        for r in raw_rows:
            buckets[r['item_name']].append(r)
        rows = []
        for item_name in sorted(buckets.keys()):
            for r in buckets[item_name]:
                rows.append(r)
    elif group_by == 'date':
        buckets = defaultdict(list)
        for r in raw_rows:
            buckets[r['date']].append(r)
        rows = []
        for d in sorted(buckets.keys()):
            for r in buckets[d]:
                rows.append(r)
    return {
        'report': 'stock_movement',
        'title': 'Stock Movement Report',
        'columns': [
            {'key': 'date', 'label': 'Date'},
            {'key': 'item_name', 'label': 'Item Name'},
            {'key': 'location', 'label': 'Location / Shelf'},
            {'key': 'barcode', 'label': 'Barcode / Asset Code'},
            {'key': 'type', 'label': 'Transaction Type'},
            {'key': 'quantity', 'label': 'Quantity', 'format': 'number'},
            {'key': 'reference', 'label': 'Reference No'},
            {'key': 'moved_by', 'label': 'Moved By'},
            {'key': 'remarks', 'label': 'Remarks'},
        ],
        'rows': rows,
    }


def report_inventory_analytics(date_from: date, date_to: date) -> dict[str, Any]:
    summary = report_stock_summary(date_from, date_to)
    low = ok = excess = 0
    total_value = Decimal('0')
    total_issued = Decimal('0')
    closing_sum = Decimal('0')
    items_by_id = {i.id: i for i in _item_base_qs()}
    for r in summary['rows']:
        if r['status'] == 'Low':
            low += 1
        elif r['status'] == 'Excess':
            excess += 1
        else:
            ok += 1
        item = items_by_id.get(r['item_id'])
        if item:
            uc = _unit_cost(item)
            c = Decimal(str(r['closing']))
            total_value += c * uc
            closing_sum += c
        total_issued += Decimal(str(r['issued']))

    # Monthly consumption trend (12 months ending month of date_to)
    monthly_labels = []
    monthly_qty = []
    end_month = date(date_to.year, date_to.month, 1)
    for i in range(11, -1, -1):
        ms = end_month - relativedelta(months=i)
        me = ms + relativedelta(months=1)
        q = StockMovement.objects.filter(
            movement_type='out',
            movement_date__gte=ms,
            movement_date__lt=me,
            item__item_type='product',
            item__is_active=True,
        ).aggregate(t=Coalesce(Sum('quantity'), Value(Decimal('0'))))['t'] or Decimal('0')
        monthly_labels.append(ms.strftime('%b %Y'))
        monthly_qty.append(float(q))

    # Top 10 consumed (out qty) in selected period
    top = (
        StockMovement.objects.filter(
            movement_type='out',
            movement_date__gte=date_from,
            movement_date__lte=date_to,
            item__is_active=True,
            item__item_type='product',
        )
        .values('item__name')
        .annotate(tq=Sum('quantity'))
        .order_by('-tq')[:10]
    )
    top_labels = [t['item__name'] for t in top]
    top_data = [float(t['tq'] or 0) for t in top]

    avg_turn = float(total_issued / (closing_sum or Decimal('1')))

    return {
        'report': 'inventory_analytics',
        'title': 'Inventory Analytics Report',
        'kpi': {
            'total_items': len(summary['rows']),
            'total_value': float(total_value.quantize(Decimal('0.01'))),
            'low_stock_count': low,
            'avg_turnover_rate': round(avg_turn, 4),
        },
        'charts': {
            'monthly_labels': monthly_labels,
            'monthly_qty': monthly_qty,
            'pie': {'labels': ['Low', 'OK', 'Excess'], 'data': [low, ok, excess]},
            'top_labels': top_labels,
            'top_data': top_data,
        },
        'columns': [
            {'key': 'item_name', 'label': 'Item Name'},
            {'key': 'category', 'label': 'Category'},
            {'key': 'location', 'label': 'Location / Shelf'},
            {'key': 'barcode', 'label': 'Barcode / Asset Code'},
            {'key': 'closing', 'label': 'Closing Stock', 'format': 'number'},
            {'key': 'status', 'label': 'Status'},
        ],
        'rows': [
            {
                'item_id': r['item_id'],
                'item_name': r['item_name'],
                'category': r['category'],
                'location': r['location'],
                'barcode': r['barcode'],
                'closing': r['closing'],
                'status': r['status'],
                'status_key': r['status_key'],
            }
            for r in summary['rows']
        ],
    }


REPORT_BUILDERS = {
    'stock_summary': report_stock_summary,
    'inventory_analytics': report_inventory_analytics,
    'inventory_valuation': report_inventory_valuation,
    'warranty': report_warranty,
    'stock_movement': report_stock_movement,
    'stock_balance': report_stock_balance,
}


def build_report(
    report_key: str,
    date_from: date,
    date_to: date,
    warranty_filter: str = 'all',
    movement_group: str = 'date',
) -> dict[str, Any]:
    if report_key == 'warranty':
        return REPORT_BUILDERS[report_key](date_from, date_to, warranty_filter)
    if report_key == 'stock_movement':
        return REPORT_BUILDERS[report_key](date_from, date_to, movement_group)
    return REPORT_BUILDERS[report_key](date_from, date_to)
