"""Copy product template BOM + routing into a production order snapshot."""

from __future__ import annotations

from django.core.files.base import ContentFile

from apps.mes.models import (
    BOMItem,
    Drawing,
    ProductTemplate,
    ProductionOrder,
    RoutingOperation,
    TemplateBOMItem,
    TemplateDrawing,
    TemplateRoutingOp,
)


def copy_template_to_production_order(
    template: ProductTemplate,
    production_order: ProductionOrder,
) -> tuple[int, int]:
    """
    Deep-copy template BOM tree and routing into the PO.
    Returns (bom_lines_created, routing_ops_created).
    """
    production_order.source_template_name = template.name
    production_order.product_template = template
    production_order.save(update_fields=['source_template_name', 'product_template', 'updated_at'])

    parent_map: dict[int, BOMItem] = {}
    bom_count = 0
    template_bom = TemplateBOMItem.objects.filter(
        template=template,
        company=template.company,
        is_active=True,
    ).select_related('inventory_item', 'parent').order_by('id')

    for line in template_bom:
        new_parent = parent_map.get(line.parent_id) if line.parent_id else None
        inv = line.inventory_item
        unit_cost = inv.purchase_price if inv else 0
        bom = BOMItem.objects.create(
            company=production_order.company,
            production_order=production_order,
            parent=new_parent,
            part_name=line.part_name,
            material_type=line.material_type,
            quantity=line.quantity,
            unit=line.unit,
            item_code=line.item_code or (inv.item_code if inv else ''),
            inventory_item=inv,
            unit_cost=unit_cost,
        )
        parent_map[line.pk] = bom
        bom_count += 1

    _copy_template_drawings(
        production_order=production_order,
        template=template,
        parent_map=parent_map,
    )

    routing_count = 0
    for op in TemplateRoutingOp.objects.filter(
        template=template,
        company=template.company,
        is_active=True,
    ).select_related('work_center').order_by('sequence', 'id'):
        RoutingOperation.objects.create(
            company=production_order.company,
            production_order=production_order,
            work_center=op.work_center,
            sequence=op.sequence,
            std_time_minutes=op.std_time_minutes,
            rate_per_hour=op.work_center.cost_per_hour,
            status=RoutingOperation.STATUS_PENDING,
        )
        routing_count += 1

    return bom_count, routing_count


def _copy_template_drawings(
    *,
    production_order: ProductionOrder,
    template: ProductTemplate,
    parent_map: dict[int, BOMItem],
) -> None:
    """Copy default template drawings onto matching PO BOM lines (draft, not released)."""
    template_drawings = TemplateDrawing.objects.filter(
        template_bom_item__template=template,
        template_bom_item__company=template.company,
        is_active=True,
    ).select_related('template_bom_item')

    for td in template_drawings:
        bom_item = parent_map.get(td.template_bom_item_id)
        if not bom_item or not td.file:
            continue
        filename = td.file.name.rsplit('/', 1)[-1]
        drawing = Drawing(
            company=production_order.company,
            bom_item=bom_item,
            title=td.title,
            version=td.version,
            is_released=False,
        )
        with td.file.open('rb') as src:
            drawing.file.save(filename, ContentFile(src.read()), save=False)
        drawing.save()
