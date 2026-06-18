"""FIFO cost layer rebuild and consumption logic."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from apps.inventory.models import StockMovement
from apps.inventory.models_reporting import InventoryCostLayer


def fifo_issue_unit_cost(item, warehouse, qty: Decimal) -> Decimal:
    """
    Consume qty from FIFO cost layers and return weighted-average unit cost.

    Falls back to ``item.get_issue_unit_cost`` when layers are missing or insufficient.
    """
    qty = Decimal(str(qty)).quantize(Decimal('0.01'))
    if qty <= 0:
        return Decimal('0.00')

    layers = list(
        InventoryCostLayer.objects.filter(
            item=item,
            warehouse=warehouse,
            qty_remaining__gt=0,
        ).order_by('received_date', 'id')
    )
    if not layers:
        cost = item.get_issue_unit_cost(warehouse)
        return cost if cost and cost > 0 else Decimal('0.00')

    remaining = qty
    total_cost = Decimal('0')
    consumed = Decimal('0')

    for layer in layers:
        if remaining <= 0:
            break
        if layer.qty_remaining <= 0:
            continue
        take = min(layer.qty_remaining, remaining)
        total_cost += take * (layer.unit_cost or Decimal('0'))
        consumed += take
        layer.qty_remaining = (layer.qty_remaining - take).quantize(Decimal('0.01'))
        layer.save(update_fields=['qty_remaining'])
        remaining -= take

    if consumed <= 0:
        cost = item.get_issue_unit_cost(warehouse)
        return cost if cost and cost > 0 else Decimal('0.00')

    if remaining > 0:
        fallback = item.get_issue_unit_cost(warehouse) or Decimal('0.00')
        total_cost += remaining * fallback

    return (total_cost / qty).quantize(Decimal('0.01'))


@transaction.atomic
def consume_fifo_layers(item, warehouse, qty: Decimal) -> Decimal:
    """Alias for ``fifo_issue_unit_cost`` (atomic layer consumption)."""
    return fifo_issue_unit_cost(item, warehouse, qty)


def _consume_layers(layers: list[InventoryCostLayer], qty: Decimal) -> Decimal:
    """Consume qty from layers list (FIFO). Returns unconsumed qty."""
    remaining = qty
    for layer in layers:
        if remaining <= 0:
            break
        if layer.qty_remaining <= 0:
            continue
        take = min(layer.qty_remaining, remaining)
        layer.qty_remaining = (layer.qty_remaining - take).quantize(Decimal('0.01'))
        layer.save(update_fields=['qty_remaining'])
        remaining -= take
    return remaining


@transaction.atomic
def rebuild_fifo_layers(*, item_id=None, warehouse_id=None) -> int:
    """
    Rebuild all cost layers from stock movement history (chronological).
    Returns number of layers created.
    """
    delete_qs = InventoryCostLayer.objects.all()
    if item_id:
        delete_qs = delete_qs.filter(item_id=item_id)
    if warehouse_id:
        delete_qs = delete_qs.filter(warehouse_id=warehouse_id)
    delete_qs.delete()

    mov_qs = StockMovement.objects.all().order_by('movement_date', 'created_at', 'id')
    if item_id:
        mov_qs = mov_qs.filter(item_id=item_id)
    if warehouse_id:
        mov_qs = mov_qs.filter(warehouse_id=warehouse_id)

    layer_stacks: dict[tuple[int, int], list[InventoryCostLayer]] = defaultdict(list)
    created = 0

    for mov in mov_qs.iterator():
        key = (mov.item_id, mov.warehouse_id)
        qty = abs(mov.quantity or Decimal('0'))
        if qty <= 0:
            continue

        if mov.movement_type in ('in', 'adjustment_plus'):
            layer = InventoryCostLayer.objects.create(
                item_id=mov.item_id,
                warehouse_id=mov.warehouse_id,
                qty_remaining=qty,
                unit_cost=mov.unit_cost or Decimal('0'),
                received_date=mov.movement_date,
                source_movement=mov,
            )
            layer_stacks[key].append(layer)
            created += 1

        elif mov.movement_type in ('out', 'adjustment_minus'):
            _consume_layers(layer_stacks[key], qty)

        elif mov.movement_type == 'transfer' and mov.to_warehouse_id:
            dest_key = (mov.item_id, mov.to_warehouse_id)
            remaining = qty
            unit_cost = mov.unit_cost or Decimal('0')
            for layer in list(layer_stacks[key]):
                if remaining <= 0:
                    break
                if layer.qty_remaining <= 0:
                    continue
                take = min(layer.qty_remaining, remaining)
                layer.qty_remaining = (layer.qty_remaining - take).quantize(Decimal('0.01'))
                layer.save(update_fields=['qty_remaining'])
                remaining -= take
                if unit_cost <= 0 and layer.unit_cost > 0:
                    unit_cost = layer.unit_cost
            received_qty = qty - remaining
            if received_qty > 0:
                layer = InventoryCostLayer.objects.create(
                    item_id=mov.item_id,
                    warehouse_id=mov.to_warehouse_id,
                    qty_remaining=received_qty,
                    unit_cost=unit_cost,
                    received_date=mov.movement_date,
                    source_movement=mov,
                )
                layer_stacks[dest_key].append(layer)
                created += 1

    # Remove zero-qty layers from DB
    InventoryCostLayer.objects.filter(qty_remaining__lte=0).delete()
    return created
