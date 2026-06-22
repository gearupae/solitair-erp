"""Inventory compliance watchdog — detect issues and persist flagged records."""
from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.inventory.models import Item, Stock, StockMovement
from apps.inventory.models_reporting import InventoryComplianceFlag, InventoryCostLayer
from apps.inventory.reports._common import active_product_items
from apps.inventory.reports.fifo_valuation import build_fifo_valuation_report
from apps.stock_take.models import StockTakeLine, StockTakeSession

VARIANCE_THRESHOLD_PCT = Decimal('5')
GL_VARIANCE_THRESHOLD_PCT = Decimal('1')

SEVERITY_BADGE = {
    InventoryComplianceFlag.SEVERITY_HIGH: 'fc-badge fc-badge-red',
    InventoryComplianceFlag.SEVERITY_MEDIUM: 'fc-badge fc-badge-orange',
    InventoryComplianceFlag.SEVERITY_LOW: 'fc-badge fc-badge-green',
}


def _run_key() -> str:
    return hashlib.sha256(date.today().isoformat().encode()).hexdigest()[:16]


def _flag(
    *,
    check_code: str,
    severity: str,
    issue: str,
    suggested_fix: str,
    item=None,
    warehouse=None,
    value_impact=Decimal('0'),
) -> dict:
    return {
        'check_code': check_code,
        'severity': severity,
        'issue': issue[:300],
        'suggested_fix': suggested_fix,
        'item': item,
        'sku': item.item_code if item else '',
        'warehouse': warehouse,
        'value_impact': value_impact.quantize(Decimal('0.01')),
    }


def _inventory_ledger_total() -> Decimal:
    payload = build_fifo_valuation_report()
    return Decimal(str(payload.get('summary', {}).get('grand_total_value', 0) or 0))


def _gl_inventory_balance() -> Decimal | None:
    try:
        from apps.finance.models import Account, AccountMapping

        acct = AccountMapping.get_account_or_default('inventory_asset', '1500')
        if not acct:
            acct = Account.objects.filter(account_code='1500', is_active=True).first()
        if not acct:
            return None
        return (acct.current_balance or Decimal('0')).quantize(Decimal('0.01'))
    except Exception:
        return None


def _open_po_item_ids() -> set[int]:
    from apps.purchase.models import PurchaseOrder, PurchaseOrderItem

    open_status = ['draft', 'sent', 'confirmed', 'partial_received']
    po_ids = PurchaseOrder.objects.filter(is_active=True, status__in=open_status).values_list('pk', flat=True)
    return set(
        PurchaseOrderItem.objects.filter(
            purchase_order_id__in=po_ids,
            inventory_item_id__isnull=False,
        ).values_list('inventory_item_id', flat=True)
    )


def _detect_negative_stock() -> list[dict]:
    flags = []
    for row in Stock.objects.filter(quantity__lt=0).select_related('item', 'warehouse'):
        flags.append(
            _flag(
                check_code='negative_stock',
                severity=InventoryComplianceFlag.SEVERITY_HIGH,
                issue=f'Negative stock: {row.item.name} @ {row.warehouse.name}',
                suggested_fix='Post adjustment or investigate duplicate issues; block sales until corrected.',
                item=row.item,
                warehouse=row.warehouse,
                value_impact=abs(row.quantity) * (row.item.purchase_price or Decimal('0')),
            )
        )
    return flags


def _detect_gl_mismatch() -> list[dict]:
    ledger = _inventory_ledger_total()
    gl = _gl_inventory_balance()
    if gl is None or ledger <= 0:
        return []
    variance = abs(ledger - gl)
    if ledger <= 0:
        return []
    pct = (variance / ledger * Decimal('100')).quantize(Decimal('0.01'))
    if pct <= GL_VARIANCE_THRESHOLD_PCT:
        return []
    return [
        _flag(
            check_code='gl_mismatch',
            severity=InventoryComplianceFlag.SEVERITY_HIGH,
            issue=f'Inventory ledger vs GL variance {pct}% (AED {variance:,.2f})',
            suggested_fix='Reconcile FIFO valuation with GL account 1500; post missing GRN/COGS journals.',
            value_impact=variance,
        )
    ]


def _detect_reorder_breach() -> list[dict]:
    open_po_items = _open_po_item_ids()
    flags = []
    for item in active_product_items():
        on_hand = (
            Stock.objects.filter(item=item).aggregate(
                t=Coalesce(Sum('quantity'), Decimal('0')),
            )['t']
            or Decimal('0')
        )
        min_stock = item.minimum_stock or Decimal('0')
        if min_stock <= 0 or on_hand >= min_stock:
            continue
        if item.pk in open_po_items:
            continue
        gap = (min_stock - on_hand).quantize(Decimal('0.01'))
        flags.append(
            _flag(
                check_code='reorder_breach',
                severity=InventoryComplianceFlag.SEVERITY_MEDIUM,
                issue=f'Below reorder point with no open PO: {item.name}',
                suggested_fix='Create purchase request or PO; review min stock and lead time.',
                item=item,
                value_impact=gap * (item.purchase_price or Decimal('0')),
            )
        )
    return flags


def _detect_valuation_drift() -> list[dict]:
    flags = []
    for item in active_product_items()[:200]:
        layers = InventoryCostLayer.objects.filter(item=item, qty_remaining__gt=0)
        if not layers.exists():
            continue
        costs = {l.unit_cost for l in layers if l.unit_cost}
        if len(costs) <= 1:
            continue
        spread = max(costs) - min(costs)
        avg = sum(costs) / len(costs)
        if avg <= 0:
            continue
        if spread / avg > Decimal('0.15'):
            flags.append(
                _flag(
                    check_code='valuation_drift',
                    severity=InventoryComplianceFlag.SEVERITY_MEDIUM,
                    issue=f'FIFO cost spread on {item.name} ({spread:.2f} AED/unit)',
                    suggested_fix='Rebuild FIFO layers or review mixed-cost receipts.',
                    item=item,
                    value_impact=spread * (item.total_stock or Decimal('0')),
                )
            )
    return flags


def _detect_expired_sellable() -> list[dict]:
    today = date.today()
    flags = []
    qs = Item.objects.filter(
        is_active=True,
        status='active',
        warranty_expiry__lt=today,
    )
    for item in qs[:100]:
        on_hand = item.total_stock or Decimal('0')
        if on_hand <= 0:
            continue
        flags.append(
            _flag(
                check_code='expired_sellable',
                severity=InventoryComplianceFlag.SEVERITY_HIGH,
                issue=f'Expired batch/warranty but stock on hand: {item.name}',
                suggested_fix='Block from sale, quarantine stock, and post write-off per UAE VAT rules.',
                item=item,
                value_impact=on_hand * (item.purchase_price or Decimal('0')),
            )
        )
    return flags


def _detect_stocktake_variance() -> list[dict]:
    flags = []
    sessions = StockTakeSession.objects.filter(status=StockTakeSession.STATUS_COMPLETED).order_by('-completed_at')[:5]
    for session in sessions:
        for line in session.lines.all():
            if not line.expected_qty or line.expected_qty == 0:
                continue
            var = abs(line.variance)
            pct = (var / line.expected_qty * Decimal('100')).quantize(Decimal('0.01'))
            if pct < VARIANCE_THRESHOLD_PCT:
                continue
            item = Item.objects.filter(item_code=line.sku, is_active=True).first()
            flags.append(
                _flag(
                    check_code='stocktake_variance',
                    severity=InventoryComplianceFlag.SEVERITY_HIGH if pct >= 10 else InventoryComplianceFlag.SEVERITY_MEDIUM,
                    issue=f'Stock count variance {pct}% on {line.sku} ({session.client_name})',
                    suggested_fix='Investigate shrinkage; post adjustment journal and update cycle count.',
                    item=item,
                    value_impact=var * (item.purchase_price if item else Decimal('0')),
                )
            )
    return flags


def _detect_uae_vat_writeoffs() -> list[dict]:
    flags = []
    qs = StockMovement.objects.filter(
        movement_type='adjustment',
        is_active=True,
    ).select_related('item').order_by('-movement_date')[:50]
    for mv in qs:
        if mv.item and mv.item.tax_code:
            continue
        flags.append(
            _flag(
                check_code='uae_vat_writeoff',
                severity=InventoryComplianceFlag.SEVERITY_MEDIUM,
                issue=f'Adjustment without VAT/tax code: {mv.item.name if mv.item else mv.pk}',
                suggested_fix='Assign tax code and ensure FTA-compliant write-off journal with VAT treatment.',
                item=mv.item,
                value_impact=abs(mv.quantity or Decimal('0')) * (mv.unit_cost or Decimal('0')),
            )
        )
    return flags


def _detect_lot_traceability() -> list[dict]:
    trace_categories = ['food', 'pharma', 'cosmetic', 'medicine', 'chemical']
    flags = []
    for item in active_product_items():
        cat_name = (item.category.name if item.category_id else '').lower()
        if not any(k in cat_name for k in trace_categories):
            continue
        if not (item.serial_batch_number or '').strip():
            flags.append(
                _flag(
                    check_code='lot_traceability',
                    severity=InventoryComplianceFlag.SEVERITY_HIGH,
                    issue=f'Missing lot/batch on traceable SKU: {item.name}',
                    suggested_fix='Capture batch/lot on receipt and link to outbound movements for FTA traceability.',
                    item=item,
                )
            )
    return flags


def run_compliance_watchdog(*, persist: bool = True) -> dict:
    """Run all checks; optionally persist to InventoryComplianceFlag."""
    run_key = _run_key()
    raw_flags = []
    raw_flags.extend(_detect_negative_stock())
    raw_flags.extend(_detect_gl_mismatch())
    raw_flags.extend(_detect_reorder_breach())
    raw_flags.extend(_detect_valuation_drift())
    raw_flags.extend(_detect_expired_sellable())
    raw_flags.extend(_detect_stocktake_variance())
    raw_flags.extend(_detect_uae_vat_writeoffs())
    raw_flags.extend(_detect_lot_traceability())

    if persist:
        InventoryComplianceFlag.objects.filter(run_key=run_key, is_resolved=False).delete()
        for row in raw_flags:
            InventoryComplianceFlag.objects.create(
                check_code=row['check_code'],
                severity=row['severity'],
                issue=row['issue'],
                item=row.get('item'),
                sku=row.get('sku') or '',
                warehouse=row.get('warehouse'),
                value_impact=row.get('value_impact') or Decimal('0'),
                suggested_fix=row.get('suggested_fix') or '',
                run_key=run_key,
            )

    rows = []
    for row in raw_flags:
        item = row.get('item')
        wh = row.get('warehouse')
        sev = row['severity']
        rows.append(
            {
                'severity': sev.title() if sev == InventoryComplianceFlag.SEVERITY_MEDIUM else sev.capitalize(),
                'severity_badge': SEVERITY_BADGE.get(sev, 'fc-badge fc-badge-orange'),
                'issue': row['issue'],
                'item_name': item.name if item else '—',
                'sku': row.get('sku') or (item.item_code if item else ''),
                'warehouse': wh.name if wh else '—',
                'value_impact': float(row.get('value_impact') or 0),
                'suggested_fix': row.get('suggested_fix') or '',
                'check_code': row['check_code'],
            }
        )

    rows.sort(key=lambda r: {'High': 0, 'Med': 1, 'Medium': 1, 'Low': 2}.get(r['severity'], 3))
    return {
        'title': 'Inventory Compliance',
        'columns': [
            {'key': 'severity', 'label': 'Severity'},
            {'key': 'issue', 'label': 'Issue'},
            {'key': 'item_name', 'label': 'Item'},
            {'key': 'sku', 'label': 'SKU'},
            {'key': 'value_impact', 'label': 'Value Impact (AED)', 'format': 'number', 'align': 'right'},
            {'key': 'suggested_fix', 'label': 'Suggested Fix'},
        ],
        'rows': rows,
        'summary': {
            'flag_count': len(rows),
            'high_count': sum(1 for r in rows if r['severity'] == 'High'),
            'run_key': run_key,
            'generated_at': timezone.now().isoformat(),
        },
    }


def load_compliance_report(*, force_refresh: bool = False) -> dict:
    from apps.inventory.services.ai_hub_cache import get_or_build_tab_cache

    return get_or_build_tab_cache(
        tab='compliance',
        builder=run_compliance_watchdog,
        force=force_refresh,
        ttl_hours=24,
    )
