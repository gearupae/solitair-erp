"""
GRN posting service — wraps existing PO goods receipt; adds formal GRN document + cancel/reversal.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import StockMovement
from apps.purchase.models import ItemPurchaseReceiptHistory, PurchaseOrder, PurchaseOrderItem
from apps.purchase.models_grn import GRNLine, GoodsReceiptNote
from apps.purchase.receiving import process_goods_receipt, sync_po_receive_status
from apps.settings_app.models import CompanySettings


def _parse_tolerance_pct() -> Decimal:
    cs = CompanySettings.get_settings()
    raw = getattr(cs, 'grn_over_receipt_tolerance_pct', None)
    if raw is None:
        return Decimal('0')
    return Decimal(str(raw)).quantize(Decimal('0.01'))


def _validate_tolerance(po_line: PurchaseOrderItem, qty_now: Decimal, received_so_far: Decimal):
    tolerance = _parse_tolerance_pct()
    ordered = (po_line.quantity or Decimal('0')).quantize(Decimal('0.01'))
    if tolerance <= 0:
        remaining = (ordered - received_so_far).quantize(Decimal('0.01'))
        if qty_now > remaining:
            raise ValidationError(
                f'Line "{po_line.description[:80]}": cannot receive {qty_now} — '
                f'only {remaining} remaining.'
            )
        return

    max_allowed = (ordered * (Decimal('1') + tolerance / Decimal('100'))).quantize(Decimal('0.01'))
    new_total = (received_so_far + qty_now).quantize(Decimal('0.01'))
    if new_total > max_allowed:
        raise ValidationError(
            f'Line "{po_line.description[:80]}": receipt {new_total} exceeds '
            f'tolerance max {max_allowed} (ordered {ordered}, tolerance {tolerance}%).'
        )


@transaction.atomic
def post_grn_from_po(
    po_id: int,
    warehouse_pk: int,
    received_on,
    notes: str,
    line_payloads: list,
    user,
    supplier_delivery_note: str = '',
    line_qc: dict | None = None,
) -> GoodsReceiptNote:
    po = PurchaseOrder.objects.select_related('vendor').get(pk=po_id)
    line_qc = line_qc or {}

    lines_by_id = {
        ln.pk: ln
        for ln in PurchaseOrderItem.objects.filter(purchase_order_id=po_id)
    }
    for raw in line_payloads:
        try:
            lid = int(raw.get('purchase_order_item_id'))
        except (TypeError, ValueError):
            continue
        po_line = lines_by_id.get(lid)
        if not po_line:
            continue
        qty_now = Decimal(str(raw.get('qty_raw') or '0')).quantize(Decimal('0.01'))
        if qty_now <= 0:
            continue
        received_so_far = (po_line.quantity_received or Decimal('0')).quantize(Decimal('0.01'))
        _validate_tolerance(po_line, qty_now, received_so_far)

    stock_payloads = []
    for raw in line_payloads:
        lid = int(raw.get('purchase_order_item_id'))
        qc = line_qc.get(lid, {})
        accepted = qc.get('accepted')
        payload = dict(raw)
        if accepted is not None:
            payload['qty_raw'] = accepted
        stock_payloads.append(payload)

    receipt = process_goods_receipt(
        po_id, warehouse_pk, received_on, notes, stock_payloads, user
    )

    grn = GoodsReceiptNote.objects.create(
        supplier=po.vendor,
        purchase_order=po,
        warehouse_id=warehouse_pk,
        received_on=received_on,
        received_by=user,
        supplier_delivery_note=supplier_delivery_note or '',
        status=GoodsReceiptNote.STATUS_POSTED,
        notes=notes or '',
        purchase_receipt=receipt,
        created_by=user,
    )

    for raw in line_payloads:
        lid = int(raw.get('purchase_order_item_id'))
        po_line = lines_by_id.get(lid)
        if not po_line or not po_line.inventory_item_id:
            continue
        received_qty = Decimal(str(raw.get('qty_raw') or '0')).quantize(Decimal('0.01'))
        if received_qty <= 0:
            continue
        qc = line_qc.get(lid, {})
        accepted = Decimal(str(qc.get('accepted', received_qty))).quantize(Decimal('0.01'))
        rejected = Decimal(str(qc.get('rejected', max(Decimal('0'), received_qty - accepted)))).quantize(
            Decimal('0.01')
        )
        qc_status = qc.get('qc_status', GRNLine.QC_PASSED if accepted > 0 else GRNLine.QC_FAILED)

        receipt_line = receipt.lines.filter(purchase_order_item_id=lid).order_by('-id').first()
        movement = None
        if receipt_line:
            hist = ItemPurchaseReceiptHistory.objects.filter(
                receipt=receipt, purchase_order_item_id=lid
            ).first()
            movement = hist.stock_movement if hist else None

        GRNLine.objects.create(
            grn=grn,
            purchase_order_item=po_line,
            item=po_line.inventory_item,
            ordered_qty=po_line.quantity or Decimal('0'),
            received_qty=received_qty,
            accepted_qty=accepted,
            rejected_qty=rejected,
            rejection_reason=qc.get('rejection_reason', ''),
            unit_cost=Decimal(str(raw.get('unit_price_raw') or po_line.unit_price or '0')),
            qc_status=qc_status,
            stock_movement=movement,
            receipt_line=receipt_line,
        )

    return grn


@transaction.atomic
def cancel_grn(grn: GoodsReceiptNote, user, reason: str = ''):
    if grn.status != GoodsReceiptNote.STATUS_POSTED:
        raise ValidationError('Only posted GRNs can be cancelled.')

    for line in grn.lines.select_related('stock_movement', 'purchase_order_item'):
        if not line.stock_movement_id:
            continue
        mv = line.stock_movement
        if line.accepted_qty <= 0:
            continue
        reversal = StockMovement.objects.create(
            item=mv.item,
            warehouse=mv.warehouse,
            movement_type='adjustment_minus',
            source='manual',
            quantity=line.accepted_qty,
            unit_cost=mv.unit_cost,
            reference=f'GRN Cancel: {grn.grn_number}',
            notes=reason or f'Cancellation of {grn.grn_number}',
            movement_date=timezone.now().date(),
            adjustment_reason='correction',
            created_by=user,
        )
        reversal.execute(user=user, allow_zero_cost=mv.unit_cost <= 0)
        if mv.journal_entry_id:
            mv.journal_entry.reverse(user=user, reason=f'GRN cancel {grn.grn_number}')

        if line.purchase_order_item_id:
            poi = line.purchase_order_item
            poi.quantity_received = max(
                Decimal('0'),
                (poi.quantity_received or Decimal('0')) - line.accepted_qty,
            ).quantize(Decimal('0.01'))
            poi.save(update_fields=['quantity_received'])

    grn.status = GoodsReceiptNote.STATUS_CANCELLED
    grn.notes = f'{grn.notes}\n[CANCELLED] {reason}'.strip()
    grn.save(update_fields=['status', 'notes', 'updated_at'])

    if grn.purchase_order_id:
        sync_po_receive_status(grn.purchase_order_id)

    return grn
