"""UAE end-of-service gratuity (EOSG) — Federal Decree-Law No. 33 of 2021."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta

OLD_LAW_CUTOFF = date(2022, 2, 2)
TERMINATION_RESIGNED = 'resigned'
TERMINATION_TERMINATED = 'terminated'
TERMINATION_REDUNDANCY = 'redundancy'
TERMINATION_CONTRACT_END = 'contract_end'
FULL_ENTITLEMENT_TERMINATIONS = frozenset(
    {TERMINATION_TERMINATED, TERMINATION_REDUNDANCY, TERMINATION_CONTRACT_END}
)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def years_of_service_decimal(joining_date: date | None, as_of_date: date) -> Decimal:
    if not joining_date or joining_date > as_of_date:
        return Decimal('0.00')
    days = (as_of_date - joining_date).days
    return _quantize(Decimal(days) / Decimal('365.25'))


def format_years_of_service_human(joining_date: date | None, as_of_date: date | None = None) -> str:
    as_of = as_of_date or date.today()
    if not joining_date or joining_date > as_of:
        return '—'
    delta = relativedelta(as_of, joining_date)
    parts = []
    if delta.years:
        parts.append(f'{delta.years} year{"s" if delta.years != 1 else ""}')
    if delta.months:
        parts.append(f'{delta.months} month{"s" if delta.months != 1 else ""}')
    if not parts:
        days = max((as_of - joining_date).days, 0)
        return f'{days} day{"s" if days != 1 else ""}'
    return ' '.join(parts)


def _resignation_adjustment_factor(
    employee,
    years: Decimal,
    termination_type: str | None,
) -> Decimal:
    term = (termination_type or TERMINATION_TERMINATED).strip().lower()
    if term in FULL_ENTITLEMENT_TERMINATIONS:
        return Decimal('1')

    join = getattr(employee, 'date_of_joining', None)
    contract_type = (getattr(employee, 'contract_type', None) or 'limited').strip().lower()
    if contract_type != 'unlimited' or not join or join >= OLD_LAW_CUTOFF:
        return Decimal('1')

    if years < Decimal('1'):
        return Decimal('0')
    if years < Decimal('3'):
        return Decimal('1') / Decimal('3')
    if years < Decimal('5'):
        return Decimal('2') / Decimal('3')
    return Decimal('1')


def calculate_uae_gratuity(employee, as_of_date=None, termination_type=None) -> dict:
    """
    Compute UAE EOSG for an employee. Returns amounts in AED; live calculation only.
    UAE nationals are excluded (GPSSA applies instead).
    """
    as_of = as_of_date or date.today()
    basic = (getattr(employee, 'basic_salary', None) or Decimal('0')).quantize(Decimal('0.01'))

    if getattr(employee, 'is_uae_national', False):
        return {
            'applicable': False,
            'message': 'UAE National — covered under GPSSA pension scheme. No gratuity applies.',
            'years_of_service': Decimal('0.00'),
            'years_of_service_display': format_years_of_service_human(
                getattr(employee, 'date_of_joining', None), as_of
            ),
            'daily_rate': Decimal('0.00'),
            'raw_gratuity': Decimal('0.00'),
            'adjustment_factor': Decimal('0.00'),
            'final_gratuity': Decimal('0.00'),
            'cap_applied': False,
            'cap_amount': Decimal('0.00'),
            'as_of_date': as_of,
        }

    join = getattr(employee, 'date_of_joining', None)
    years = years_of_service_decimal(join, as_of)
    daily_rate = _quantize(basic / Decimal('30')) if basic else Decimal('0.00')

    if years < Decimal('1'):
        raw_gratuity = Decimal('0.00')
    elif years <= Decimal('5'):
        raw_gratuity = _quantize(daily_rate * Decimal('21') * years)
    else:
        first_5 = _quantize(daily_rate * Decimal('21') * Decimal('5'))
        remaining = _quantize(daily_rate * Decimal('30') * (years - Decimal('5')))
        raw_gratuity = _quantize(first_5 + remaining)

    cap_amount = _quantize(basic * Decimal('24'))
    cap_applied = raw_gratuity > cap_amount
    gratuity_capped = min(raw_gratuity, cap_amount) if raw_gratuity else Decimal('0.00')

    factor = _resignation_adjustment_factor(employee, years, termination_type)
    final_gratuity = _quantize(gratuity_capped * factor)

    return {
        'applicable': True,
        'message': '',
        'years_of_service': years,
        'years_of_service_display': format_years_of_service_human(join, as_of),
        'daily_rate': daily_rate,
        'raw_gratuity': gratuity_capped,
        'adjustment_factor': factor,
        'final_gratuity': final_gratuity,
        'cap_applied': cap_applied,
        'cap_amount': cap_amount,
        'as_of_date': as_of,
        'termination_type': (termination_type or TERMINATION_TERMINATED).strip().lower(),
    }


def calculate_monthly_gratuity_provision(employee, as_of_date=None) -> Decimal:
    """
    Employer monthly gratuity provision (informational, not deducted from net pay).
    <5 years: (basic/30)*21/12  |  >=5 years: (basic/30)*30/12
    """
    if getattr(employee, 'is_uae_national', False):
        return Decimal('0.00')

    as_of = as_of_date or date.today()
    basic = (getattr(employee, 'basic_salary', None) or Decimal('0')).quantize(Decimal('0.01'))
    if basic <= 0:
        return Decimal('0.00')

    daily_rate = basic / Decimal('30')
    years = years_of_service_decimal(getattr(employee, 'date_of_joining', None), as_of)
    if years >= Decimal('5'):
        monthly = daily_rate * Decimal('30') / Decimal('12')
    else:
        monthly = daily_rate * Decimal('21') / Decimal('12')
    return _quantize(monthly)


def employee_gratuity_eligible(employee) -> bool:
    loc = (getattr(employee, 'location', None) or 'uae').strip().lower()
    if loc != 'uae':
        return False
    if getattr(employee, 'is_uae_national', False):
        return False
    return True
