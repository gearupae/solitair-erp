"""Render revision snapshots (HTML detail + PDF from stored JSON)."""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.core.files.base import ContentFile
from django.template.loader import get_template

from .estimate_pdf_groups import build_pdf_item_groups_for_line_items
from .models import EstimateRevisionSnapshot

logger = logging.getLogger(__name__)


def _decimal(value, default='0'):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _attach_snapshot_line_calc(item_ns: SimpleNamespace) -> SimpleNamespace:
    """Add computed line breakdown attrs for PDF/detail (snapshot rows)."""
    from .models import EstimateItem

    tmp = EstimateItem(
        quantity=item_ns.quantity,
        unit_price=item_ns.unit_price,
        installation_cost=getattr(item_ns, 'installation_cost', Decimal('0')),
        selling_cost=getattr(item_ns, 'selling_cost', None) or item_ns.unit_price,
        profit_type=item_ns.profit_type or 'none',
        vat_rate=item_ns.vat_rate or Decimal('0'),
        is_vat_inclusive=False,
    )
    tmp.apply_profit_from_selling_cost()
    item_ns.line_profit_amount = tmp.line_profit_amount
    item_ns.line_calc_summary = tmp.line_calc_summary
    item_ns.line_total_incl_vat = tmp.line_total_incl_vat
    item_ns.line_net_excl_vat = tmp.line_net_excl_vat
    item_ns.effective_rate = tmp.effective_rate
    return item_ns


def snapshot_item_from_dict(row: dict) -> SimpleNamespace:
    code = row.get('inventory_item_code') or ''
    brand = row.get('brand') or ''
    inv = SimpleNamespace(item_code=code, brand='') if code else None
    item = SimpleNamespace(
        description=row.get('description', ''),
        quantity=_decimal(row.get('quantity')),
        unit_price=_decimal(row.get('unit_price')),
        profit_type=row.get('profit_type', ''),
        profit_value=_decimal(row.get('profit_value')),
        rate=_decimal(row.get('rate')),
        total=_decimal(row.get('total')),
        vat_amount=_decimal(row.get('vat_amount')),
        group_name=row.get('group_name', ''),
        group_qty_multiplier=_decimal(row.get('group_qty_multiplier'), '1'),
        brand=brand,
        installation_cost=_decimal(row.get('installation_cost')),
        selling_cost=_decimal(row.get('selling_cost'), row.get('rate')),
        inventory_item=inv,
        display_brand=brand,
        vat_rate=Decimal('0'),
    )
    return _attach_snapshot_line_calc(item)


def group_snapshot_items_for_display(items_data: list) -> list[dict]:
    """Group snapshot line rows for the revision detail template."""
    group_order: list[str] = []
    groups_by_name: dict[str, dict] = {}

    for row in items_data or []:
        name = (row.get('group_name') or '').strip()
        if name not in groups_by_name:
            group_order.append(name)
            groups_by_name[name] = {'name': name, 'items': []}
        groups_by_name[name]['items'].append(snapshot_item_from_dict(row))

    return [groups_by_name[name] for name in group_order]


class SnapshotEstimateProxy:
    """Estimate-like object for PDF rendering from revision snapshot JSON."""

    def __init__(self, live_estimate, snapshot: EstimateRevisionSnapshot):
        data = snapshot.snapshot_data or {}
        self._live = live_estimate
        self.pk = live_estimate.pk
        self.customer = live_estimate.customer
        self.assigned_to = live_estimate.assigned_to
        self.project = live_estimate.project
        self.show_rates_on_pdf = live_estimate.show_rates_on_pdf
        self.show_brand_name_on_pdf = live_estimate.show_brand_name_on_pdf
        self.show_installation_cost_on_pdf = live_estimate.show_installation_cost_on_pdf
        self.show_group_totals_on_pdf = live_estimate.show_group_totals_on_pdf
        self.authorized_signature = None
        self.customer_signature = None
        self.notes = live_estimate.notes
        self.prepared_by = live_estimate.prepared_by

        self.status = snapshot.status_at_snapshot or data.get('status', live_estimate.status)
        self.subtotal = _decimal(data.get('subtotal', live_estimate.subtotal))
        self.discount_applied = _decimal(data.get('discount_applied', live_estimate.discount_applied))
        self.vat_amount = _decimal(data.get('vat_amount', live_estimate.vat_amount))
        self.total_amount = _decimal(data.get('total_amount', snapshot.total_amount))
        self.scope_of_work = data.get('scope_of_work', live_estimate.scope_of_work)
        self.type_of_work = data.get('type_of_work', live_estimate.type_of_work)
        self.type_of_occupancy = data.get('type_of_occupancy', live_estimate.type_of_occupancy)
        self.client_note = data.get('client_note', live_estimate.client_note)
        self.terms_and_conditions = data.get('terms_and_conditions', live_estimate.terms_and_conditions)

        self._display_number = data.get('display_estimate_number') or snapshot.display_number
        self._items = [snapshot_item_from_dict(r) for r in data.get('items', [])]
        self.date = _parse_iso_date(data.get('date')) or live_estimate.date
        self.valid_until = _parse_iso_date(data.get('valid_until')) or live_estimate.valid_until

    @property
    def display_estimate_number(self):
        return self._display_number

    @property
    def items(self):
        return _SnapshotItemsQuerySet(self._items)

    def get_status_display(self):
        from .models import Estimate

        return dict(Estimate.STATUS_CHOICES).get(self.status, self.status)

    def get_type_of_occupancy_display(self):
        return self._live.get_type_of_occupancy_display()

    def get_type_of_work_display(self):
        return self._live.get_type_of_work_display()

    @property
    def scope_of_work_label(self):
        return self._live.scope_of_work_label if hasattr(self._live, 'scope_of_work_label') else self.scope_of_work

    def build_vat_summary(self) -> dict:
        subtotal = self.subtotal
        vat = self.vat_amount
        if subtotal > 0 and vat > 0:
            rate = float((vat / subtotal * Decimal('100')).quantize(Decimal('0.01')))
            return {rate: {'taxable': float(subtotal), 'vat': float(vat)}}
        return {}


class _SnapshotItemsQuerySet:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def select_related(self, *args, **kwargs):
        return self


def _parse_iso_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def render_revision_snapshot_pdf_bytes(request, snapshot: EstimateRevisionSnapshot):
    """Render quotation PDF from stored snapshot JSON."""
    try:
        from weasyprint import HTML
    except ImportError:
        return None, 'WeasyPrint is not installed; cannot generate PDF.'

    from .views import _build_estimate_pdf_context

    proxy = SnapshotEstimateProxy(snapshot.estimate, snapshot)
    data = snapshot.snapshot_data or {}
    line_items = [snapshot_item_from_dict(r) for r in data.get('items', [])]

    context = _build_estimate_pdf_context(request, proxy, for_weasyprint=True)
    context['pdf_item_groups'] = build_pdf_item_groups_for_line_items(line_items)
    context.update(
        {
            'document_heading': 'QUOTATION',
            'document_number': snapshot.display_number,
            'page_title': f'Quotation — {snapshot.display_number}',
            'print_button_label': 'Print quotation',
            'show_pdf_status': True,
            'pdf_variant': 'quotation',
            'pdf_details_heading': 'Quotation details',
            'pdf_date_label': 'Quotation date',
            'is_revision_snapshot': True,
        }
    )

    template = get_template('sales/estimate_pdf.html')
    html_string = template.render(context)
    host = request.META.get('HTTP_HOST') or 'localhost'
    base_url = request.build_absolute_uri('/') if hasattr(request, 'build_absolute_uri') else f'http://{host}/'
    html = HTML(string=html_string, base_url=base_url)
    return html.write_pdf(), None


def ensure_revision_snapshot_pdf(request, snapshot: EstimateRevisionSnapshot) -> bool:
    """Generate and persist PDF for a snapshot if missing. Returns True when a file exists."""
    if snapshot.pdf_file:
        return True

    pdf_bytes, err = render_revision_snapshot_pdf_bytes(request, snapshot)
    if not pdf_bytes:
        if err:
            logger.warning(
                'Revision snapshot PDF failed (estimate=%s snapshot=%s): %s',
                snapshot.estimate_id,
                snapshot.pk,
                err,
            )
        return False

    label = snapshot.revision_label or 'original'
    filename = f'{snapshot.estimate.estimate_number}-{label}.pdf'
    snapshot.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
    return True


def revision_snapshot_detail_context(snapshot: EstimateRevisionSnapshot) -> dict:
    data = snapshot.snapshot_data or {}
    return {
        'data': data,
        'item_groups': group_snapshot_items_for_display(data.get('items', [])),
        'snapshot_date': _parse_iso_date(data.get('date')),
        'snapshot_valid_until': _parse_iso_date(data.get('valid_until')),
        'subtotal': _decimal(data.get('subtotal')),
        'discount_applied': _decimal(data.get('discount_applied')),
        'vat_amount': _decimal(data.get('vat_amount')),
        'total_amount': _decimal(data.get('total_amount', snapshot.total_amount)),
    }
