"""Calculate proforma invoice line amounts from a won quotation."""
from decimal import Decimal, InvalidOperation


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'))


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


def compute_proforma_amounts(estimate, charge_type: str, charge_value) -> tuple[Decimal, Decimal, Decimal]:
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
    return line_subtotal, line_vat, total
