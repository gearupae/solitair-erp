"""Shared proforma invoice form validation and amount calculation."""
from decimal import Decimal

from .proforma_calculation import compute_proforma_amounts


def apply_proforma_form_data(proforma, estimate, post_data):
    """Validate POST data, compute amounts, apply to proforma instance."""
    name = (post_data.get('name') or '').strip()
    description = (post_data.get('description') or '').strip()
    charge_type = (post_data.get('charge_type') or '').strip()
    charge_value = post_data.get('charge_value')

    if not name:
        raise ValueError('Name is required.')
    if charge_type not in ('percent', 'amount'):
        raise ValueError('Select percentage or amount.')

    exclude_pk = proforma.pk if getattr(proforma, 'pk', None) else None
    line_subtotal, vat_amount, total_amount = compute_proforma_amounts(
        estimate,
        charge_type,
        charge_value,
        exclude_proforma_pk=exclude_pk,
    )

    proforma.name = name
    proforma.description = description
    proforma.charge_type = charge_type
    proforma.charge_value = Decimal(str(charge_value))
    proforma.line_subtotal = line_subtotal
    proforma.vat_amount = vat_amount
    proforma.total_amount = total_amount
    return proforma
