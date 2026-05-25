"""Serial-tracked inventory stock helpers."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from .models import ItemSerialNumber, Stock


def item_available_qty(item, *, warehouse=None) -> Decimal:
    """Available stock: serial count for tracked items, else warehouse/total stock qty."""
    if not item.track_by_serial:
        qs = Stock.objects.filter(item=item, warehouse__is_active=True)
        if warehouse is not None:
            qs = qs.filter(warehouse=warehouse)
        total = qs.aggregate(total=Sum('quantity'))['total']
        return (total or Decimal('0.00')).quantize(Decimal('0.01'))

    qs = ItemSerialNumber.objects.filter(
        item=item,
        status=ItemSerialNumber.STATUS_AVAILABLE,
        is_active=True,
    )
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    return Decimal(qs.count()).quantize(Decimal('0.01'))


def sync_serial_stock_mirror(item, warehouse) -> None:
    """Set Stock.quantity to count of available serials (serial-tracked items only)."""
    if not item.track_by_serial:
        return
    available = ItemSerialNumber.objects.filter(
        item=item,
        warehouse=warehouse,
        status=ItemSerialNumber.STATUS_AVAILABLE,
        is_active=True,
    ).count()
    stock, _ = Stock.objects.get_or_create(
        item=item,
        warehouse=warehouse,
        defaults={'quantity': Decimal('0.00')},
    )
    stock.quantity = Decimal(available).quantize(Decimal('0.01'))
    stock.save(update_fields=['quantity', 'updated_at'])


def fifo_pick_serials(item, quantity, *, warehouse=None, for_update=False):
    """Return up to `quantity` available serials in FIFO order (oldest received first)."""
    qty = int(quantity)
    if qty <= 0:
        return []
    qs = ItemSerialNumber.objects.filter(
        item=item,
        status=ItemSerialNumber.STATUS_AVAILABLE,
        is_active=True,
    ).order_by('date_received', 'pk')
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if for_update:
        qs = qs.select_for_update()
    serials = list(qs[:qty])
    if len(serials) < qty:
        available = len(serials)
        raise ValidationError(f'Only {available} unit{"s" if available != 1 else ""} available.')
    return serials


def validate_model_numbers_for_receive(item, model_numbers, *, qty_expected):
    """Validate model number list for PO receive."""
    cleaned = [m.strip() for m in model_numbers if (m or '').strip()]
    if len(cleaned) != int(qty_expected):
        raise ValidationError(
            f'Enter exactly {int(qty_expected)} model number(s) for {item.name}.'
        )
    lower = [m.lower() for m in cleaned]
    if len(lower) != len(set(lower)):
        raise ValidationError(f'Duplicate model numbers in submission for {item.name}.')
    existing = set(
        ItemSerialNumber.objects.filter(item=item, model_number__in=cleaned)
        .values_list('model_number', flat=True)
    )
    if existing:
        raise ValidationError(
            f'Model number(s) already registered for {item.name}: {", ".join(sorted(existing))}'
        )
    return cleaned


def item_has_blocking_stock_for_serial_toggle(item) -> bool:
    """True if legacy qty stock exists while serial tracking is off."""
    if item.track_by_serial:
        return False
    return item.total_stock > 0


@transaction.atomic
def deliver_serial_items_to_project(project, item, quantity, delivery_date, user, *, warehouse=None):
    """FIFO-deliver serial-tracked units to a project."""
    if not item.track_by_serial:
        raise ValidationError(f'{item.name} is not tracked by serial number.')
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        raise ValidationError('Quantity must be a whole number.') from None
    if qty <= 0:
        raise ValidationError('Quantity must be greater than zero.')

    serials = fifo_pick_serials(item, qty, warehouse=warehouse, for_update=True)
    warehouses_touched = set()
    for sn in serials:
        sn.status = ItemSerialNumber.STATUS_DELIVERED
        sn.assigned_project = project
        sn.delivered_date = delivery_date
        sn.delivered_by = user
        sn.save(
            update_fields=[
                'status',
                'assigned_project',
                'delivered_date',
                'delivered_by',
                'updated_at',
            ]
        )
        warehouses_touched.add(sn.warehouse_id)

    for wh_id in warehouses_touched:
        from .models import Warehouse
        wh = Warehouse.objects.get(pk=wh_id)
        sync_serial_stock_mirror(item, wh)

    return serials


def on_hand_units_needing_model_numbers(item) -> int:
    """In-stock qty minus available registered serials (tracking on or being enabled)."""
    stock_total = Stock.objects.filter(
        item=item,
        warehouse__is_active=True,
    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
    registered = ItemSerialNumber.objects.filter(
        item=item,
        status=ItemSerialNumber.STATUS_AVAILABLE,
        is_active=True,
    ).count()
    return max(0, int(stock_total) - registered)


def unregistered_on_hand_count(item) -> int:
    """How many in-stock units still need model numbers (serial-tracked items)."""
    if not item.track_by_serial:
        return 0
    return on_hand_units_needing_model_numbers(item)


@transaction.atomic
def register_on_hand_model_numbers(item, model_numbers, user, *, received_on=None):
    """Register model numbers for units already in stock (before tracking was enabled)."""
    from datetime import date

    if not item.track_by_serial:
        raise ValidationError(f'{item.name} is not set to track by model number.')

    needed = unregistered_on_hand_count(item)
    if needed <= 0:
        raise ValidationError('All on-hand units already have model numbers.')

    cleaned = [m.strip() for m in model_numbers if (m or '').strip()]
    if len(cleaned) != needed:
        raise ValidationError(f'Enter exactly {needed} model number(s) for units already in stock.')

    lower = [m.lower() for m in cleaned]
    if len(lower) != len(set(lower)):
        raise ValidationError('Duplicate model numbers in submission.')

    existing = set(
        ItemSerialNumber.objects.filter(item=item, model_number__in=cleaned)
        .values_list('model_number', flat=True)
    )
    if existing:
        raise ValidationError(
            f'Model number(s) already registered: {", ".join(sorted(existing))}'
        )

    recv_date = received_on or date.today()
    stocks = list(
        Stock.objects.filter(item=item, warehouse__is_active=True, quantity__gt=0)
        .select_related('warehouse')
        .order_by('warehouse__name')
    )
    if not stocks:
        raise ValidationError('No warehouse stock found to assign model numbers.')

    idx = 0
    warehouses_touched = set()
    for stock in stocks:
        wh_qty = int(stock.quantity)
        for _ in range(wh_qty):
            if idx >= len(cleaned):
                break
            ItemSerialNumber.objects.create(
                item=item,
                model_number=cleaned[idx],
                warehouse=stock.warehouse,
                date_received=recv_date,
                status=ItemSerialNumber.STATUS_AVAILABLE,
                created_by=user,
            )
            warehouses_touched.add(stock.warehouse_id)
            idx += 1

    for wh_id in warehouses_touched:
        from .models import Warehouse
        sync_serial_stock_mirror(item, Warehouse.objects.get(pk=wh_id))

    return cleaned


def annotate_item_available_stock(queryset):
    """Annotate queryset with total_stock_calc (serial count or stock sum)."""
    from django.db.models import Count, Case, When, Sum, Q, Value, DecimalField, F
    from django.db.models.functions import Cast, Coalesce

    avail_filter = Q(
        serial_numbers__status=ItemSerialNumber.STATUS_AVAILABLE,
        serial_numbers__is_active=True,
    )
    qs = queryset.annotate(
        _serial_available=Count('serial_numbers', filter=avail_filter),
    )
    return qs.annotate(
        total_stock_calc=Case(
            When(
                track_by_serial=True,
                then=Cast(
                    F('_serial_available'),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                ),
            ),
            default=Coalesce(
                Sum(
                    'stock_records__quantity',
                    filter=Q(stock_records__warehouse__is_active=True),
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            output_field=DecimalField(max_digits=15, decimal_places=2),
        ),
    )
