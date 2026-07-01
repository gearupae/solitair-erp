"""Production routing — operation sequence per work order."""

from __future__ import annotations

from decimal import Decimal

from apps.mes.models import Part, RoutingOperation, WorkCenter

# Default standard minutes per production-line work center code (seed + auto-routing).
DEFAULT_STD_TIME_MINUTES: dict[str, int] = {
    'CUT': 15,
    'EDGE': 10,
    'CNC': 20,
    'ASSY': 25,
    'UPH': 30,
    'METAL': 20,
    'PAINT': 35,
    'QC': 10,
    'DISP': 5,
}


def get_production_line(company):
    return WorkCenter.objects.filter(
        company=company,
        is_active=True,
        is_production_step=True,
    ).order_by('sequence_order', 'pk')


def next_routing_sequence(production_order) -> int:
    last = (
        production_order.routing_operations.filter(is_active=True)
        .order_by('-sequence')
        .values_list('sequence', flat=True)
        .first()
    )
    return (last or 0) + 10


def ensure_routing_for_order(production_order) -> int:
    """
    Create routing operations from the production line if none exist.
    Returns number of operations created.
    """
    if production_order.routing_operations.filter(is_active=True).exists():
        return 0
    created = 0
    for wc in get_production_line(production_order.company):
        _, was_created = RoutingOperation.objects.get_or_create(
            company=production_order.company,
            production_order=production_order,
            work_center=wc,
            defaults={
                'sequence': wc.sequence_order,
                'std_time_minutes': DEFAULT_STD_TIME_MINUTES.get(wc.code, 15),
                'rate_per_hour': wc.cost_per_hour,
                'status': RoutingOperation.STATUS_PENDING,
            },
        )
        if was_created:
            created += 1
    return created


def get_routing_operations(production_order):
    return list(
        production_order.routing_operations.filter(is_active=True)
        .select_related('work_center')
        .prefetch_related('assigned_employees')
        .order_by('sequence', 'id'),
    )


def part_routing_index(part, operations: list[RoutingOperation]) -> int:
    """Index of the part's current routing step (-1 = not yet started)."""
    if part.current_work_center_id:
        for idx, op in enumerate(operations):
            if op.work_center_id == part.current_work_center_id:
                return idx
    if part.scans.exists():
        return 0
    return -1


def operation_status_for_order(
    operation: RoutingOperation,
    operations: list[RoutingOperation],
    parts,
) -> str:
    """Derive pending / in_progress / done from part positions on the line."""
    if not parts:
        return RoutingOperation.STATUS_PENDING

    op_idx = next(i for i, row in enumerate(operations) if row.pk == operation.pk)
    indices = [part_routing_index(part, operations) for part in parts]

    if all(idx > op_idx for idx in indices if idx >= 0):
        return RoutingOperation.STATUS_DONE
    if any(idx >= op_idx for idx in indices):
        return RoutingOperation.STATUS_IN_PROGRESS
    return RoutingOperation.STATUS_PENDING


def sync_routing_statuses(production_order) -> None:
    """Persist routing operation status from current part positions."""
    operations = get_routing_operations(production_order)
    if not operations:
        return
    parts = list(
        production_order.parts.filter(is_active=True).exclude(
            status=Part.STATUS_SCRAPPED,
        ).select_related('current_work_center'),
    )
    for op in operations:
        new_status = operation_status_for_order(op, operations, parts)
        if op.status != new_status:
            op.status = new_status
            op.save(update_fields=['status', 'updated_at'])


def standard_labour_cost(production_order, part_count: int = 1) -> Decimal:
    """Planned labour for one full pass through all routing steps."""
    total = Decimal('0')
    for op in get_routing_operations(production_order):
        hours = Decimal(op.std_time_minutes) / Decimal('60')
        total += hours * op.rate_per_hour * part_count
    return total


def labour_cost_from_routing_progress(production_order) -> Decimal:
    """
    Labour accumulated as parts progress: sum(std_time × rate) for each
    operation step reached by each active part.
    """
    operations = get_routing_operations(production_order)
    if not operations:
        return Decimal('0')

    parts = production_order.parts.filter(is_active=True).exclude(
        status=Part.STATUS_SCRAPPED,
    )
    total = Decimal('0')
    for part in parts:
        step_idx = part_routing_index(part, operations)
        if step_idx < 0:
            continue
        for idx in range(step_idx + 1):
            op = operations[idx]
            hours = Decimal(op.std_time_minutes) / Decimal('60')
            total += hours * op.rate_per_hour
    return total


def swap_routing_sequence(op_a: RoutingOperation, op_b: RoutingOperation) -> None:
    op_a.sequence, op_b.sequence = op_b.sequence, op_a.sequence
    op_a.save(update_fields=['sequence', 'updated_at'])
    op_b.save(update_fields=['sequence', 'updated_at'])
