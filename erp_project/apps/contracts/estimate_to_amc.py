"""Create an AMC contract from a quotation-won estimate."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.contracts.models import Contract, ContractType


def quotation_terms_for_amc(estimate) -> str:
    """Plain-text terms copied from the won quotation."""
    terms = (estimate.terms_and_conditions or '').strip()
    if terms:
        return terms
    return (estimate.client_note or '').strip()


def _estimate_amc_category(estimate) -> str:
    customer = estimate.customer
    mapping = {
        'fire_protection_system': 'fire_alarm',
        'gas_protection_system': 'gas',
        'cctv': 'cctv',
        'smoke_management_system': 'general_maintenance',
    }
    if customer and customer.job_type:
        for code in customer.job_type:
            if code in mapping:
                return mapping[code]
    if estimate.type_of_work == 'amc':
        return 'general_maintenance'
    return 'general_maintenance'


def _estimate_service_site(estimate) -> str:
    customer = estimate.customer
    if not customer:
        return ''
    parts = []
    if customer.company:
        parts.append(customer.company.strip())
    if customer.address:
        parts.append(customer.address.strip())
    city_bits = [x for x in (customer.city, customer.country) if x]
    if city_bits:
        parts.append(', '.join(city_bits))
    return '\n'.join(parts)


def _default_contract_dates(estimate):
    today = timezone.now().date()
    start = estimate.date or today
    if estimate.valid_until and estimate.valid_until > start:
        end = estimate.valid_until
    else:
        end = start + timedelta(days=365)
    return start, end


def _ensure_amc_contract_type() -> ContractType:
    ct, _ = ContractType.objects.get_or_create(name='AMC')
    return ct


def _resolve_salesperson(estimate):
    if estimate.sales_engineer_id:
        return estimate.sales_engineer
    customer = estimate.customer
    if customer and customer.assigned_salesperson_id:
        return customer.assigned_salesperson
    return None


@transaction.atomic
def create_amc_from_estimate(*, estimate):
    """
    Create an AMC contract from a quotation-won estimate.
    Copies quotation terms & conditions; links quotation, customer, and project.
    """
    customer = estimate.customer
    start, end = _default_contract_dates(estimate)
    terms = quotation_terms_for_amc(estimate)

    desc_parts = []
    if estimate.notes:
        desc_parts.append(estimate.notes.strip())
    desc_parts.append(
        f'Created from won quotation {estimate.display_estimate_number}.'
    )
    description = '\n\n'.join(desc_parts)

    name = f'AMC — {estimate.display_estimate_number}'
    if customer:
        label = (customer.company or customer.name or '').strip()
        if label:
            name = f'{name} — {label}'
    name = name[:255]

    today = timezone.now().date()
    status = 'upcoming' if start > today else 'active'

    contract = Contract.objects.create(
        customer=customer,
        salesperson=_resolve_salesperson(estimate),
        source_estimate=estimate,
        project=estimate.project,
        amc_category=_estimate_amc_category(estimate),
        service_site=_estimate_service_site(estimate),
        name=name,
        contract_value=estimate.total_amount or Decimal('0.00'),
        start_date=start,
        end_date=end,
        planned_visits=0,
        remind_before_days=30,
        description=description[:5000],
        terms_and_conditions=terms,
        status=status,
    )
    contract.contract_types.add(_ensure_amc_contract_type())
    return contract
