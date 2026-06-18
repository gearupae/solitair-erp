"""Purchase-order retention (vendor/AP side). Separate from sales invoice retention."""
from __future__ import annotations

from decimal import Decimal

PO_RETENTION_PERCENT_VALUES = frozenset({Decimal('5'), Decimal('10')})


def normalize_po_retention_percent(value) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        pct = Decimal(str(value)).quantize(Decimal('0.01'))
    except Exception:
        return None
    if pct <= 0:
        return None
    if pct in PO_RETENTION_PERCENT_VALUES:
        return pct
    return None


def po_retention_percent_label(percent) -> str:
    pct = normalize_po_retention_percent(percent)
    if pct is None:
        return 'None'
    if pct == pct.to_integral_value():
        return f'{int(pct)}%'
    return f'{pct}%'


def calculate_po_retention_amount(scope_subtotal: Decimal, retention_percent) -> Decimal:
    """Retention withheld from bill scope subtotal (excl. VAT)."""
    pct = normalize_po_retention_percent(retention_percent)
    base = Decimal(str(scope_subtotal or '0')).quantize(Decimal('0.01'))
    if pct is None or base <= 0:
        return Decimal('0.00')
    return (base * pct / Decimal('100')).quantize(Decimal('0.01'))


def apply_retention_to_vendor_bill_totals(
    bill,
    *,
    line_subtotal: Decimal | None = None,
    line_vat: Decimal | None = None,
    retention_amount_override=None,
) -> None:
    """
    Apply retention on scope subtotal (excl. VAT), then VAT on the billable subtotal.

    ``retention_amount`` is informational (vendor / project overview only).
    ``subtotal``, ``vat_amount``, and ``total_amount`` are billable amounts posted to finance.
    """
    scope_subtotal = (
        Decimal(str(line_subtotal or '0')).quantize(Decimal('0.01'))
        if line_subtotal is not None
        else Decimal(str(bill.subtotal or '0')).quantize(Decimal('0.01'))
    )
    scope_vat = (
        Decimal(str(line_vat or '0')).quantize(Decimal('0.01'))
        if line_vat is not None
        else Decimal(str(bill.vat_amount or '0')).quantize(Decimal('0.01'))
    )

    if retention_amount_override is not None:
        retention = Decimal(str(retention_amount_override)).quantize(Decimal('0.01'))
    else:
        retention = calculate_po_retention_amount(scope_subtotal, bill.retention_percent)
    if retention < 0:
        retention = Decimal('0.00')
    if retention > scope_subtotal:
        retention = scope_subtotal

    billable_subtotal = (scope_subtotal - retention).quantize(Decimal('0.01'))
    if scope_subtotal > 0:
        billable_vat = (scope_vat * billable_subtotal / scope_subtotal).quantize(Decimal('0.01'))
    else:
        billable_vat = Decimal('0.00')

    bill.retention_amount = retention
    bill.subtotal = billable_subtotal
    bill.vat_amount = billable_vat
    bill.total_amount = (billable_subtotal + billable_vat).quantize(Decimal('0.01'))


def resolve_purchase_retention_for_po(purchase_order) -> Decimal | None:
    if not purchase_order:
        return None
    return normalize_po_retention_percent(purchase_order.retention_percent)


def resolve_purchase_retention_for_project(project) -> Decimal | None:
    """Retention % from the most recent PO linked to this project."""
    if not project:
        return None
    from apps.purchase.models import PurchaseOrder

    po = (
        PurchaseOrder.objects.filter(
            project=project,
            is_active=True,
            retention_percent__isnull=False,
        )
        .exclude(retention_percent=0)
        .order_by('-order_date', '-pk')
        .first()
    )
    if po:
        return normalize_po_retention_percent(po.retention_percent)
    return None


def sync_vendor_bill_retention_links(bill) -> None:
    """Fill project / retention % from linked PO or project."""
    from apps.purchase.models import PurchaseOrder

    if bill.purchase_order_id:
        po = bill.purchase_order
        if po.project_id and not bill.project_id:
            bill.project_id = po.project_id
        if po.retention_percent and not bill.retention_percent:
            bill.retention_percent = normalize_po_retention_percent(po.retention_percent)
    elif bill.project_id and not bill.retention_percent:
        bill.retention_percent = resolve_purchase_retention_for_project(bill.project)


def vendor_bill_retention_summary_rows(bills) -> list[dict]:
    """Line-by-line retention summary for PO / vendor overview cards."""
    rows = []
    total_retention = Decimal('0.00')
    total_gross = Decimal('0.00')
    total_payable = Decimal('0.00')

    for bill in bills:
        scope_subtotal = (bill.subtotal or Decimal('0')) + (bill.retention_amount or Decimal('0'))
        retention = bill.retention_amount or Decimal('0')
        payable = bill.total_amount or Decimal('0')
        total_retention += retention
        total_gross += scope_subtotal
        total_payable += payable
        rows.append({
            'bill_number': bill.bill_number,
            'bill_pk': bill.pk,
            'bill_date': bill.bill_date,
            'scope_subtotal': scope_subtotal,
            'gross_total': scope_subtotal,
            'retention_amount': retention,
            'retention_percent': bill.retention_percent,
            'payable_amount': payable,
            'po_number': bill.purchase_order.po_number if bill.purchase_order_id else '—',
        })

    return {
        'rows': rows,
        'total_retention': total_retention.quantize(Decimal('0.01')),
        'total_gross': total_gross.quantize(Decimal('0.01')),
        'total_payable': total_payable.quantize(Decimal('0.01')),
    }
