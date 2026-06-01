"""Calculate proforma invoice line amounts from a won quotation."""
from decimal import Decimal, InvalidOperation

from django.db.models import Sum


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'))


def _format_aed(value: Decimal) -> str:
    return f'AED {_quantize(value)}'


def resolve_quotation_totals(estimate) -> tuple[Decimal, Decimal]:
    """Return (subtotal excl. VAT, total incl. VAT) for the quotation."""
    est_subtotal = estimate.subtotal or Decimal('0.00')
    if est_subtotal <= 0:
        est_subtotal = sum(
            (item.total or Decimal('0')) for item in estimate.items.all()
        ) or Decimal('0.00')

    est_total = estimate.total_amount or Decimal('0.00')
    if est_total <= 0:
        est_vat = estimate.vat_amount or Decimal('0.00')
        est_total = _quantize(est_subtotal + est_vat)

    return est_subtotal, est_total


def proforma_billed_sums(estimate, exclude_proforma_pk=None) -> tuple[Decimal, Decimal]:
    """Return (billed subtotal excl. VAT, billed total incl. VAT) for existing proformas."""
    qs = estimate.proforma_invoices.all()
    if exclude_proforma_pk:
        qs = qs.exclude(pk=exclude_proforma_pk)
    agg = qs.aggregate(sub=Sum('line_subtotal'), tot=Sum('total_amount'))
    billed_sub = agg['sub'] or Decimal('0.00')
    billed_tot = agg['tot'] or Decimal('0.00')
    return billed_sub, billed_tot


def proforma_billing_limits(estimate, exclude_proforma_pk=None) -> dict:
    """Caps for a new or edited proforma against the quotation."""
    est_subtotal, est_total = resolve_quotation_totals(estimate)
    billed_sub, billed_tot = proforma_billed_sums(estimate, exclude_proforma_pk)
    remaining_sub = max(est_subtotal - billed_sub, Decimal('0.00'))
    remaining_tot = max(est_total - billed_tot, Decimal('0.00'))
    max_percent = Decimal('0.00')
    if est_subtotal > 0 and remaining_sub > 0:
        max_percent = _quantize(remaining_sub / est_subtotal * Decimal('100'))
    return {
        'est_subtotal': est_subtotal,
        'est_total': est_total,
        'billed_subtotal': billed_sub,
        'billed_total': billed_tot,
        'remaining_subtotal': remaining_sub,
        'remaining_total': remaining_tot,
        'max_percent': max_percent,
    }


def resolve_proforma_vat_rate_percent(estimate) -> Decimal:
    """
    VAT % for proforma lines when quotation header VAT is missing or zero.
    Uses quotation effective rate, line tax codes, then company default tax code.
    """
    subtotal = estimate.subtotal or Decimal('0.00')
    vat = estimate.vat_amount or Decimal('0.00')

    if subtotal > 0 and vat > 0:
        return _quantize(vat / subtotal * Decimal('100'))

    items = list(estimate.items.select_related('tax_code').all())
    if items:
        item_sub = sum((item.total or Decimal('0')) for item in items)
        item_vat = sum((item.vat_amount or Decimal('0')) for item in items)
        if item_sub > 0 and item_vat > 0:
            return _quantize(item_vat / item_sub * Decimal('100'))
        for item in items:
            if item.tax_code_id and (item.vat_rate or 0) > 0:
                return Decimal(str(item.vat_rate))
            if item.tax_code_id and (item.tax_code.rate or 0) > 0:
                return Decimal(str(item.tax_code.rate))

    from apps.finance.models import TaxCode

    default = TaxCode.objects.filter(is_active=True, is_default=True).first()
    if default and (default.rate or 0) > 0:
        return Decimal(str(default.rate))

    fallback = TaxCode.objects.filter(is_active=True, rate__gt=0).order_by('code').first()
    if fallback:
        return Decimal(str(fallback.rate))

    return Decimal('0.00')


def validate_proforma_within_quotation(
    estimate,
    charge_type: str,
    charge_value,
    line_subtotal: Decimal,
    total_amount: Decimal,
    *,
    exclude_proforma_pk=None,
) -> None:
    """Ensure this proforma does not bill more than the quotation (incl. other proformas)."""
    limits = proforma_billing_limits(estimate, exclude_proforma_pk)

    if limits['est_total'] <= 0:
        raise ValueError('Quotation has no total amount to bill against.')

    if limits['remaining_total'] <= 0:
        raise ValueError(
            'This quotation is already fully covered by proforma invoice(s) '
            f'(quotation total {_format_aed(limits["est_total"])}).'
        )

    if charge_type == 'percent':
        est_subtotal = limits['est_subtotal']
        if est_subtotal > 0 and charge_value > limits['max_percent']:
            raise ValueError(
                f'Percentage cannot exceed {limits["max_percent"]}% '
                f'({_format_aed(limits["remaining_subtotal"])} of quotation subtotal remains unbilled).'
            )
    elif charge_type == 'amount' and line_subtotal > limits['remaining_subtotal']:
        raise ValueError(
            f'Amount cannot exceed {_format_aed(limits["remaining_subtotal"])} '
            f'(quotation subtotal remaining unbilled).'
        )

    if total_amount > limits['remaining_total']:
        raise ValueError(
            f'Proforma total {_format_aed(total_amount)} exceeds what is left on this quotation. '
            f'Quotation total is {_format_aed(limits["est_total"])}; '
            f'{_format_aed(limits["billed_total"])} is already on other proforma(s). '
            f'Maximum for this proforma: {_format_aed(limits["remaining_total"])} (incl. VAT).'
        )


def compute_proforma_amounts(
    estimate,
    charge_type: str,
    charge_value,
    *,
    exclude_proforma_pk=None,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Return (line_subtotal excl. VAT, vat_amount, total_amount incl. VAT).

    Percentage is applied to the quotation subtotal (excl. VAT).
    VAT uses the quotation effective rate or default tax code when header VAT is zero.
    """
    try:
        value = Decimal(str(charge_value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Enter a valid number for the charge value.')

    if value <= 0:
        raise ValueError('Charge value must be greater than zero.')

    est_subtotal = estimate.subtotal or Decimal('0.00')
    if est_subtotal <= 0:
        est_subtotal = sum(
            (item.total or Decimal('0')) for item in estimate.items.all()
        ) or Decimal('0.00')

    if charge_type == 'percent':
        if value > Decimal('100'):
            raise ValueError('Percentage cannot exceed 100%.')
        line_subtotal = _quantize(est_subtotal * value / Decimal('100'))
    elif charge_type == 'amount':
        line_subtotal = _quantize(value)
    else:
        raise ValueError('Invalid charge type.')

    vat_rate_pct = resolve_proforma_vat_rate_percent(estimate)
    if vat_rate_pct > 0:
        line_vat = _quantize(line_subtotal * vat_rate_pct / Decimal('100'))
    else:
        est_vat = estimate.vat_amount or Decimal('0.00')
        if est_subtotal > 0 and est_vat > 0:
            line_vat = _quantize(line_subtotal * est_vat / est_subtotal)
        else:
            line_vat = Decimal('0.00')

    total = _quantize(line_subtotal + line_vat)

    validate_proforma_within_quotation(
        estimate,
        charge_type,
        value,
        line_subtotal,
        total,
        exclude_proforma_pk=exclude_proforma_pk,
    )

    return line_subtotal, line_vat, total
