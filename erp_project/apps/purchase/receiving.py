"""
Purchase order goods receipt: inventory stock-in, audit trails, PO status sync.
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import StockMovement, Warehouse

from .models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    ItemPurchaseReceiptHistory,
)


def purchase_order_can_receive(po: PurchaseOrder) -> bool:
    if not getattr(po, 'is_active', True):
        return False
    if po.status in ('cancelled', 'received', 'draft'):
        return False
    return po.status in ('sent', 'confirmed', 'partial_received')


def _parse_decimal(raw):
    if raw is None:
        return Decimal('0')
    s = str(raw).strip().replace(',', '.')
    if not s:
        return Decimal('0')
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValidationError(f'Invalid number: {raw!r}') from exc


def sync_po_receive_status(po_id: int):
    """Set PO status to received / partial_received from cumulative quantities."""
    po = PurchaseOrder.objects.prefetch_related('items').get(pk=po_id)
    lines = list(po.items.all())
    if not lines:
        return
    has_positive_order = any((ln.quantity or Decimal('0')) > 0 for ln in lines)
    if not has_positive_order:
        return
    all_done = True
    any_recv = False
    for ln in lines:
        recv = (ln.quantity_received or Decimal('0')).quantize(Decimal('0.01'))
        ordq = (ln.quantity or Decimal('0')).quantize(Decimal('0.01'))
        if recv > 0:
            any_recv = True
        if recv < ordq:
            all_done = False
    if all_done:
        PurchaseOrder.objects.filter(pk=po.pk).update(status='received')
    elif any_recv:
        PurchaseOrder.objects.filter(pk=po.pk).update(status='partial_received')


@transaction.atomic
def process_goods_receipt(po_id: int, warehouse_pk: int, received_on, notes: str, line_payloads: list, user):
    """
    line_payloads: list of dicts with keys purchase_order_item_id (int), qty_raw, unit_price_raw

    Raises ValidationError on business validation failures.
    """
    po = (
        PurchaseOrder.objects.select_for_update()
        .select_related('vendor')
        .prefetch_related('items')
        .get(pk=po_id)
    )
    if not purchase_order_can_receive(po):
        raise ValidationError('This purchase order cannot receive goods (wrong status or inactive).')

    wh = (
        Warehouse.objects.select_for_update()
        .filter(pk=warehouse_pk, is_active=True, status='active')
        .first()
    )
    if not wh:
        raise ValidationError('Select a valid active warehouse.')

    lines_by_id = {
        ln.pk: ln
        for ln in PurchaseOrderItem.objects.select_for_update()
        .filter(purchase_order_id=po.pk)
        .select_related('inventory_item')
    }

    validated = []
    errors = []

    for raw in line_payloads:
        lid = raw.get('purchase_order_item_id')
        try:
            lid = int(lid)
        except (TypeError, ValueError):
            errors.append(f'Invalid line id: {lid!r}')
            continue
        po_line = lines_by_id.get(lid)
        if not po_line:
            errors.append(f'Unknown PO line id {lid}.')
            continue

        try:
            qty_now = _parse_decimal(raw.get('qty_raw')).quantize(Decimal('0.01'))
            unit_price = _parse_decimal(raw.get('unit_price_raw')).quantize(Decimal('0.01'))
        except ValidationError as exc:
            errors.extend(exc.messages if hasattr(exc, 'messages') else [str(exc)])
            continue

        if qty_now < 0:
            errors.append(f'Line "{po_line.description[:60]}": quantity cannot be negative.')
            continue
        if unit_price < 0:
            errors.append(f'Line "{po_line.description[:60]}": unit price cannot be negative.')
            continue

        received_so_far = (po_line.quantity_received or Decimal('0')).quantize(Decimal('0.01'))
        ordered = (po_line.quantity or Decimal('0')).quantize(Decimal('0.01'))
        remaining = (ordered - received_so_far).quantize(Decimal('0.01'))

        if qty_now > remaining:
            errors.append(
                f'Line "{po_line.description[:80]}": cannot receive {qty_now} — '
                f'only {remaining} remaining ({received_so_far} already received of {ordered}).'
            )
            continue

        if qty_now > 0 and not po_line.inventory_item_id:
            errors.append(
                f'Line "{po_line.description[:80]}": link an inventory item on the PO line before receiving stock.'
            )
            continue

        validated.append((po_line, qty_now, unit_price))

    if errors:
        raise ValidationError(errors)

    total_qty = sum(t[1] for t in validated)
    if total_qty <= 0:
        raise ValidationError('Enter at least one quantity greater than zero to receive.')

    receipt = PurchaseOrderReceipt.objects.create(
        purchase_order=po,
        warehouse=wh,
        received_on=received_on,
        notes=(notes or '').strip(),
    )

    for po_line, qty_now, unit_price in validated:
        if qty_now <= 0:
            continue

        movement = StockMovement(
            item=po_line.inventory_item,
            warehouse=wh,
            movement_type='in',
            source='purchase',
            quantity=qty_now,
            unit_cost=unit_price,
            reference=po.po_number,
            notes=f'Goods receipt #{receipt.pk} — {po.po_number}',
            movement_date=received_on,
        )
        movement.save()
        movement.execute(user=user)

        PurchaseOrderReceiptLine.objects.create(
            receipt=receipt,
            purchase_order_item=po_line,
            quantity_received=qty_now,
            unit_price=unit_price,
        )

        ItemPurchaseReceiptHistory.objects.create(
            item=po_line.inventory_item,
            vendor=po.vendor,
            purchase_order=po,
            purchase_order_item=po_line,
            receipt=receipt,
            quantity=qty_now,
            unit_price=unit_price,
            po_number=po.po_number,
            stock_movement=movement,
        )

        po_line.quantity_received = (
            (po_line.quantity_received or Decimal('0')) + qty_now
        ).quantize(Decimal('0.01'))
        po_line.save(update_fields=['quantity_received'])

    sync_po_receive_status(po.pk)
    return receipt
