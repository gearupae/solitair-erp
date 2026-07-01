"""Build indented BOM tree for product templates."""

from apps.mes.models import ProductTemplate, TemplateBOMItem


def build_template_bom_tree(template: ProductTemplate) -> list[tuple[TemplateBOMItem, int]]:
    items = list(
        template.bom_items.filter(is_active=True).select_related('parent', 'inventory_item'),
    )
    by_parent: dict[int | None, list] = {}
    for item in items:
        by_parent.setdefault(item.parent_id, []).append(item)

    result: list[tuple[TemplateBOMItem, int]] = []

    def walk(parent_id, depth):
        for item in sorted(by_parent.get(parent_id, []), key=lambda x: x.id):
            result.append((item, depth))
            walk(item.pk, depth + 1)

    walk(None, 0)
    return result
