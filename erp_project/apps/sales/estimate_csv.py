"""
CSV import for estimate line items (inventory item_code–based).
No sort_order / tax_code / VAT inclusive in file — sort order is row order;
lines use VAT 5% (standard) and VAT-inclusive pricing by default.
"""
import csv
import io
from decimal import Decimal, InvalidOperation

from apps.finance.models import TaxCode
from apps.inventory.models import Item


# Headers (case-insensitive). No VAT columns; tax fixed to VAT 5% inclusive.
ESTIMATE_ITEMS_CSV_HEADERS = [
    'item_code',
    'group_name',
    'description',
    'quantity',
    'unit_price',
    'profit_percent',
    'profit_amount',
    'uom',
    'installation_selling_cost',
    'apply_overhead',
]


def _norm_header(s):
    return (s or '').strip().lower().replace(' ', '_')


def _dec(val, default=None):
    if val is None or str(val).strip() == '':
        return default
    try:
        return Decimal(str(val).strip().replace(',', ''))
    except (InvalidOperation, ValueError):
        return default


def _resolve_profit(row):
    """
    If profit_percent is non-empty → percent.
    Else if profit_amount is non-empty → amount.
    Else → none / 0.
    If both non-empty, percent wins.
    """
    pp = _dec(row.get('profit_percent'))
    pa = _dec(row.get('profit_amount'))
    if pp is not None and pp != 0:
        return 'percent', pp
    if pa is not None and pa != 0:
        return 'amount', pa
    if pp is not None:
        return 'percent', pp
    if pa is not None:
        return 'amount', pa
    return 'none', Decimal('0')


def get_default_estimate_csv_tax_code():
    """
    VAT 5% standard (seed code VAT5). Fallback: default flag, then any 5% standard rate.
    """
    tc = TaxCode.objects.filter(is_active=True, code__iexact='VAT5').first()
    if tc:
        return tc
    tc = TaxCode.objects.filter(is_active=True, is_default=True).first()
    if tc:
        return tc
    tc = (
        TaxCode.objects.filter(is_active=True, tax_type='standard', rate=Decimal('5.00'))
        .order_by('code')
        .first()
    )
    return tc


def parse_estimate_items_csv(file_obj):
    """
    Parse uploaded CSV into kwargs for EstimateItem.objects.create (unsaved).
    Always applies VAT 5% (standard) tax code and VAT-inclusive line pricing.
    sort_order follows CSV row order (0-based).
    Raises ValueError with user-facing message on failure.
    """
    from .models import EstimateItem

    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise ValueError('CSV has no header row.')

    headers = [_norm_header(h) for h in reader.fieldnames]
    if 'item_code' not in headers:
        raise ValueError('CSV must include an "item_code" column.')

    items_by_code = {}
    codes_needed = set()
    rows_in = []
    for r in reader:
        if not any((v or '').strip() for v in r.values()):
            continue
        row = {_norm_header(k): (v or '').strip() for k, v in r.items()}
        code = row.get('item_code', '').strip()
        if not code:
            raise ValueError('Each data row must have item_code.')
        codes_needed.add(code)
        rows_in.append(row)

    if not rows_in:
        raise ValueError('No data rows found in CSV.')

    found = Item.objects.filter(is_active=True, item_code__in=list(codes_needed)).select_related('tax_code')
    for it in found:
        items_by_code[it.item_code] = it
    missing = codes_needed - set(items_by_code.keys())
    if missing:
        raise ValueError(f'Unknown or inactive item_code(s): {", ".join(sorted(missing))}')

    default_tax = get_default_estimate_csv_tax_code()
    if not default_tax:
        raise ValueError(
            'No VAT 5% tax code found. Run finance tax seed or create an active TaxCode VAT5 (5%).'
        )

    out = []
    for idx, row in enumerate(rows_in):
        code = row['item_code'].strip()
        inv = items_by_code[code]
        qty = _dec(row.get('quantity'), Decimal('1'))
        if qty is None or qty <= 0:
            raise ValueError(f'Row {idx + 2}: quantity must be > 0.')

        base = _dec(row.get('unit_price'))
        if base is None:
            base = inv.selling_price or Decimal('0')
        if base < 0:
            raise ValueError(f'Row {idx + 2}: unit_price cannot be negative.')

        ptype, pval = _resolve_profit(row)

        desc = row.get('description', '').strip() or inv.name
        group_name = row.get('group_name', '').strip()
        uom_raw = row.get('uom', '').strip().lower()
        uom = uom_raw if uom_raw in dict(EstimateItem.UOM_CHOICES) else ''
        if not uom:
            from .estimate_overhead import uom_from_inventory_unit
            uom = uom_from_inventory_unit(inv.unit)

        install_selling = _dec(row.get('installation_selling_cost'))
        from .estimate_overhead import resolve_apply_overhead
        apply_overhead = resolve_apply_overhead(
            EstimateItem(inventory_item=inv, group_name=group_name),
        )

        out.append(
            {
                'inventory_item_id': inv.pk,
                'group_name': group_name,
                'sort_order': idx,
                'description': desc[:500],
                'quantity': qty,
                'unit_price': base,
                'profit_type': ptype,
                'profit_value': pval,
                'uom': uom,
                'apply_overhead': apply_overhead,
                'installation_selling_cost': install_selling or Decimal('0'),
                'tax_code_id': default_tax.pk,
                'is_vat_inclusive': True,
            }
        )
    return out


def bulk_create_estimate_items(estimate, rows, replace_existing=False):
    """Persist parsed CSV rows as EstimateItem lines."""
    from .models import EstimateItem

    if replace_existing:
        estimate.items.all().delete()
    for data in rows:
        d = dict(data)
        inv_id = d.pop('inventory_item_id')
        tc_id = d.pop('tax_code_id')
        EstimateItem.objects.create(
            estimate=estimate,
            inventory_item_id=inv_id,
            tax_code_id=tc_id,
            **d,
        )
    estimate.calculate_totals()


def sample_csv_content():
    """UTF-8 BOM string for download."""
    buf = io.StringIO()
    buf.write('\ufeff')
    w = csv.writer(buf)
    w.writerow(ESTIMATE_ITEMS_CSV_HEADERS)
    w.writerow(
        [
            'ITEM-0001',
            'Section A',
            'Optional description override',
            '2',
            '100.00',
            '15',
            '',
        ]
    )
    w.writerow(
        [
            'ITEM-0002',
            'Section A',
            '',
            '1',
            '',
            '',
            '50.00',
        ]
    )
    return buf.getvalue()
