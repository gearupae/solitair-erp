"""Group line items for estimate PDF rendering."""
from __future__ import annotations

from decimal import Decimal


def _itemgroup_hide_by_name():
    from apps.inventory.models import ItemGroup

    return {
        (g.name or '').strip().lower(): g.hide_items_on_pdf
        for g in ItemGroup.objects.all()
    }


def _itemgroup_expense_type_by_name():
    from apps.inventory.models import ItemGroup

    result = {}
    for g in ItemGroup.objects.select_related('expense_type').filter(expense_type__isnull=False):
        key = (g.name or '').strip().lower()
        if not key or not g.expense_type_id:
            continue
        result[key] = {
            'expense_type_name': g.expense_type.name,
            'expense_type_sort_order': g.expense_type.sort_order,
        }
    return result


def build_expense_type_totals(item_groups):
    """
    Totals by expense type (incl. VAT) for estimate sections whose inventory
    sub-group has an expense type assigned. item_groups: build_pdf_item_groups.
    """
    expense_by_name = _itemgroup_expense_type_by_name()
    by_type = {}
    for grp in item_groups:
        name = (grp.get('name') or '').strip()
        if not name:
            continue
        meta = expense_by_name.get(name.lower())
        if not meta:
            continue
        type_name = meta['expense_type_name']
        entry = by_type.setdefault(type_name, {
            'expense_type_name': type_name,
            'expense_type_sort_order': meta['expense_type_sort_order'],
            'line_total': Decimal('0.00'),
        })
        entry['line_total'] += grp.get('line_total') or Decimal('0.00')

    totals = list(by_type.values())
    totals.sort(key=lambda row: (row['expense_type_sort_order'], row['expense_type_name']))
    return totals


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


def build_pdf_item_groups_for_line_items(line_items):
    """Same grouping as build_pdf_item_groups, for snapshot / mock line rows."""
    hide_by_name = _itemgroup_hide_by_name()
    group_order = []
    groups_by_name = {}

    for item in line_items:
        name = (getattr(item, 'group_name', None) or '').strip()
        line_amt = (getattr(item, 'total', None) or Decimal('0.00')) + (
            getattr(item, 'vat_amount', None) or Decimal('0.00')
        )

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
        groups_by_name[name]['line_subtotal'] += getattr(item, 'total', None) or Decimal('0.00')

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
