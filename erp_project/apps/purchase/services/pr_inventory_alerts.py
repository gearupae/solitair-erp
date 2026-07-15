"""Purchase price and quote context for PR lines already in inventory."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q

from apps.purchase.models import ItemPurchaseReceiptHistory, PurchaseOrderItem, PurchaseRequest, PurchaseRequestAttachment, PurchaseRequestAttachment


def _variance_pct(reference: Decimal | float | None, compare: Decimal | float | None) -> float | None:
    if reference is None or compare is None:
        return None
    ref = float(reference)
    cmp = float(compare)
    if ref <= 0:
        return None
    return round((cmp - ref) / ref * 100, 1)


def _quote_lines_for_item(inv, pr_line, attachments) -> list[dict]:
    """Vendor quote unit prices matched to this inventory / PR line."""
    quotes: list[dict] = []
    item_code = (inv.item_code or '').strip().lower()
    item_name = (inv.name or '').strip().lower()
    line_desc = (pr_line.description or '').strip().lower()

    seen: set[tuple] = set()
    for att in attachments:
        vendor_label = (att.vendor or '').strip()
        structured = att.structured_quote_json if isinstance(att.structured_quote_json, dict) else None

        if structured:
            vendor_label = (structured.get('vendor_name') or vendor_label or 'Vendor').strip()
            validity = (structured.get('validity_date') or '').strip()
            for row in structured.get('line_items') or []:
                if not isinstance(row, dict):
                    continue
                unit_price = row.get('unit_price')
                if unit_price is None:
                    continue
                li_desc = (row.get('description') or '').strip().lower()
                matched = False
                if item_code and item_code in li_desc:
                    matched = True
                elif item_name and len(item_name) >= 3 and item_name in li_desc:
                    matched = True
                elif line_desc and len(line_desc) >= 4 and line_desc[:60] in li_desc:
                    matched = True
                elif line_desc and len(line_desc) >= 4 and li_desc and line_desc in li_desc:
                    matched = True
                if not matched:
                    continue
                key = (vendor_label, float(unit_price), li_desc[:80])
                if key in seen:
                    continue
                seen.add(key)
                quotes.append({
                    'vendor': vendor_label,
                    'unit_price': float(unit_price),
                    'validity_date': validity,
                    'description': row.get('description') or '',
                    'source': 'quote_line',
                })
        elif att.total_price is not None and vendor_label:
            key = (vendor_label, float(att.total_price), 'total')
            if key not in seen:
                seen.add(key)
                quotes.append({
                    'vendor': vendor_label,
                    'unit_price': None,
                    'total_price': float(att.total_price),
                    'validity_date': '',
                    'description': '',
                    'source': 'attachment_total',
                })

    quotes.sort(key=lambda q: (q.get('unit_price') is None, q.get('unit_price') or 0))
    return quotes


def _receipt_history_for_item(item_id, *, limit: int = 6) -> list[dict]:
    rows = []
    qs = (
        ItemPurchaseReceiptHistory.objects.filter(item_id=item_id, is_active=True)
        .select_related('vendor', 'purchase_order', 'receipt')
        .order_by('-created_at')[:limit]
    )
    for h in qs:
        purchase_date = None
        if h.created_at:
            purchase_date = h.created_at.date()
        elif h.receipt_id and getattr(h.receipt, 'created_at', None):
            purchase_date = h.receipt.created_at.date()
        rows.append({
            'vendor': h.vendor.name,
            'unit_price': float(h.unit_price),
            'purchase_date': purchase_date,
            'po_number': h.po_number,
            'quantity': float(h.quantity),
        })
    return rows


def _po_fallback_history(pr_line, *, limit: int = 6) -> list[dict]:
    desc = (pr_line.description or '').strip()
    if len(desc) < 3:
        return []
    qs = (
        PurchaseOrderItem.objects.filter(
            purchase_order__is_active=True,
            purchase_order__status__in=('sent', 'confirmed', 'partial_received', 'received'),
        )
        .filter(
            Q(description__icontains=desc[:80])
            | Q(description__icontains=desc.split()[0] if desc.split() else desc)
        )
        .select_related('purchase_order', 'purchase_order__vendor')
        .order_by('-purchase_order__order_date', '-id')[:limit]
    )
    rows = []
    for poi in qs:
        po = poi.purchase_order
        rows.append({
            'vendor': po.vendor.name,
            'unit_price': float(poi.unit_price),
            'purchase_date': po.order_date,
            'po_number': po.po_number,
            'quantity': float(poi.quantity),
        })
    return rows


def build_pr_inventory_purchase_alerts(pr: PurchaseRequest) -> list[dict]:
    """
    In-stock PR lines with purchase history, vendor quotes, last/lowest price, variance.
    """
    from apps.inventory.serial_stock import item_available_qty

    attachments = list(
        pr.attachments.filter(kind=PurchaseRequestAttachment.KIND_VENDOR_QUOTE).order_by('id')
    )
    alerts: list[dict] = []

    for line in pr.items.select_related('inventory_item').order_by('id'):
        if not line.inventory_item_id:
            continue
        inv = line.inventory_item
        if not inv.is_active or inv.status != 'active':
            continue
        available = item_available_qty(inv)
        if available <= 0:
            continue

        history = _receipt_history_for_item(inv.pk)
        if not history:
            history = _po_fallback_history(line)

        last_purchase = history[0] if history else None
        prices = [h['unit_price'] for h in history if h.get('unit_price', 0) > 0]
        lowest_price = min(prices) if prices else None

        estimated = float(line.estimated_price) if line.estimated_price else None
        variance_vs_last = _variance_pct(
            last_purchase['unit_price'] if last_purchase else None,
            estimated,
        )
        variance_vs_lowest = _variance_pct(lowest_price, estimated)

        quote_prices = _quote_lines_for_item(inv, line, attachments)
        quote_unit_prices = [q['unit_price'] for q in quote_prices if q.get('unit_price')]
        lowest_quote = min(quote_unit_prices) if quote_unit_prices else None

        alerts.append({
            'pr_line_id': line.pk,
            'name': inv.name,
            'item_code': inv.item_code,
            'requested_qty': line.quantity,
            'available_qty': available,
            'covers_request': available >= line.quantity,
            'estimated_unit_price': estimated,
            'last_purchase': last_purchase,
            'lowest_price': lowest_price,
            'variance_vs_last_pct': variance_vs_last,
            'variance_vs_lowest_pct': variance_vs_lowest,
            'purchase_history': history,
            'quote_prices': quote_prices,
            'lowest_quote_price': lowest_quote,
        })

    return alerts
