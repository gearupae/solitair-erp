"""Mirror approved consumable requests onto a project's Items table (ProjectItemLine)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Max

from apps.inventory.consumable_project_scope import (
    SCOPE_ADDITIONAL_QTY,
    SCOPE_NEW_ITEM,
    SCOPE_STANDARD,
    classify_consumable_request_line,
)


def _estimate_base_unit_cost(project, item) -> Decimal:
    """Project scope base price (estimate unit_price) for this inventory item."""
    from apps.projects.item_delivery import _project_item_budget_unit_cost

    return _project_item_budget_unit_cost(project, item)


def sync_consumable_request_to_project_item_lines(consumable_request) -> int:
    """
    Append consumable lines to ``project.item_lines`` when ``consumable_request.project`` is set.

    Standard scope items are skipped (they already exist on the project from the estimate;
    stock is delivered via ``deliver_items_to_project`` on dispense).

    Uses ``group_name`` ``Consumable — {request_number}`` so the same request is not duplicated
    if sync runs from both approve and dispense workflows.

    Returns the number of ``ProjectItemLine`` rows created.
    """
    from apps.projects.models import ProjectItemLine
    from apps.inventory.models import Item

    project = consumable_request.project
    if not project:
        return 0

    group_name = f'Consumable — {consumable_request.request_number}'[:200]
    if ProjectItemLine.objects.filter(project_id=project.pk, group_name=group_name).exists():
        return 0

    rows: list[tuple] = []
    if consumable_request.items.exists():
        for li in consumable_request.items.select_related('item'):
            if not li.item_id:
                continue
            info = classify_consumable_request_line(project, li.item, li.quantity)
            if info['classification'] == SCOPE_STANDARD:
                continue
            qty = li.quantity
            if info['classification'] == SCOPE_ADDITIONAL_QTY:
                qty = info['additional_qty']
            if not qty or qty <= 0:
                continue
            base_uc = _estimate_base_unit_cost(project, li.item)
            uc = base_uc if base_uc > 0 else (li.unit_cost or Decimal('0'))
            rows.append((li.item, qty, uc, info['classification']))
    elif consumable_request.item_id and consumable_request.quantity:
        item = consumable_request.item
        info = classify_consumable_request_line(project, item, consumable_request.quantity)
        if info['classification'] == SCOPE_STANDARD:
            return 0
        qty = consumable_request.quantity
        if info['classification'] == SCOPE_ADDITIONAL_QTY:
            qty = info['additional_qty']
        base_uc = _estimate_base_unit_cost(project, item)
        uc = base_uc if base_uc > 0 else (consumable_request.unit_cost or Decimal('0'))
        rows.append((item, qty, uc, info['classification']))
    else:
        return 0

    agg = ProjectItemLine.objects.filter(project_id=project.pk).aggregate(mx=Max('sort_order'))
    sort_next = (agg['mx'] or 0) + 1

    bulk = []
    for item, qty, unit_cost, classification in rows:
        if not item:
            continue
        uc = unit_cost or Decimal('0')
        if uc <= 0:
            uc = item.selling_price or item.purchase_price or Decimal('0')
        qty = Item.normalize_quantity(item, qty or Decimal('0'))
        line_net = (qty * uc).quantize(Decimal('0.01'))
        desc = (item.name or '')[:500]
        if classification == SCOPE_ADDITIONAL_QTY:
            desc = f'{desc} (additional qty)'[:500]
        elif classification == SCOPE_NEW_ITEM:
            desc = f'{desc} (consumable addition)'[:500]
        bulk.append(
            ProjectItemLine(
                project_id=project.pk,
                sort_order=sort_next,
                group_name=group_name,
                description=desc,
                inventory_item=item,
                quantity=qty,
                unit_price=uc,
                rate=uc,
                line_net=line_net,
                vat_amount=Decimal('0'),
            )
        )
        sort_next += 1

    if not bulk:
        return 0
    ProjectItemLine.objects.bulk_create(bulk)
    return len(bulk)
