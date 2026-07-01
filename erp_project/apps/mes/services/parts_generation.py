"""Generate trackable parts from a production order BOM."""

from __future__ import annotations

import math
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q

from apps.mes.models import BOMItem, Part, ProductionOrder, WorkCenter
from apps.mes.services.barcode import save_part_barcode_image
from apps.mes.services.po import POWorkflowError


def get_first_production_step(company) -> WorkCenter | None:
    return (
        WorkCenter.objects.filter(
            company=company,
            is_active=True,
            is_production_step=True,
        )
        .order_by('sequence_order', 'pk')
        .first()
    )


def get_leaf_bom_items(production_order: ProductionOrder):
    return (
        BOMItem.objects.filter(
            production_order=production_order,
            company=production_order.company,
            is_active=True,
        )
        .annotate(
            active_child_count=Count(
                'children',
                filter=Q(children__is_active=True),
            ),
        )
        .filter(active_child_count=0)
        .order_by('id')
    )


def _target_part_count(bom_item: BOMItem, po_quantity: int) -> int:
    total = Decimal(str(bom_item.quantity)) * po_quantity
    return max(1, int(math.ceil(total)))


def _part_barcode(production_order: ProductionOrder, bom_item: BOMItem, sequence: int) -> str:
    slug = production_order.po_number.replace(' ', '-').upper()
    return f'{slug}-{bom_item.pk:04d}-{sequence:04d}'


@transaction.atomic
def generate_parts_from_bom(production_order: ProductionOrder) -> int:
    """
    Create parts for each leaf BOM line × PO quantity.
    Idempotent: only creates parts up to the required count per BOM line.
    """
    if not production_order.is_editable:
        raise POWorkflowError('Parts can only be generated while the order is in draft.')

    cutting = get_first_production_step(production_order.company)
    if not cutting:
        raise POWorkflowError('No production line work center configured (Cutting).')

    leaves = list(get_leaf_bom_items(production_order))
    if not leaves:
        raise POWorkflowError('Add BOM lines before generating parts.')

    created = 0
    for bom_item in leaves:
        target = _target_part_count(bom_item, production_order.quantity)
        existing = Part.objects.filter(
            production_order=production_order,
            bom_item=bom_item,
            is_active=True,
        ).count()
        for seq in range(existing + 1, target + 1):
            barcode = _part_barcode(production_order, bom_item, seq)
            if Part.objects.filter(company=production_order.company, barcode=barcode).exists():
                continue
            part = Part.objects.create(
                company=production_order.company,
                production_order=production_order,
                bom_item=bom_item,
                barcode=barcode,
                current_work_center=cutting,
                status=Part.STATUS_PENDING,
            )
            save_part_barcode_image(part)
            created += 1
    return created
