"""BOM display helpers."""

from __future__ import annotations

from collections import defaultdict

from apps.mes.models import BOMItem, ProductionOrder


def build_bom_tree(production_order: ProductionOrder) -> list[tuple[BOMItem, int]]:
    """Return (bom_item, depth) rows in tree order for indented display."""
    items = list(
        production_order.bom_items.filter(is_active=True).select_related('parent'),
    )
    by_parent: dict[int | None, list[BOMItem]] = defaultdict(list)
    for item in items:
        by_parent[item.parent_id].append(item)

    rows: list[tuple[BOMItem, int]] = []

    def walk(parent_id, depth):
        for item in sorted(by_parent.get(parent_id, []), key=lambda row: row.id):
            rows.append((item, depth))
            walk(item.pk, depth + 1)

    walk(None, 0)
    return rows
