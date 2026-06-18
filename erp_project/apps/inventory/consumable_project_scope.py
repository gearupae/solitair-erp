"""Classify consumable request lines against a linked project's Items list."""
from __future__ import annotations

from decimal import Decimal

SCOPE_STANDARD = 'standard'
SCOPE_NEW_ITEM = 'new_item'
SCOPE_ADDITIONAL_QTY = 'additional_qty'

SCOPE_CLASSIFICATION_CHOICES = [
    (SCOPE_STANDARD, 'Standard project item request'),
    (SCOPE_NEW_ITEM, 'New additional item'),
    (SCOPE_ADDITIONAL_QTY, 'Additional quantity'),
]


def project_proposed_item_qty(project, item) -> Decimal | None:
    """Total proposed qty for this inventory item on the project, or None if not listed."""
    if not project or not item:
        return None
    from apps.projects.item_delivery import project_item_required_qty

    return project_item_required_qty(project, item)


def project_scope_item_map(project) -> dict[int, str]:
    """``{inventory_item_id: proposed_qty_str}`` for JS / form hints."""
    if not project:
        return {}
    from apps.projects.models import ProjectItemLine
    from django.db.models import Sum

    rows = (
        ProjectItemLine.objects.filter(project=project, inventory_item__isnull=False)
        .values('inventory_item_id')
        .annotate(total=Sum('quantity'))
        .order_by('inventory_item_id')
    )
    out = {}
    for row in rows:
        qty = row['total']
        if qty is not None:
            out[row['inventory_item_id']] = str(qty.quantize(Decimal('0.01')))
    return out


def classify_consumable_request_line(project, item, quantity) -> dict:
    """
    Compare a request line to the project Items list.

    Returns dict with keys: classification, proposed_qty, additional_qty, label, badge_class.
    """
    qty = Decimal(str(quantity or '0')).quantize(Decimal('0.01'))
    proposed = project_proposed_item_qty(project, item) if project and item else None

    if proposed is None:
        return {
            'classification': SCOPE_NEW_ITEM,
            'proposed_qty': None,
            'additional_qty': qty,
            'label': 'New additional item — not on the project Items list.',
            'badge_class': 'bg-warning text-dark',
            'badge_text': 'New addition',
        }

    proposed = proposed.quantize(Decimal('0.01'))
    if qty <= proposed:
        return {
            'classification': SCOPE_STANDARD,
            'proposed_qty': proposed,
            'additional_qty': Decimal('0.00'),
            'label': f'Standard request — item is on the project list (proposed {proposed}).',
            'badge_class': 'bg-light text-dark border',
            'badge_text': 'Standard',
        }

    extra = (qty - proposed).quantize(Decimal('0.01'))
    return {
        'classification': SCOPE_ADDITIONAL_QTY,
        'proposed_qty': proposed,
        'additional_qty': extra,
        'label': (
            f'Additional quantity — proposed on project is {proposed}; '
            f'{extra} is above the proposed amount.'
        ),
        'badge_class': 'bg-info text-dark',
        'badge_text': f'+{extra} additional',
    }


def pending_consumable_request_qty_by_item(project) -> dict[int, Decimal]:
    """Sum of qty on open consumable requests per inventory item for this project."""
    if not project:
        return {}
    from apps.inventory.models import ConsumableRequestItem
    from django.db.models import Sum

    rows = (
        ConsumableRequestItem.objects.filter(
            consumable_request__project=project,
            consumable_request__is_active=True,
            consumable_request__status__in=['pending', 'submitted', 'approved'],
        )
        .values('item_id')
        .annotate(total=Sum('quantity'))
    )
    return {
        row['item_id']: (row['total'] or Decimal('0')).quantize(Decimal('0.01'))
        for row in rows
    }


def attach_project_line_request_limits(item_lines, project) -> None:
    """Set max_request_qty / remaining_request_qty on each project item line."""
    from apps.inventory.models import Item
    from apps.projects.item_delivery import project_item_delivered_qty

    pending_by_item = pending_consumable_request_qty_by_item(project)
    proposed_by_item: dict[int, Decimal] = {}
    for line in item_lines:
        if not line.inventory_item_id:
            line.remaining_request_qty = None
            line.max_request_qty = None
            continue
        iid = line.inventory_item_id
        proposed_by_item[iid] = proposed_by_item.get(iid, Decimal('0')) + line.quantity

    delivered_by_item: dict[int, Decimal] = {}
    for iid in proposed_by_item:
        item = Item.objects.filter(pk=iid).first()
        if item:
            delivered_by_item[iid] = project_item_delivered_qty(project, item)
        else:
            delivered_by_item[iid] = Decimal('0')

    request_budget: dict[int, Decimal] = {}
    for iid, total_prop in proposed_by_item.items():
        pending = pending_by_item.get(iid, Decimal('0'))
        delivered = delivered_by_item.get(iid, Decimal('0'))
        request_budget[iid] = max(Decimal('0'), total_prop - delivered - pending)

    for line in item_lines:
        if not line.inventory_item_id:
            continue
        iid = line.inventory_item_id
        budget = request_budget.get(iid, Decimal('0'))
        line.max_request_qty = min(line.quantity, budget).quantize(Decimal('0.01'))
        request_budget[iid] = max(Decimal('0'), budget - line.max_request_qty)
        line.remaining_request_qty = request_budget.get(iid, Decimal('0'))


def apply_scope_to_consumable_request(consumable_request) -> None:
    """Persist scope classification on each line after save."""
    from apps.inventory.models import ConsumableRequestItem

    if not consumable_request.project_id:
        ConsumableRequestItem.objects.filter(consumable_request=consumable_request).update(
            scope_classification='',
            proposed_qty_at_request=None,
            additional_qty_at_request=None,
        )
        return

    from apps.projects.models import Project

    project = Project.objects.filter(pk=consumable_request.project_id).first()
    if not project:
        return

    for line in consumable_request.items.select_related('item'):
        if not line.item_id:
            continue
        info = classify_consumable_request_line(project, line.item, line.quantity)
        line.scope_classification = info['classification']
        line.proposed_qty_at_request = info['proposed_qty']
        extra = info['additional_qty']
        line.additional_qty_at_request = extra if extra and extra > 0 else None
        line.save(
            update_fields=[
                'scope_classification',
                'proposed_qty_at_request',
                'additional_qty_at_request',
            ]
        )
