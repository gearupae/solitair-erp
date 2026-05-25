"""Record delivery of inventory items to a project."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import Item, Stock, StockMovement, ItemSerialNumber
from apps.inventory.serial_stock import deliver_serial_items_to_project, item_available_qty, sync_serial_stock_mirror
from apps.projects.models import Project, ProjectItemDelivery, ProjectItemLine, ProjectItemReturn


def project_item_required_qty(project: Project, item: Item):
    """Total qty of this item on the project scope (estimate lines), or None if not scoped."""
    from django.db.models import Sum

    total = ProjectItemLine.objects.filter(
        project=project,
        inventory_item=item,
    ).aggregate(t=Sum('quantity'))['t']
    if total is None:
        return None
    return total


def project_item_delivered_qty(project: Project, item: Item) -> Decimal:
    """How many units of this item are currently on the project (delivered − returned)."""
    from django.db.models import Sum

    if item.track_by_serial:
        return Decimal(
            ItemSerialNumber.objects.filter(
                assigned_project=project,
                item=item,
                status=ItemSerialNumber.STATUS_DELIVERED,
                is_active=True,
            ).count()
        )

    delivery_sum = ProjectItemDelivery.objects.filter(
        project=project,
        item=item,
    ).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
    returned_sum = ProjectItemReturn.objects.filter(
        project=project,
        item=item,
        serial_number__isnull=True,
    ).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
    return delivery_sum - returned_sum


def _item_unit_cost(item: Item, *, warehouse=None) -> Decimal:
    """Inventory unit cost for project spend (purchase price or last receipt cost)."""
    cost = item.get_issue_unit_cost(warehouse)
    return cost if cost and cost > 0 else Decimal('0.00')


def project_inventory_spend_total(project: Project) -> Decimal:
    """
    Value of inventory currently on the project (deliveries increase, returns decrease).
    Serial items: sum unit cost per delivered serial still on site.
    Non-serial: net qty × unit cost.
    """
    total = Decimal('0.00')

    serials = (
        ItemSerialNumber.objects.filter(
            assigned_project=project,
            status=ItemSerialNumber.STATUS_DELIVERED,
            is_active=True,
        )
        .select_related('item', 'warehouse')
    )
    for sn in serials:
        total += _item_unit_cost(sn.item, warehouse=sn.warehouse)

    non_serial_item_ids = (
        ProjectItemDelivery.objects.filter(project=project)
        .values_list('item_id', flat=True)
        .distinct()
    )
    for item_id in non_serial_item_ids:
        item = Item.objects.filter(pk=item_id, track_by_serial=False).first()
        if not item:
            continue
        net_qty = project_item_returnable_qty(project, item)
        if net_qty <= 0:
            continue
        last_out = (
            StockMovement.objects.filter(
                item=item,
                movement_type='out',
                reference__icontains=project.project_code,
            )
            .select_related('warehouse')
            .order_by('-movement_date', '-pk')
            .first()
        )
        wh = last_out.warehouse if last_out else None
        total += net_qty * _item_unit_cost(item, warehouse=wh)

    return total.quantize(Decimal('0.01'))


def project_item_returnable_qty(project: Project, item: Item) -> Decimal:
    """Units currently on the project that can be returned to stock."""
    if item.track_by_serial:
        return Decimal(
            ItemSerialNumber.objects.filter(
                assigned_project=project,
                item=item,
                status=ItemSerialNumber.STATUS_DELIVERED,
                is_active=True,
            ).count()
        )
    from django.db.models import Sum

    delivery_sum = ProjectItemDelivery.objects.filter(
        project=project,
        item=item,
    ).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
    returned_sum = ProjectItemReturn.objects.filter(
        project=project,
        item=item,
        serial_number__isnull=True,
    ).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
    return max(Decimal('0'), delivery_sum - returned_sum)


def project_returnable_item_ids(project: Project) -> list[int]:
    """Inventory item PKs that have at least one returnable unit on this project."""
    ids = set()
    for item_id in ItemSerialNumber.objects.filter(
        assigned_project=project,
        status=ItemSerialNumber.STATUS_DELIVERED,
        is_active=True,
    ).values_list('item_id', flat=True).distinct():
        ids.add(item_id)
    for item_id in ProjectItemDelivery.objects.filter(project=project).values_list('item_id', flat=True).distinct():
        item = Item.objects.filter(pk=item_id).first()
        if item and not item.track_by_serial and project_item_returnable_qty(project, item) > 0:
            ids.add(item_id)
    return sorted(ids)


def project_item_remaining_qty(project: Project, item: Item):
    """Units still allowed for delivery, or None if item is not on project scope."""
    required = project_item_required_qty(project, item)
    if required is None:
        return None
    return max(Decimal('0'), required - project_item_delivered_qty(project, item))


def project_has_scoped_inventory_lines(project: Project) -> bool:
    return ProjectItemLine.objects.filter(
        project=project,
        inventory_item__isnull=False,
    ).exists()


@transaction.atomic
def deliver_items_to_project(
    project: Project,
    item: Item,
    quantity,
    delivery_date: date,
    user,
    *,
    warehouse=None,
):
    """
    Deliver inventory to a project.
    Serial items: FIFO auto-assign model numbers.
    Non-serial items: stock movement out + delivery log row.
    """
    try:
        qty = Decimal(str(quantity)).quantize(Decimal('0.01'))
    except Exception as exc:
        raise ValidationError('Invalid quantity.') from exc
    if qty <= 0:
        raise ValidationError('Quantity must be greater than zero.')

    remaining = project_item_remaining_qty(project, item)
    if remaining is not None and qty > remaining:
        required = project_item_required_qty(project, item)
        delivered = project_item_delivered_qty(project, item)
        if remaining <= 0:
            raise ValidationError(
                f'This project already has all {required} unit(s) of {item.name} delivered.'
            )
        raise ValidationError(
            f'This project requires {required} × {item.name}; '
            f'{delivered} already delivered. You can deliver at most {remaining} more.'
        )

    if item.track_by_serial:
        if qty != qty.to_integral_value():
            raise ValidationError('Serial-tracked items require a whole-number quantity.')
        serials = deliver_serial_items_to_project(
            project, item, int(qty), delivery_date, user, warehouse=warehouse
        )
        return {'serials': serials, 'quantity': qty}

    available = item_available_qty(item, warehouse=warehouse)
    if qty > available:
        raise ValidationError(
            f'Only {available.quantize(Decimal("0.01"))} units available for {item.name}.'
        )

    if warehouse is None:
        stock_qs = Stock.objects.filter(
            item=item,
            warehouse__is_active=True,
            warehouse__status='active',
            quantity__gte=qty,
        ).select_related('warehouse').order_by('-quantity')
        stock_row = stock_qs.first()
        if not stock_row:
            raise ValidationError(f'Insufficient stock for {item.name}.')
        warehouse = stock_row.warehouse

    stock_record = Stock.objects.filter(item=item, warehouse=warehouse).first()
    if not stock_record or stock_record.quantity < qty:
        avail = stock_record.quantity if stock_record else Decimal('0')
        raise ValidationError(
            f'Insufficient stock for {item.name} in {warehouse.name}. '
            f'Available: {avail}, requested: {qty}.'
        )

    unit_cost = item.get_issue_unit_cost(warehouse)
    movement = StockMovement.objects.create(
        item=item,
        warehouse=warehouse,
        movement_type='out',
        source='manual',
        quantity=qty,
        unit_cost=unit_cost,
        reference=f'Project delivery: {project.project_code}',
        notes=f'Delivered to project {project.name}',
        movement_date=delivery_date,
        created_by=user,
    )
    movement.execute(user=user, allow_zero_cost=unit_cost <= 0)

    ProjectItemDelivery.objects.create(
        project=project,
        item=item,
        quantity=qty,
        delivered_date=delivery_date,
        delivered_by=user,
    )
    return {'serials': [], 'quantity': qty}


@transaction.atomic
def return_serial_unit_from_project(project: Project, serial_pk: int, return_date: date, user):
    """Return one serial-tracked unit from the project back to available stock."""
    sn = (
        ItemSerialNumber.objects.select_for_update()
        .select_related('item', 'warehouse')
        .filter(
            pk=serial_pk,
            assigned_project=project,
            status=ItemSerialNumber.STATUS_DELIVERED,
            is_active=True,
        )
        .first()
    )
    if not sn:
        raise ValidationError('That serial unit is not on this project or was already returned.')

    sn.status = ItemSerialNumber.STATUS_AVAILABLE
    sn.assigned_project = None
    sn.delivered_date = None
    sn.delivered_by = None
    sn.save(
        update_fields=[
            'status',
            'assigned_project',
            'delivered_date',
            'delivered_by',
            'updated_at',
        ]
    )
    sync_serial_stock_mirror(sn.item, sn.warehouse)
    ProjectItemReturn.objects.create(
        project=project,
        item=sn.item,
        quantity=Decimal('1'),
        returned_date=return_date,
        returned_by=user,
        serial_number=sn,
        notes=f'Returned {sn.model_number} to stock',
    )
    return sn


@transaction.atomic
def return_items_from_project(
    project: Project,
    item: Item,
    quantity,
    return_date: date,
    user,
    *,
    warehouse=None,
):
    """
    Return units from a project back to inventory.
    Serial items: LIFO (most recently delivered first) unless quantity is 1 with one serial.
    Non-serial: stock movement in + return log.
    """
    try:
        qty = Decimal(str(quantity)).quantize(Decimal('0.01'))
    except Exception as exc:
        raise ValidationError('Invalid quantity.') from exc
    if qty <= 0:
        raise ValidationError('Quantity must be greater than zero.')

    returnable = project_item_returnable_qty(project, item)
    if qty > returnable:
        raise ValidationError(
            f'Only {returnable} unit(s) of {item.name} can be returned from this project.'
        )

    if item.track_by_serial:
        if qty != qty.to_integral_value():
            raise ValidationError('Serial-tracked items require a whole-number quantity.')
        count = int(qty)
        serials = list(
            ItemSerialNumber.objects.select_for_update()
            .filter(
                assigned_project=project,
                item=item,
                status=ItemSerialNumber.STATUS_DELIVERED,
                is_active=True,
            )
            .order_by('-delivered_date', '-pk')[:count]
        )
        if len(serials) < count:
            raise ValidationError(f'Only {len(serials)} serial unit(s) available to return.')
        returned = []
        for sn in serials:
            returned.append(
                return_serial_unit_from_project(project, sn.pk, return_date, user)
            )
        return {'serials': returned, 'quantity': qty}

    if warehouse is None:
        last_out = (
            StockMovement.objects.filter(
                item=item,
                movement_type='out',
                reference__icontains=project.project_code,
            )
            .select_related('warehouse')
            .order_by('-movement_date', '-pk')
            .first()
        )
        if last_out:
            warehouse = last_out.warehouse
        else:
            stock_row = (
                Stock.objects.filter(item=item, warehouse__is_active=True)
                .select_related('warehouse')
                .order_by('-quantity')
                .first()
            )
            if not stock_row:
                raise ValidationError(f'No warehouse found to receive returned {item.name}.')
            warehouse = stock_row.warehouse

    unit_cost = item.get_issue_unit_cost(warehouse)
    movement = StockMovement.objects.create(
        item=item,
        warehouse=warehouse,
        movement_type='in',
        source='manual',
        quantity=qty,
        unit_cost=unit_cost,
        reference=f'Project return: {project.project_code}',
        notes=f'Returned from project {project.name}',
        movement_date=return_date,
        created_by=user,
    )
    movement.execute(user=user, allow_zero_cost=unit_cost <= 0)

    ProjectItemReturn.objects.create(
        project=project,
        item=item,
        quantity=qty,
        returned_date=return_date,
        returned_by=user,
        notes=f'Returned {qty} × {item.name} to {warehouse.name}',
    )
    return {'serials': [], 'quantity': qty}


def project_delivery_summary_groups(project):
    """Grouped delivery summary for the project sidebar (one row per item)."""
    from django.db.models import Count, Max

    groups = []

    serial_agg = (
        ItemSerialNumber.objects.filter(
            assigned_project=project,
            status=ItemSerialNumber.STATUS_DELIVERED,
            is_active=True,
        )
        .values('item_id', 'item__name')
        .annotate(qty=Count('id'), latest_date=Max('delivered_date'))
        .order_by('-latest_date', 'item__name')
    )
    for row in serial_agg:
        serials = list(
            ItemSerialNumber.objects.filter(
                assigned_project=project,
                item_id=row['item_id'],
                status=ItemSerialNumber.STATUS_DELIVERED,
                is_active=True,
            )
            .order_by('-delivered_date', 'model_number')
        )
        groups.append({
            'item_id': row['item_id'],
            'item_name': row['item__name'],
            'quantity': row['qty'],
            'latest_date': row['latest_date'],
            'is_serial': True,
            'serials': [
                {
                    'serial_pk': sn.pk,
                    'model_number': sn.model_number,
                    'delivered_date': sn.delivered_date,
                }
                for sn in serials
            ],
        })

    serial_item_ids = {g['item_id'] for g in groups}
    for item_id in (
        ProjectItemDelivery.objects.filter(project=project)
        .values_list('item_id', flat=True)
        .distinct()
    ):
        if item_id in serial_item_ids:
            continue
        item = Item.objects.filter(pk=item_id).first()
        if not item or item.track_by_serial:
            continue
        net = project_item_returnable_qty(project, item)
        if net <= 0:
            continue
        latest = (
            ProjectItemDelivery.objects.filter(project=project, item_id=item_id)
            .order_by('-delivered_date')
            .values_list('delivered_date', flat=True)
            .first()
        )
        groups.append({
            'item_id': item_id,
            'item_name': item.name,
            'quantity': net,
            'latest_date': latest,
            'is_serial': False,
            'serials': [],
            'returnable_qty': net,
        })

    groups.sort(key=lambda g: (g['latest_date'] or date.min, g['item_name']), reverse=True)
    return groups


def project_return_history_rows(project):
    """Compact return log for the deliveries card."""
    rows = []
    for ret in (
        ProjectItemReturn.objects.filter(project=project)
        .select_related('item', 'serial_number')
        .order_by('-returned_date', '-pk')[:30]
    ):
        if ret.serial_number_id:
            detail = ret.serial_number.model_number
        else:
            qty = ret.quantity
            if qty == qty.to_integral_value():
                qty = int(qty)
            detail = f'Qty {qty}'
        rows.append({
            'item_name': ret.item.name,
            'detail': detail,
            'returned_date': ret.returned_date,
        })
    return rows


def project_delivery_display_rows(project):
    """Legacy flat rows — prefer project_delivery_summary_groups for UI."""
    from apps.inventory.models import ItemSerialNumber

    rows = []
    serials = (
        ItemSerialNumber.objects.filter(
            assigned_project=project,
            status=ItemSerialNumber.STATUS_DELIVERED,
            is_active=True,
        )
        .select_related('item')
        .order_by('-delivered_date', 'model_number')
    )
    for sn in serials:
        rows.append({
            'item_name': sn.item.name,
            'model_number': sn.model_number,
            'quantity_label': '',
            'delivered_date': sn.delivered_date,
            'sort_date': sn.delivered_date,
            'serial_pk': sn.pk,
            'can_return': True,
        })

    for delivery in (
        ProjectItemDelivery.objects.filter(project=project)
        .select_related('item')
        .order_by('-delivered_date', '-pk')
    ):
        qty_label = delivery.quantity
        if delivery.quantity == delivery.quantity.to_integral_value():
            qty_label = int(delivery.quantity)
        returnable = project_item_returnable_qty(project, delivery.item)
        rows.append({
            'item_name': delivery.item.name,
            'model_number': '',
            'quantity_label': f'Qty: {qty_label}',
            'delivered_date': delivery.delivered_date,
            'sort_date': delivery.delivered_date,
            'serial_pk': None,
            'can_return': returnable > 0 and not delivery.item.track_by_serial,
            'item_id': delivery.item_id,
            'returnable_qty': returnable,
        })

    for ret in (
        ProjectItemReturn.objects.filter(project=project)
        .select_related('item', 'serial_number')
        .order_by('-returned_date', '-pk')
    ):
        label = ret.serial_number.model_number if ret.serial_number_id else f'Qty: {ret.quantity}'
        rows.append({
            'item_name': ret.item.name,
            'model_number': label if ret.serial_number_id else '',
            'quantity_label': '' if ret.serial_number_id else label,
            'delivered_date': ret.returned_date,
            'sort_date': ret.returned_date,
            'serial_pk': None,
            'can_return': False,
            'is_return': True,
        })

    rows.sort(
        key=lambda r: (r['sort_date'] or date.min, r.get('model_number') or ''),
        reverse=True,
    )
    return rows
