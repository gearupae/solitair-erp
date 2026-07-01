"""Production cost roll-up: material + team labour + machine + overhead."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from apps.mes.models import BOMItem, MaterialConsumption, Part, ProductionOrder
from apps.mes.services.labour_utils import po_team_labour_summary, team_labour_cost
from apps.mes.services.routing import labour_cost_from_routing_progress, sync_routing_statuses


@dataclass
class WIPBreakdown:
    material: Decimal
    labour: Decimal
    machine: Decimal
    overhead: Decimal
    total: Decimal
    per_unit: Decimal
    labour_lines: list = field(default_factory=list)
    is_frozen: bool = False


def _inventory_unit_price(bom_item: BOMItem) -> Decimal:
    if bom_item.inventory_item_id:
        return bom_item.inventory_item.purchase_price or Decimal('0')
    return bom_item.unit_cost or Decimal('0')


def _material_cost(production_order: ProductionOrder) -> Decimal:
    """Material = sum(BOM qty × PO qty × inventory unit price) on active BOM lines."""
    po_qty = Decimal(production_order.quantity)
    total = Decimal('0')
    for line in production_order.bom_items.filter(is_active=True).select_related('inventory_item'):
        line_qty = Decimal(line.quantity) * po_qty
        total += line_qty * _inventory_unit_price(line)

    consumed = MaterialConsumption.objects.filter(
        production_order=production_order,
        company=production_order.company,
        is_active=True,
    ).select_related('bom_item', 'bom_item__inventory_item')
    for row in consumed:
        total += row.qty_consumed * _inventory_unit_price(row.bom_item)

    return total


def _machine_cost(production_order: ProductionOrder) -> Decimal:
    """Machine cost from routing progress: std_time × work-center rate per part step."""
    return labour_cost_from_routing_progress(production_order)


def compute_wip_breakdown(production_order: ProductionOrder) -> WIPBreakdown:
    if production_order.is_cost_frozen and production_order.final_total_cost is not None:
        qty = max(production_order.quantity, 1)
        per_unit = (production_order.final_total_cost / Decimal(qty)).quantize(Decimal('0.01'))
        return WIPBreakdown(
            material=production_order.frozen_material_cost or Decimal('0.00'),
            labour=production_order.frozen_labour_cost or Decimal('0.00'),
            machine=production_order.frozen_machine_cost or Decimal('0.00'),
            overhead=production_order.frozen_overhead_cost or Decimal('0.00'),
            total=production_order.final_total_cost,
            per_unit=per_unit,
            is_frozen=True,
        )

    sync_routing_statuses(production_order)
    material = _material_cost(production_order)
    labour_lines, _, labour = po_team_labour_summary(production_order)
    if labour == 0:
        labour = team_labour_cost(production_order)
    machine = _machine_cost(production_order)
    subtotal = material + labour + machine
    overhead_rate = production_order.overhead_percent / Decimal('100')
    overhead = subtotal * overhead_rate
    total = subtotal + overhead
    qty = max(production_order.quantity, 1)
    per_unit = (total / Decimal(qty)).quantize(Decimal('0.01'))
    return WIPBreakdown(
        material=material.quantize(Decimal('0.01')),
        labour=labour.quantize(Decimal('0.01')),
        machine=machine.quantize(Decimal('0.01')),
        overhead=overhead.quantize(Decimal('0.01')),
        total=total.quantize(Decimal('0.01')),
        per_unit=per_unit,
        labour_lines=labour_lines,
        is_frozen=False,
    )


def recalculate_wip(production_order: ProductionOrder) -> Decimal:
    if production_order.is_cost_frozen:
        return production_order.final_total_cost or production_order.wip_value
    breakdown = compute_wip_breakdown(production_order)
    if production_order.wip_value != breakdown.total:
        production_order.wip_value = breakdown.total
        production_order.save(update_fields=['wip_value', 'updated_at'])
    return breakdown.total


def freeze_production_order_cost(production_order: ProductionOrder) -> Decimal:
    breakdown = compute_wip_breakdown(production_order)
    production_order.final_total_cost = breakdown.total
    production_order.frozen_material_cost = breakdown.material
    production_order.frozen_labour_cost = breakdown.labour
    production_order.frozen_machine_cost = breakdown.machine
    production_order.frozen_overhead_cost = breakdown.overhead
    production_order.cost_frozen_at = timezone.now()
    production_order.wip_value = breakdown.total
    production_order.save(
        update_fields=[
            'final_total_cost',
            'frozen_material_cost',
            'frozen_labour_cost',
            'frozen_machine_cost',
            'frozen_overhead_cost',
            'cost_frozen_at',
            'wip_value',
            'updated_at',
        ],
    )
    return breakdown.total
