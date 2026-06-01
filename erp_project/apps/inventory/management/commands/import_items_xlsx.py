"""
Import inventory items and groups from the medical-gas BOM Excel template.

Does not delete existing items or groups — creates or updates as needed.
Reuses existing items by name (case-insensitive) and can attach them to multiple groups.
"""
from __future__ import annotations

import random
import re
from decimal import Decimal

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.finance.models import TaxCode
from apps.inventory.models import Item, ItemGroup, ItemGroupMembership


def _cell_str(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _normalize_group_name(raw: str) -> str:
    name = re.sub(r'\s*\[Group name\]\s*$', '', raw.strip(), flags=re.IGNORECASE)
    name = ' '.join(name.split())
    if name.isupper() or (name.upper() == name and any(c.isalpha() for c in name)):
        return name.title()
    return name


def _normalize_item_name(raw: str) -> str:
    return ' '.join(raw.strip().split())


def _is_group_header(col_a) -> bool:
    if col_a is None:
        return False
    if isinstance(col_a, str):
        return '[group name]' in col_a.lower()
    return False


def _is_item_sl_number(col_a) -> bool:
    if col_a is None:
        return False
    if isinstance(col_a, (int, float)):
        return True
    s = str(col_a).strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_pdf_note(note: str) -> tuple[bool, bool]:
    """Return (hide_items_on_pdf, show_brand_hint)."""
    n = (note or '').lower()
    hide = 'hide items' in n
    show_brand = 'need display' in n
    return hide, show_brand


def _parse_qty(value) -> Decimal:
    if value is None or value == '':
        return Decimal('1')
    try:
        qty = Decimal(str(value))
    except Exception:
        return Decimal('1')
    if qty <= 0:
        return Decimal('1')
    return qty.quantize(Decimal('0.01'))


def parse_items_xlsx(path: str) -> list[dict]:
    """
    Parse workbook into a list of group dicts:
    {name, hide_items_on_pdf, items: [{name, qty, brand, sort_order}, ...]}
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    groups: list[dict] = []
    current: dict | None = None
    sort_order = 0

    for row in rows[1:]:
        if not row or not any(row[:6]):
            continue

        col_a, col_b, col_c, col_d, _col_e, col_f = (row + (None,) * 6)[:6]
        item_name = _normalize_item_name(_cell_str(col_b))
        pdf_note = _cell_str(col_f)
        hide_note, show_brand_note = _parse_pdf_note(pdf_note)

        if _is_group_header(col_a):
            current = {
                'name': _normalize_group_name(_cell_str(col_a)),
                'hide_items_on_pdf': hide_note,
                'items': [],
            }
            groups.append(current)
            sort_order = 0
            continue

        # Standalone group row: empty SL NO, name in column B (cabinet / maintenance lines).
        if not _is_item_sl_number(col_a) and item_name and col_a is None:
            sort_order = 0
            group = {
                'name': _normalize_group_name(item_name),
                'hide_items_on_pdf': hide_note,
                'items': [{
                    'name': _normalize_item_name(item_name),
                    'qty': _parse_qty(col_c),
                    'brand': _cell_str(col_d),
                    'sort_order': 0,
                }],
            }
            groups.append(group)
            current = None
            continue

        if not item_name:
            continue

        if current is None:
            raise CommandError(
                f'Item "{item_name}" at row without an active group header.'
            )

        if hide_note:
            current['hide_items_on_pdf'] = True

        current['items'].append({
            'name': item_name,
            'qty': _parse_qty(col_c),
            'brand': _cell_str(col_d),
            'sort_order': sort_order,
        })
        sort_order += 1

    wb.close()
    return groups


class Command(BaseCommand):
    help = 'Import inventory items and groups from item.xlsx (additive, no flush).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Path to item.xlsx',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Parse and report without saving',
        )

    def handle(self, *args, **options):
        path = options['file']
        dry_run = options['dry_run']

        try:
            parsed_groups = parse_items_xlsx(path)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if not parsed_groups:
            raise CommandError('No groups found in workbook.')

        tax_code = TaxCode.objects.filter(code='VAT5', is_active=True).first()
        if not tax_code:
            tax_code = TaxCode.objects.filter(rate=Decimal('5.00'), is_active=True).first()
        if not tax_code and not dry_run:
            raise CommandError('VAT 5% tax code (VAT5) not found. Run seed_tax_codes first.')

        self.stdout.write(
            f'Parsed {len(parsed_groups)} groups, '
            f'{sum(len(g["items"]) for g in parsed_groups)} item lines.'
        )

        stats = {
            'groups_created': 0,
            'groups_updated': 0,
            'items_created': 0,
            'items_reused': 0,
            'memberships_created': 0,
            'memberships_updated': 0,
        }

        item_cache: dict[str, Item] = {}

        def get_or_create_item(name: str, brand: str) -> Item:
            key = name.lower()
            if key in item_cache:
                item = item_cache[key]
                if brand and not item.brand:
                    item.brand = brand
                return item

            existing = Item.objects.filter(name__iexact=name, is_active=True).first()
            if existing:
                stats['items_reused'] += 1
                item = existing
                if brand and not item.brand:
                    item.brand = brand
            else:
                purchase = Decimal(str(random.randint(50, 500)))
                selling = purchase + Decimal(str(random.randint(10, 100)))
                item = Item(
                    name=name,
                    item_type='product',
                    status='active',
                    unit='pcs',
                    brand=brand or '',
                    purchase_price=purchase,
                    selling_price=selling,
                    tax_code=tax_code,
                )
                stats['items_created'] += 1

            item_cache[key] = item
            return item

        @transaction.atomic
        def run_import():
            for group_data in parsed_groups:
                group_name = group_data['name']
                group, created = ItemGroup.objects.get_or_create(name=group_name)
                if created:
                    stats['groups_created'] += 1
                else:
                    stats['groups_updated'] += 1

                hide = group_data.get('hide_items_on_pdf', False)
                if group.hide_items_on_pdf != hide:
                    group.hide_items_on_pdf = hide
                    group.save(update_fields=['hide_items_on_pdf'])

                for line in group_data['items']:
                    item = get_or_create_item(line['name'], line.get('brand', ''))
                    if item.pk is None:
                        item.save()

                    membership, mem_created = ItemGroupMembership.objects.get_or_create(
                        group=group,
                        item=item,
                        defaults={
                            'default_quantity': line['qty'],
                            'sort_order': line['sort_order'],
                        },
                    )
                    if mem_created:
                        stats['memberships_created'] += 1
                    else:
                        changed = False
                        if membership.default_quantity != line['qty']:
                            membership.default_quantity = line['qty']
                            changed = True
                        if membership.sort_order != line['sort_order']:
                            membership.sort_order = line['sort_order']
                            changed = True
                        if changed:
                            membership.save()
                            stats['memberships_updated'] += 1

            # Persist brand updates on reused items
            for item in item_cache.values():
                if item.pk and item.brand:
                    Item.objects.filter(pk=item.pk).update(brand=item.brand)

            if dry_run:
                transaction.set_rollback(True)

        run_import()

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Import complete — '
            f'groups: {stats["groups_created"]} created, {stats["groups_updated"]} existing; '
            f'items: {stats["items_created"]} created, {stats["items_reused"]} reused; '
            f'memberships: {stats["memberships_created"]} created, '
            f'{stats["memberships_updated"]} updated.'
        ))
