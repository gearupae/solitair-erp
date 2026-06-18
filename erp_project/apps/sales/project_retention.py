"""Project retention: configure on estimates, apply on invoices."""
from __future__ import annotations

from decimal import Decimal

RETENTION_PERCENT_CHOICES = [
    (None, 'None'),
    (Decimal('5'), '5%'),
    (Decimal('10'), '10%'),
]

RETENTION_PERCENT_VALUES = frozenset({Decimal('5'), Decimal('10')})


def normalize_retention_percent(value) -> Decimal | None:
    """Return 5, 10, or None for retention configuration."""
    if value is None or value == '':
        return None
    try:
        pct = Decimal(str(value)).quantize(Decimal('0.01'))
    except Exception:
        return None
    if pct <= 0:
        return None
    if pct in RETENTION_PERCENT_VALUES:
        return pct
    return None


def retention_percent_label(percent) -> str:
    pct = normalize_retention_percent(percent)
    if pct is None:
        return 'None'
    if pct == pct.to_integral_value():
        return f'{int(pct)}%'
    return f'{pct}%'


def calculate_retention_amount(gross_total: Decimal, retention_percent) -> Decimal:
    """Retention deducted from gross invoice total (subtotal + VAT)."""
    pct = normalize_retention_percent(retention_percent)
    gross = Decimal(str(gross_total or '0')).quantize(Decimal('0.01'))
    if pct is None or gross <= 0:
        return Decimal('0.00')
    return (gross * pct / Decimal('100')).quantize(Decimal('0.01'))


def apply_retention_to_invoice_totals(invoice, *, retention_amount_override=None) -> None:
    """
    Set ``retention_amount`` and ``total_amount`` on an invoice from line totals.

    ``subtotal`` and ``vat_amount`` remain the full line amounts (excl. retention).
    ``total_amount`` is what the customer pays now (gross − retention).
    """
    gross = (invoice.subtotal or Decimal('0.00')) + (invoice.vat_amount or Decimal('0.00'))
    if retention_amount_override is not None:
        retention = Decimal(str(retention_amount_override)).quantize(Decimal('0.01'))
    else:
        retention = calculate_retention_amount(gross, invoice.retention_percent)
    if retention < 0:
        retention = Decimal('0.00')
    if retention > gross:
        retention = gross
    invoice.retention_amount = retention
    invoice.total_amount = (gross - retention).quantize(Decimal('0.01'))


def resolve_retention_for_project(project) -> Decimal | None:
    """Retention % from the primary estimate linked to this project."""
    if not project:
        return None
    from apps.projects.member_roles import get_project_source_estimate

    estimate = get_project_source_estimate(project)
    if estimate and estimate.retention_percent:
        return normalize_retention_percent(estimate.retention_percent)
    active = (
        project.estimates.filter(is_active=True, retention_percent__isnull=False)
        .exclude(retention_percent=0)
        .order_by('-date', '-pk')
        .first()
    )
    if active:
        return normalize_retention_percent(active.retention_percent)
    return None


def sync_invoice_retention_links(invoice) -> None:
    """Fill project / retention % from estimate or project when not set on the form."""
    from apps.sales.models import Estimate

    if invoice.estimate_id:
        est = (
            invoice.estimate
            if getattr(invoice, '_estimate_cache', None) or hasattr(invoice, 'estimate')
            else Estimate.objects.filter(pk=invoice.estimate_id).first()
        )
        if est:
            if est.project_id and not invoice.project_id:
                invoice.project_id = est.project_id
            if est.retention_percent and not invoice.retention_percent:
                invoice.retention_percent = normalize_retention_percent(est.retention_percent)
    if invoice.project_id and not invoice.retention_percent:
        invoice.retention_percent = resolve_retention_for_project(invoice.project)


def customer_retention_invoice_rows(customer, project=None):
    """Invoices with retention for customer overview / sales order card."""
    from apps.sales.models import Invoice

    qs = (
        Invoice.objects.filter(
            customer=customer,
            is_active=True,
            retention_amount__gt=0,
        )
        .exclude(status='cancelled')
        .select_related('project')
        .order_by('-invoice_date', '-pk')
    )
    if project is not None:
        qs = qs.filter(project=project)

    rows = []
    for inv in qs:
        rows.append({
            'invoice_number': inv.invoice_number,
            'invoice_pk': inv.pk,
            'project_name': inv.project.name if inv.project_id else '—',
            'project_id': inv.project_id,
            'retention_amount': inv.retention_amount,
            'subtotal': inv.subtotal,
            'retention_percent': inv.retention_percent,
            'invoice_date': inv.invoice_date,
        })
    return rows
