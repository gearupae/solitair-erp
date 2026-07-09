"""Overhead exemption rules for estimate line items."""
from __future__ import annotations


def expense_type_exempt_from_overhead(expense_type_name: str | None) -> bool:
    """True when expense type is a pass-through expense or authority-fee bucket."""
    if not expense_type_name:
        return False
    low = expense_type_name.strip().lower()
    if 'authority' in low:
        return True
    if 'expense' in low:
        return True
    return False


def resolve_item_expense_type_name(item) -> str | None:
    from .estimate_pdf_groups import (
        _itemgroup_expense_type_by_name,
        get_service_item_expense_type_meta,
        get_untyped_group_expense_type_meta,
        resolve_item_expense_type,
    )

    expense_by_name = _itemgroup_expense_type_by_name()
    service_meta = get_service_item_expense_type_meta()
    untyped_meta = get_untyped_group_expense_type_meta()
    type_name, _sort = resolve_item_expense_type(
        item, expense_by_name, service_meta, untyped_meta
    )
    return type_name


def resolve_apply_overhead(item) -> bool:
    """
    Determine apply_overhead for a line.
    Always derived server-side; never user-editable.
    """
    if item.inventory_item_id:
        inv = item.inventory_item
        if inv is None and item.inventory_item_id:
            from apps.inventory.models import Item

            inv = Item.objects.filter(pk=item.inventory_item_id).first()
        if inv and getattr(inv, 'no_overhead', False):
            return False

    type_name = resolve_item_expense_type_name(item)
    if expense_type_exempt_from_overhead(type_name):
        return False

    return True


INVENTORY_UNIT_TO_ESTIMATE_UOM = {
    'pcs': 'units',
    'pc': 'units',
    'piece': 'units',
    'pieces': 'units',
    'units': 'units',
    'unit': 'units',
    'nos': 'units',
    'no': 'units',
    'ls': 'ls',
    'l.s': 'ls',
    'l.s.': 'ls',
    'rm': 'rm',
    'litre': 'litre',
    'liter': 'litre',
    'l': 'litre',
    'set': 'set',
    'sets': 'set',
    'mtr': 'mtr',
    'm': 'mtr',
    'meter': 'mtr',
    'metre': 'mtr',
    'meters': 'mtr',
    'metres': 'mtr',
}


def uom_from_inventory_unit(unit: str | None) -> str:
    if not unit:
        return ''
    key = unit.strip().lower()
    return INVENTORY_UNIT_TO_ESTIMATE_UOM.get(key, '')
