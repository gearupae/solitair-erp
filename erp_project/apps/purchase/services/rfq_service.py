"""
RFQ / Competitive Purchase Analysis — quote comparison, award, PO conversion.
"""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.purchase.models import PurchaseOrder, PurchaseOrderItem, Vendor
from apps.purchase.models_rfq import RFQ, RFQAwardLine, RFQLine, SupplierQuote, SupplierQuoteLine


def build_comparison_matrix(rfq: RFQ) -> dict:
    """RFQ lines as rows, suppliers as columns."""
    lines = list(rfq.lines.select_related('item').order_by('sort_order', 'id'))
    quotes = list(
        rfq.quotes.prefetch_related('lines__rfq_line', 'supplier').order_by('supplier__name')
    )

    suppliers = [q.supplier for q in quotes]
    rows = []
    for rfq_line in lines:
        cells = []
        prices = []
        leads = []
        for quote in quotes:
            ql = quote.lines.filter(rfq_line=rfq_line).first()
            unit_price = ql.unit_price if ql else None
            line_total = ql.line_total if ql else None
            lead = ql.line_lead_time_days if ql and ql.line_lead_time_days else quote.lead_time_days
            cells.append({
                'quote_id': quote.pk,
                'supplier_id': quote.supplier_id,
                'supplier_name': quote.supplier.name,
                'unit_price': float(unit_price) if unit_price is not None else None,
                'line_total': float(line_total) if line_total is not None else None,
                'lead_time_days': lead,
            })
            if unit_price is not None:
                prices.append((unit_price, quote.supplier_id))
            if lead is not None:
                leads.append((lead, quote.supplier_id))

        lowest_price_supplier = min(prices)[1] if prices else None
        shortest_lead_supplier = min(leads)[1] if leads else None

        rows.append({
            'rfq_line_id': rfq_line.pk,
            'description': rfq_line.description,
            'quantity': float(rfq_line.quantity),
            'unit': rfq_line.unit,
            'cells': cells,
            'lowest_price_supplier_id': lowest_price_supplier,
            'shortest_lead_supplier_id': shortest_lead_supplier,
        })

    return {
        'rfq_id': rfq.pk,
        'rfq_number': rfq.rfq_number,
        'suppliers': [{'id': s.pk, 'name': s.name} for s in suppliers],
        'rows': rows,
    }


@transaction.atomic
def award_rfq(rfq: RFQ, user, awards: list, justification: str, award_notes: str = ''):
    """
    awards: list of dicts {rfq_line_id, supplier_id, awarded_qty, unit_price, quote_line_id?}
    """
    if rfq.status not in (RFQ.STATUS_QUOTES_RECEIVED, RFQ.STATUS_SENT):
        raise ValidationError('RFQ must have quotes before award.')

    RFQAwardLine.objects.filter(rfq=rfq).delete()
    for aw in awards:
        rfq_line = RFQLine.objects.get(pk=aw['rfq_line_id'], rfq=rfq)
        supplier = Vendor.objects.get(pk=aw['supplier_id'])
        RFQAwardLine.objects.create(
            rfq=rfq,
            rfq_line=rfq_line,
            supplier=supplier,
            supplier_quote_line_id=aw.get('quote_line_id'),
            awarded_qty=Decimal(str(aw['awarded_qty'])),
            unit_price=Decimal(str(aw['unit_price'])),
        )

    rfq.status = RFQ.STATUS_AWARDED
    rfq.award_justification = justification
    rfq.award_notes = award_notes
    rfq.awarded_by = user
    rfq.awarded_at = timezone.now()
    rfq.save()
    return rfq


@transaction.atomic
def convert_awards_to_pos(rfq: RFQ, user) -> list:
    """Create one PO per awarded supplier."""
    if rfq.status != RFQ.STATUS_AWARDED:
        raise ValidationError('RFQ must be awarded before PO conversion.')

    awards = rfq.awards.select_related('supplier', 'rfq_line__item').order_by('supplier_id')
    by_supplier: dict[int, list] = {}
    for aw in awards:
        by_supplier.setdefault(aw.supplier_id, []).append(aw)

    pos = []
    for supplier_id, supplier_awards in by_supplier.items():
        po = PurchaseOrder.objects.create(
            vendor_id=supplier_id,
            order_date=date.today(),
            status='draft',
            created_by=user,
            notes=f'From RFQ {rfq.rfq_number}',
        )
        for aw in supplier_awards:
            item = aw.rfq_line.item
            PurchaseOrderItem.objects.create(
                purchase_order=po,
                description=aw.rfq_line.description,
                quantity=aw.awarded_qty,
                unit_price=aw.unit_price,
                inventory_item=item,
            )
            aw.purchase_order = po
            aw.save(update_fields=['purchase_order'])
        pos.append(po)
    return pos


def pull_lines_from_mr(rfq: RFQ, mr):
    """Populate RFQ lines from a material requisition."""
    RFQLine.objects.filter(rfq=rfq).delete()
    sort = 0
    for line in mr.items.select_related('item'):
        RFQLine.objects.create(
            rfq=rfq,
            item=line.item,
            description=line.item.name,
            quantity=line.quantity,
            unit=line.item.unit,
            sort_order=sort,
        )
        sort += 1
