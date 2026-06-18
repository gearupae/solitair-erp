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


def calculate_po_retention_amount(gross_total: Decimal, retention_percent) -> Decimal:
    pct = normalize_po_retention_percent(retention_percent)
    gross = Decimal(str(gross_total or '0')).quantize(Decimal('0.01'))
    if pct is None or gross <= 0:
        return Decimal('0.00')
    return (gross * pct / Decimal('100')).quantize(Decimal('0.01'))


def apply_retention_to_vendor_bill_totals(bill, *, retention_amount_override=None) -> None:
    """
    Set retention and payable total on a vendor bill.

    ``subtotal`` / ``vat_amount`` stay as full line amounts; ``total_amount`` is AP payable (gross − retention).
    """
    gross = (bill.subtotal or Decimal('0.00')) + (bill.vat_amount or Decimal('0.00'))
    if retention_amount_override is not None:
        retention = Decimal(str(retention_amount_override)).quantize(Decimal('0.01'))
    else:
        retention = calculate_po_retention_amount(gross, bill.retention_percent)
    if retention < 0:
        retention = Decimal('0.00')
    if retention > gross:
        retention = gross
    bill.retention_amount = retention
    bill.total_amount = (gross - retention).quantize(Decimal('0.01'))


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
        gross = (bill.subtotal or Decimal('0')) + (bill.vat_amount or Decimal('0'))
        retention = bill.retention_amount or Decimal('0')
        payable = bill.total_amount or Decimal('0')
        total_retention += retention
        total_gross += gross
        total_payable += payable
        rows.append({
            'bill_number': bill.bill_number,
            'bill_pk': bill.pk,
            'bill_date': bill.bill_date,
            'gross_total': gross,
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
