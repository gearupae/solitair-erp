"""Historical purchase prices for PR line items (quote comparison context)."""
from __future__ import annotations

from django.db.models import Q

from apps.purchase.models import ItemPurchaseReceiptHistory, PurchaseOrderItem, PurchaseRequest


def build_pr_purchase_price_history(pr: PurchaseRequest, *, limit_per_line: int = 8) -> list[dict]:
    """
    Past PO/receipt unit prices for each PR line (by inventory item or description match).
    """
    rows = []
    for line in pr.items.select_related('inventory_item').order_by('id'):
        entry = {
            'pr_line_description': line.description,
            'quantity': float(line.quantity),
            'unit': line.get_unit_display(),
            'estimated_unit_price': float(line.estimated_price),
            'inventory_item_code': line.inventory_item.item_code if line.inventory_item_id else '',
            'past_purchases': [],
        }
        past = []

        if line.inventory_item_id:
            qs = (
                ItemPurchaseReceiptHistory.objects.filter(
                    item_id=line.inventory_item_id,
                    is_active=True,
                )
                .select_related('vendor', 'purchase_order')
                .order_by('-created_at')[:limit_per_line]
            )
            for h in qs:
                past.append({
                    'vendor': h.vendor.name,
                    'unit_price': float(h.unit_price),
                    'po_number': h.po_number,
                    'date': h.created_at.date().isoformat() if h.created_at else '',
                })
        else:
            desc = (line.description or '').strip()
            if len(desc) >= 3:
                qs = (
                    PurchaseOrderItem.objects.filter(
                        purchase_order__is_active=True,
                        purchase_order__status__in=(
                            'sent', 'confirmed', 'partial_received', 'received',
                        ),
                    )
                    .filter(
                        Q(description__icontains=desc[:80])
                        | Q(description__icontains=desc.split()[0] if desc.split() else desc)
                    )
                    .select_related('purchase_order', 'purchase_order__vendor')
                    .order_by('-purchase_order__order_date', '-id')[:limit_per_line]
                )
                for poi in qs:
                    past.append({
                        'vendor': poi.purchase_order.vendor.name,
                        'unit_price': float(poi.unit_price),
                        'po_number': poi.purchase_order.po_number,
                        'date': (
                            poi.purchase_order.order_date.isoformat()
                            if poi.purchase_order.order_date
                            else ''
                        ),
                    })

        entry['past_purchases'] = past
        if past:
            prices = [p['unit_price'] for p in past if p['unit_price'] > 0]
            entry['historical_avg_unit_price'] = round(sum(prices) / len(prices), 2) if prices else None
            entry['historical_low_unit_price'] = min(prices) if prices else None
            entry['historical_high_unit_price'] = max(prices) if prices else None
        else:
            entry['historical_avg_unit_price'] = None
            entry['historical_low_unit_price'] = None
            entry['historical_high_unit_price'] = None

        rows.append(entry)
    return rows
