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
            'line_subtotal': Decimal('0.00'),
            'profit_amount': Decimal('0.00'),
        })
        entry['line_total'] += grp.get('line_total') or Decimal('0.00')
        entry['line_subtotal'] += grp.get('line_subtotal') or Decimal('0.00')
        for row in grp.get('items') or []:
            item = row.get('item') if isinstance(row, dict) else row
            entry['profit_amount'] += getattr(item, 'line_profit_amount', Decimal('0.00'))

    totals = list(by_type.values())
    totals.sort(key=lambda row: (row['expense_type_sort_order'], row['expense_type_name']))
    return totals


def build_consolidated_installation_summary(estimate):
    """Sum of qty × unit installation cost across all lines (expense bucket)."""
    net = Decimal('0.00')
    vat = Decimal('0.00')
    for item in estimate.items.all():
        inst_net = item.net_installation_cost
        if inst_net <= 0:
            continue
        net += inst_net
        line_vat = (inst_net * (item.vat_rate or Decimal('0')) / Decimal('100')).quantize(
            Decimal('0.01')
        )
        vat += line_vat
    net = net.quantize(Decimal('0.01'))
    vat = vat.quantize(Decimal('0.01'))
    if net <= 0:
        return None
    return {
        'expense_type_name': 'Installation cost',
        'expense_type_sort_order': 9999,
        'line_subtotal': net,
        'line_total': net + vat,
        'pre_profit_subtotal': net,
        'profit_amount': Decimal('0.00'),
        'profit_percent': Decimal('0.00'),
        'is_installation_summary': True,
    }


def build_expense_type_totals_for_estimate(estimate):
    """Expense-type totals from line items (incl. VAT, profit, net excl. VAT)."""
    expense_by_name = _itemgroup_expense_type_by_name()
    by_type = {}
    for item in estimate.items.all():
        name = (item.group_name or '').strip()
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
            'line_subtotal': Decimal('0.00'),
            'pre_profit_subtotal': Decimal('0.00'),
            'profit_amount': Decimal('0.00'),
        })
        entry['line_total'] += item.line_total_incl_vat
        entry['line_subtotal'] += item.line_net_excl_vat
        entry['pre_profit_subtotal'] += item.line_pre_profit_subtotal
        entry['profit_amount'] += item.line_profit_amount

    totals = list(by_type.values())
    for row in totals:
        pre = row['pre_profit_subtotal']
        profit = row['profit_amount']
        if pre > 0 and profit > 0:
            row['profit_percent'] = (profit / pre * Decimal('100')).quantize(Decimal('0.01'))
        else:
            row['profit_percent'] = Decimal('0.00')
    install_row = build_consolidated_installation_summary(estimate)
    if install_row:
        totals.append(install_row)
    totals.sort(key=lambda row: (row['expense_type_sort_order'], row['expense_type_name']))
    return totals


def build_estimate_profit_summary(estimate):
    """Total profit added on lines and overall margin on pre-profit subtotal."""
    pre = Decimal('0.00')
    profit = Decimal('0.00')
    for item in estimate.items.all():
        pre += item.line_pre_profit_subtotal
        profit += item.line_profit_amount
    pre = pre.quantize(Decimal('0.01'))
    profit = profit.quantize(Decimal('0.01'))
    pct = (profit / pre * Decimal('100')) if pre > 0 else Decimal('0.00')
    return {
        'pre_profit_subtotal': pre,
        'profit_total': profit,
        'profit_percent': pct.quantize(Decimal('0.01')),
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
        line_amt = item.line_total_incl_vat

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
        groups_by_name[name]['line_subtotal'] += item.line_net_excl_vat

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
