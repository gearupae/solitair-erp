"""Production order status pipeline — Draft → Released → In Production → Finished."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.mes.models import ProductionOrder, ProductionOrderStatusLog
from apps.mes.services.costing import freeze_production_order_cost, recalculate_wip


class PipelineError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


FORWARD = {
    ProductionOrder.STATUS_DRAFT: ProductionOrder.STATUS_RELEASED,
    ProductionOrder.STATUS_RELEASED: ProductionOrder.STATUS_IN_PRODUCTION,
    ProductionOrder.STATUS_IN_PRODUCTION: ProductionOrder.STATUS_FINISHED,
}

BACKWARD = {v: k for k, v in FORWARD.items()}


def _log_transition(production_order, from_status, to_status, user, notes=''):
    ProductionOrderStatusLog.objects.create(
        company=production_order.company,
        production_order=production_order,
        from_status=from_status or '',
        to_status=to_status,
        notes=notes,
        changed_by=user if user and getattr(user, 'is_authenticated', False) else None,
    )


def can_advance_to(production_order: ProductionOrder, target: str) -> str | None:
    current = production_order.status
    if current == target:
        return 'Order is already in that status.'

    if target == ProductionOrder.STATUS_CANCELLED:
        if current == ProductionOrder.STATUS_FINISHED:
            return 'Finished orders cannot be cancelled.'
        return None

    if target == ProductionOrder.STATUS_ON_HOLD:
        if current in (
            ProductionOrder.STATUS_DRAFT,
            ProductionOrder.STATUS_FINISHED,
            ProductionOrder.STATUS_CANCELLED,
        ):
            return 'Cannot put this order on hold from the current status.'
        return None

    if current == ProductionOrder.STATUS_ON_HOLD:
        if target in (ProductionOrder.STATUS_RELEASED, ProductionOrder.STATUS_IN_PRODUCTION):
            return None
        return 'Resume to Released or In Production.'

    if target == BACKWARD.get(current):
        return None

    if FORWARD.get(current) == target:
        if target in (
            ProductionOrder.STATUS_RELEASED,
            ProductionOrder.STATUS_IN_PRODUCTION,
        ):
            if production_order.parts.filter(is_active=True).count() == 0:
                return 'Generate parts before advancing.'
        return None

    return 'Invalid status transition.'


@transaction.atomic
def advance_production_order(
    production_order: ProductionOrder,
    target: str,
    user=None,
    notes: str = '',
) -> ProductionOrder:
    error = can_advance_to(production_order, target)
    if error:
        raise PipelineError(error)

    from_status = production_order.status
    production_order.status = target
    update_fields = ['status', 'updated_at']

    if target == ProductionOrder.STATUS_RELEASED and not production_order.released_at:
        production_order.released_at = timezone.now()
        update_fields.append('released_at')
    if target == ProductionOrder.STATUS_FINISHED:
        production_order.finished_at = timezone.now()
        update_fields.append('finished_at')
        freeze_production_order_cost(production_order)
        update_fields.extend([
            'final_total_cost',
            'frozen_material_cost',
            'frozen_labour_cost',
            'frozen_machine_cost',
            'frozen_overhead_cost',
            'cost_frozen_at',
            'wip_value',
        ])

    production_order.save(update_fields=update_fields)
    _log_transition(production_order, from_status, target, user, notes)

    if target != ProductionOrder.STATUS_FINISHED:
        recalculate_wip(production_order)

    return production_order


def next_pipeline_status(production_order: ProductionOrder) -> str | None:
    if production_order.status == ProductionOrder.STATUS_ON_HOLD:
        return ProductionOrder.STATUS_IN_PRODUCTION
    return FORWARD.get(production_order.status)


def previous_pipeline_status(production_order: ProductionOrder) -> str | None:
    if production_order.status == ProductionOrder.STATUS_ON_HOLD:
        return ProductionOrder.STATUS_RELEASED
    return BACKWARD.get(production_order.status)
