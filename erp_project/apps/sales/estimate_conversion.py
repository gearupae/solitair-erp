"""Estimate → project conversion eligibility (B2B compliance, linked project state)."""
from __future__ import annotations

from apps.crm.customer_compliance import (
    b2b_compliance_missing_labels,
    b2b_compliance_warning_message,
    b2b_has_compliance_for_project_conversion,
    customer_is_b2b,
)


def estimate_customer_b2b_compliance_ok(estimate) -> bool:
    customer = getattr(estimate, 'customer', None)
    return b2b_has_compliance_for_project_conversion(customer)


def estimate_convert_to_project_block_reason(estimate) -> str:
    """
    Empty string if conversion is allowed (status/permissions checked elsewhere).
    """
    if not estimate.allows_follow_on_conversion:
        return 'Only quotation-won estimates can be converted to a project.'
    if estimate.project_id:
        project = estimate.project
        if project and getattr(project, 'status', None) == 'draft':
            if getattr(project, 'conversion_approval_status', 'none') == 'pending':
                return (
                    f'A project ({project.project_code}) is already awaiting conversion approval. '
                    'Open the project to approve or reject it.'
                )
        return 'This estimate is already linked to a project.'
    if not estimate_customer_b2b_compliance_ok(estimate):
        missing = b2b_compliance_missing_labels(estimate.customer)
        if missing:
            return (
                'B2B customer must have VAT (TRN), TRN document, and trade license on file. '
                f'Missing: {", ".join(missing)}. '
                'Update the customer record in CRM, then convert to project.'
            )
    return ''


def warn_on_quotation_won_if_b2b_incomplete(estimate) -> str:
    """Warning message after marking won (B2B only); empty if nothing to warn."""
    return b2b_compliance_warning_message(estimate.customer)


def estimate_show_b2b_compliance_banner(estimate) -> bool:
    return (
        estimate.status == 'quotation_won'
        and customer_is_b2b(estimate.customer)
        and not estimate_customer_b2b_compliance_ok(estimate)
        and not estimate.project_id
    )


def estimate_convert_to_amc_block_reason(estimate) -> str:
    """Empty string if a won quotation may be converted to an AMC contract."""
    if not estimate.allows_follow_on_conversion:
        return 'Only quotation-won estimates can be converted to an AMC contract.'
    if estimate.has_amc_contract:
        existing = estimate.primary_amc_contract
        if existing:
            return (
                f'This quotation is already linked to AMC {existing.contract_number}. '
                'Open the contract to edit or use Renew AMC for a new period.'
            )
        return 'This quotation already has an AMC contract.'
    return ''
