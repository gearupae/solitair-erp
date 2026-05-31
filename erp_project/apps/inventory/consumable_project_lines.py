"""Mirror approved consumable requests onto a project's Items table (ProjectItemLine)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Max


def sync_consumable_request_to_project_item_lines(consumable_request) -> int:
    """
    Append consumable lines to ``project.item_lines`` when ``consumable_request.project`` is set.

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
            rows.append((li.item, li.quantity, li.unit_cost))
    elif consumable_request.item_id and consumable_request.quantity:
        uc = consumable_request.unit_cost or Decimal('0')
        rows.append((consumable_request.item, consumable_request.quantity, uc))
    else:
        return 0

    agg = ProjectItemLine.objects.filter(project_id=project.pk).aggregate(mx=Max('sort_order'))
    sort_next = (agg['mx'] or 0) + 1

    bulk = []
    for item, qty, unit_cost in rows:
        if not item:
            continue
        uc = unit_cost or Decimal('0')
        if uc <= 0:
            uc = item.purchase_price or Decimal('0')
        qty = Item.normalize_quantity(item, qty or Decimal('0'))
        line_net = (qty * uc).quantize(Decimal('0.01'))
        bulk.append(
            ProjectItemLine(
                project_id=project.pk,
                sort_order=sort_next,
                group_name=group_name,
                description=(item.name or '')[:500],
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
