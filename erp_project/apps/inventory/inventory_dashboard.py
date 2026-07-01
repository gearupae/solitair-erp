"""Inventory module dashboard — stock, warehouses, material requests, consumption."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Count, ExpressionWrapper, F, Sum
from django.db.models.fields import DecimalField
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import PermissionChecker
from apps.inventory.models import ConsumableRequest, Item, Stock, StockMovement, Warehouse

PREVIEW_LIMIT = 8
PENDING_MR_STATUSES = ('draft', 'submitted', 'pending', 'partially_issued')


def _money(val) -> Decimal:
    if val is None:
        return Decimal('0.00')
    return Decimal(str(val)).quantize(Decimal('0.01'))


def _material_requests_qs():
    return ConsumableRequest.objects.filter(is_active=True, request_kind='material')


def _stock_qs():
    return Stock.objects.filter(
        item__is_active=True,
        item__item_type='product',
        item__status='active',
        warehouse__is_active=True,
        warehouse__status='active',
    )


def build_inventory_dashboard_context(user, *, month: date | None = None) -> dict:
    from datetime import timedelta

    today = timezone.localdate()
    month_start = (month or today).replace(day=1)
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    month_end = min(next_month - timedelta(days=1), today)

    stock_qs = _stock_qs()
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

    items_in_stock = (
        Item.objects.filter(
            is_active=True,
            item_type='product',
            status='active',
            stock_records__quantity__gt=0,
            stock_records__warehouse__is_active=True,
        )
        .distinct()
        .count()
    )

    warehouse_count = Warehouse.objects.filter(is_active=True, status='active').count()

    material_qs = _material_requests_qs()
    pending_material = material_qs.filter(status__in=PENDING_MR_STATUSES)
    approved_material_month = material_qs.filter(
        status='approved',
        approved_date__date__gte=month_start,
        approved_date__date__lte=month_end,
    )
    approved_material_all = material_qs.filter(status='approved')

    consumption_qs = StockMovement.objects.filter(
        is_active=True,
        movement_type='out',
        movement_date__gte=month_start,
        movement_date__lte=month_end,
    )
    consumption_qty = float(consumption_qs.aggregate(t=Sum('quantity'))['t'] or 0)
    consumption_value = float(_money(consumption_qs.aggregate(t=Sum('total_cost'))['t']))

    low_stock = sum(
        1
        for item in Item.objects.filter(is_active=True, item_type='product', status='active').iterator(
            chunk_size=200
        )
        if item.is_low_stock
    )

    warehouse_rows = []
    wh_stats = (
        stock_qs.values('warehouse__name', 'warehouse__code')
        .annotate(
            item_count=Count('item', distinct=True),
            qty=Sum('quantity'),
            value=Sum(
                ExpressionWrapper(
                    F('quantity') * F('item__purchase_price'),
                    output_field=DecimalField(max_digits=20, decimal_places=2),
                )
            ),
        )
        .order_by('-qty')
    )
    max_wh_qty = max((float(r['qty'] or 0) for r in wh_stats), default=1) or 1
    for row in wh_stats:
        qty = float(row['qty'] or 0)
        warehouse_rows.append({
            'name': row['warehouse__name'],
            'code': row['warehouse__code'] or '—',
            'items': row['item_count'],
            'qty': qty,
            'value': float(row['value'] or 0),
            'height_pct': round(qty / max_wh_qty * 100, 1) if qty else 0,
        })

    top_consumed = list(
        consumption_qs.values('item__name', 'item__item_code')
        .annotate(qty=Sum('quantity'), value=Sum('total_cost'))
        .order_by('-qty')[:PREVIEW_LIMIT]
    )

    kpis = [
        {
            'key': 'pending_material',
            'label': 'Pending material requests',
            'value': pending_material.count(),
            'icon': 'fa-clock',
            'color': 'warning' if pending_material.exists() else 'secondary',
            'link': reverse('inventory:consumable_request_list') + '?status=pending',
            'hint': 'Awaiting approval or issue',
        },
        {
            'key': 'approved_material',
            'label': 'Approved material requests',
            'value': approved_material_month.count(),
            'icon': 'fa-check-circle',
            'color': 'success',
            'link': reverse('inventory:consumable_request_list') + '?status=approved',
            'hint': f'{month_start.strftime("%B %Y")} · {approved_material_all.count()} total open',
        },
        {
            'key': 'items_in_stock',
            'label': 'Items in stock',
            'value': items_in_stock,
            'icon': 'fa-cubes',
            'color': 'primary',
            'link': reverse('inventory:item_list'),
            'hint': f'{total_qty:,.0f} units across warehouses',
        },
        {
            'key': 'inventory_value',
            'label': 'Total inventory value',
            'value': f'AED {total_value:,.0f}',
            'icon': 'fa-coins',
            'color': 'info',
            'link': reverse('inventory:fifo_valuation_report'),
            'hint': 'At purchase cost',
            'is_text': True,
        },
        {
            'key': 'warehouses',
            'label': 'Active warehouses',
            'value': warehouse_count,
            'icon': 'fa-warehouse',
            'color': 'secondary',
            'link': reverse('inventory:warehouse_list'),
            'hint': 'Storage locations in use',
        },
        {
            'key': 'consumption',
            'label': 'Item consumption',
            'value': f'{consumption_qty:,.0f}',
            'icon': 'fa-chart-line',
            'color': 'danger' if consumption_qty else 'secondary',
            'link': reverse('inventory:movement_list'),
            'hint': f'{month_start.strftime("%B %Y")} · AED {consumption_value:,.0f} at cost',
            'is_text': True,
        },
    ]

    secondary_stats = [
        {
            'label': 'Low stock items',
            'value': low_stock,
            'link': reverse('inventory:reorder_report'),
        },
        {
            'label': 'Stock movements (month)',
            'value': consumption_qs.count(),
            'link': reverse('inventory:movement_list'),
        },
        {
            'label': 'All material requests',
            'value': material_qs.count(),
            'link': reverse('inventory:consumable_request_list'),
        },
        {
            'label': 'Consumables dashboard',
            'value': '→',
            'link': reverse('inventory:consumable_dashboard'),
        },
    ]

    pending_preview = list(
        pending_material.select_related('requested_by', 'project', 'department').order_by(
            '-created_at'
        )[:PREVIEW_LIMIT]
    )
    approved_preview = list(
        approved_material_all.select_related('requested_by', 'project', 'warehouse').order_by(
            '-approved_date'
        )[:PREVIEW_LIMIT]
    )
    recent_consumption = list(
        consumption_qs.select_related('item', 'warehouse').order_by('-movement_date', '-created_at')[
            :PREVIEW_LIMIT
        ]
    )

    return {
        'today': today,
        'month_start': month_start,
        'month_end': month_end,
        'month_label': month_start.strftime('%B %Y'),
        'kpis': kpis,
        'secondary_stats': secondary_stats,
        'warehouse_rows': warehouse_rows,
        'top_consumed': top_consumed,
        'pending_material_requests': pending_preview,
        'approved_material_requests': approved_preview,
        'recent_consumption': recent_consumption,
        'total_qty': total_qty,
        'total_value': total_value,
        'consumption_qty': consumption_qty,
        'consumption_value': consumption_value,
        'can_create_request': user.is_superuser or PermissionChecker.has_permission(
            user, 'inventory', 'create'
        ),
    }
