"""B2B customer TRN / trade document checks for sales follow-on actions."""
from __future__ import annotations


def customer_is_b2b(customer) -> bool:
    if not customer:
        return False
    return (getattr(customer, 'business_segment', None) or '').strip().lower() == 'b2b'


def customer_is_b2c(customer) -> bool:
    if not customer:
        return False
    return (getattr(customer, 'business_segment', None) or '').strip().lower() == 'b2c'


def b2b_compliance_missing_labels(customer) -> list[str]:
    """Human-readable list of missing B2B compliance items (empty if OK or not B2B)."""
    if not customer or not customer_is_b2b(customer):
        return []
    missing = []
    if not (getattr(customer, 'trn', None) or '').strip():
        missing.append('VAT (TRN) number')
    if not _file_uploaded(getattr(customer, 'trn_document', None)):
        missing.append('TRN document')
    if not _file_uploaded(getattr(customer, 'trade_license_document', None)):
        missing.append('Trade license document')
    return missing


def b2b_has_compliance_for_project_conversion(customer) -> bool:
    """B2C and non-B2B segments skip checks; B2B must have TRN + both documents."""
    if not customer_is_b2b(customer):
        return True
    return len(b2b_compliance_missing_labels(customer)) == 0


def b2b_compliance_warning_message(customer) -> str:
    missing = b2b_compliance_missing_labels(customer)
    if not missing:
        return ''
    items = ', '.join(missing)
    return (
        f'This B2B customer is missing: {items}. '
        'Please add them under CRM → Customers before converting this quotation to a project. '
        'The quotation was marked won.'
    )


def _file_uploaded(field) -> bool:
    try:
        return bool(field and field.name)
    except Exception:
        return False
