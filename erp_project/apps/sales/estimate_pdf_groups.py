"""Group line items for estimate PDF rendering."""
from __future__ import annotations

from decimal import Decimal


def _itemgroup_hide_by_name():
    from apps.inventory.models import ItemGroup

    return {
        (g.name or '').strip().lower(): g.hide_items_on_pdf
        for g in ItemGroup.objects.all()
    }


def build_pdf_item_groups(estimate):
    """
    Ordered groups of estimate lines for PDF.
    Items sharing a group_name are merged into one section (order = first time
    that name appears on the estimate). Each entry: name, items, line_total,
    line_subtotal, hide_items_on_pdf (from inventory ItemGroup when names match).
    line_total is incl. VAT per line.
    """
    hide_by_name = _itemgroup_hide_by_name()
    group_order = []
    groups_by_name = {}

    for item in estimate.items.select_related('inventory_item').all():
        name = (item.group_name or '').strip()
        line_amt = (item.total or Decimal('0.00')) + (item.vat_amount or Decimal('0.00'))

        if name not in groups_by_name:
            group_order.append(name)
            groups_by_name[name] = {
                'name': name,
                'items': [],
                'line_total': Decimal('0.00'),
                'line_subtotal': Decimal('0.00'),
            }

        groups_by_name[name]['items'].append(item)
        groups_by_name[name]['line_total'] += line_amt
        groups_by_name[name]['line_subtotal'] += item.total or Decimal('0.00')

    groups = []
    row_index = 0
    for name in group_order:
        data = groups_by_name[name]
        hide_items = bool(name and hide_by_name.get(name.lower(), False))

        if hide_items:
            row_index += 1
            groups.append({
                'name': data['name'],
                'items': [],
                'line_total': data['line_total'],
                'line_subtotal': data['line_subtotal'],
                'hide_items_on_pdf': True,
                'collapsed_index': row_index,
            })
            continue

        numbered_items = []
        for item in data['items']:
            row_index += 1
            numbered_items.append({'item': item, 'index': row_index})

        groups.append({
            'name': data['name'],
            'items': numbered_items,
            'line_total': data['line_total'],
            'line_subtotal': data['line_subtotal'],
            'hide_items_on_pdf': False,
        })

    return groups
