"""Production order numbering and release workflow."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.mes.models import ProductionOrder


class POWorkflowError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def allocate_po_number(company) -> str:
    """Tenant-scoped PO-YYYY-#### sequential number (concurrency-safe)."""
    year = timezone.now().year
    prefix = f'PO-{year}-'
    with transaction.atomic():
        last = (
            ProductionOrder.objects.select_for_update()
            .filter(company=company, po_number__startswith=prefix)
            .order_by('-po_number')
            .first()
        )
        if last:
            try:
                seq = int(last.po_number.rsplit('-', 1)[-1])
            except (ValueError, IndexError):
                seq = 0
        else:
            seq = 0
        return f'{prefix}{seq + 1:04d}'


@transaction.atomic
def release_production_order(production_order: ProductionOrder, user=None) -> ProductionOrder:
    from apps.mes.services.pipeline import PipelineError, advance_production_order

    if production_order.status != ProductionOrder.STATUS_DRAFT:
        raise POWorkflowError('Only draft production orders can be released.')
    try:
        return advance_production_order(
            production_order,
            ProductionOrder.STATUS_RELEASED,
            user=user,
            notes='Released to floor',
        )
    except PipelineError as exc:
        raise POWorkflowError(exc.message) from exc
