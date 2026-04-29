"""Payroll allowance lines — standard UAE codes and draft sync from POST."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from apps.hr.models_extended import PayrollAllowanceLine


def effective_payroll_company(payroll):
    """Legal entity for WPS/GOSI/reporting: Payroll.company, else Employee.company."""
    if getattr(payroll, 'company_id', None):
        return payroll.company
    emp = getattr(payroll, 'employee', None)
    if emp and getattr(emp, 'company_id', None):
        return emp.company
    return None


def payrolls_for_company_entity(qs, company):
    """Filter payroll queryset for rows belonging to company entity (explicit FK or via employee)."""
    if not company:
        return qs.none()
    return qs.filter(Q(company_id=company.pk) | Q(company__isnull=True, employee__company_id=company.pk))


def uae_company_payroll_filter(qs):
    from apps.settings_app.models import Company

    uae_ids = list(Company.objects.filter(is_active=True, country='uae').values_list('pk', flat=True))
    if not uae_ids:
        return qs.none()
    return qs.filter(Q(company_id__in=uae_ids) | Q(company__isnull=True, employee__company_id__in=uae_ids))


def ksa_company_payroll_filter(qs):
    from apps.settings_app.models import Company

    ksa_ids = list(Company.objects.filter(is_active=True, country='ksa').values_list('pk', flat=True))
    if not ksa_ids:
        return qs.none()
    return qs.filter(Q(company_id__in=ksa_ids) | Q(company__isnull=True, employee__company_id__in=ksa_ids))


STANDARD_UAE_ALLOWANCE_CHOICES = [
    (PayrollAllowanceLine.CODE_HOUSING, 'Housing Allowance'),
    (PayrollAllowanceLine.CODE_TRANSPORT, 'Transport Allowance'),
    (PayrollAllowanceLine.CODE_FOOD, 'Food Allowance'),
    (PayrollAllowanceLine.CODE_PHONE, 'Phone Allowance'),
    (PayrollAllowanceLine.CODE_OTHER, 'Other Allowance'),
]

# Salary template + payroll form dropdowns (short labels)
TEMPLATE_ALLOWANCE_CHOICES = [
    (PayrollAllowanceLine.CODE_HOUSING, 'Housing'),
    (PayrollAllowanceLine.CODE_TRANSPORT, 'Transport'),
    (PayrollAllowanceLine.CODE_FOOD, 'Food'),
    (PayrollAllowanceLine.CODE_PHONE, 'Phone'),
    (PayrollAllowanceLine.CODE_EDUCATION, 'Education'),
    (PayrollAllowanceLine.CODE_CAR, 'Car'),
    (PayrollAllowanceLine.CODE_CLOTHING, 'Clothing'),
    (PayrollAllowanceLine.CODE_OTHER, 'Other'),
]

TEMPLATE_ALLOWANCE_DEFAULT_DESCRIPTION = {
    PayrollAllowanceLine.CODE_HOUSING: 'Housing allowance',
    PayrollAllowanceLine.CODE_TRANSPORT: 'Transport allowance',
    PayrollAllowanceLine.CODE_FOOD: 'Food allowance',
    PayrollAllowanceLine.CODE_PHONE: 'Phone allowance',
    PayrollAllowanceLine.CODE_EDUCATION: 'Education allowance',
    PayrollAllowanceLine.CODE_CAR: 'Car allowance',
    PayrollAllowanceLine.CODE_CLOTHING: 'Clothing allowance',
    PayrollAllowanceLine.CODE_OTHER: 'Other allowance',
}


def standard_allowance_label(code: str) -> str:
    return dict(STANDARD_UAE_ALLOWANCE_CHOICES).get(code, code)


def template_default_description(code: str) -> str:
    return TEMPLATE_ALLOWANCE_DEFAULT_DESCRIPTION.get(code, standard_allowance_label(code))


def allowance_lines_json_from_post(post_data, prefix: str = 'tpl_') -> list:
    """Build allowance_lines JSON list from POST (template or shared naming)."""
    codes = post_data.getlist(f'{prefix}allowance_code[]')
    descriptions = post_data.getlist(f'{prefix}allowance_description[]')
    amounts = post_data.getlist(f'{prefix}allowance_amount[]')
    out = []
    for i, code in enumerate(codes):
        code = (code or '').strip()
        if not code:
            continue
        desc = (descriptions[i] if i < len(descriptions) else '').strip() or template_default_description(code)
        raw_amt = (amounts[i] if i < len(amounts) else '') or '0'
        try:
            amt = Decimal(str(raw_amt).replace(',', '').strip())
        except Exception:
            amt = Decimal('0')
        if amt <= 0:
            continue
        out.append({'code': code[:40], 'description': desc[:200], 'amount': str(amt.quantize(Decimal('0.01')))})
    return out


def allowance_lines_from_hidden_json(raw: str | None) -> list:
    """
    Parse template form hidden `allowance_lines` JSON; amounts as Decimal-quantized strings.
    """
    import json

    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for line in data:
        if not isinstance(line, dict):
            continue
        code = (line.get('code') or '').strip()
        if not code:
            continue
        desc = (line.get('description') or '').strip() or template_default_description(code)
        try:
            amt = Decimal(str(line.get('amount', '0')).replace(',', '').strip()).quantize(Decimal('0.01'))
        except Exception:
            amt = Decimal('0')
        if amt <= 0:
            continue
        out.append(
            {
                'code': code[:40],
                'description': desc[:200],
                'amount': str(amt),
            }
        )
    return out


def normalize_template_allowance_lines_json(lines: list | None) -> list:
    """Return allowance_lines list with amounts as quantized decimal strings (for JSON/API/display)."""
    if not lines:
        return []
    out = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        code = (line.get('code') or '').strip()
        if not code:
            continue
        desc = (line.get('description') or '').strip() or template_default_description(code)
        try:
            amt = Decimal(str(line.get('amount', '0')).replace(',', '').strip()).quantize(Decimal('0.01'))
        except Exception:
            amt = Decimal('0')
        if amt <= 0:
            continue
        out.append({'code': code[:40], 'description': desc[:200], 'amount': str(amt)})
    return out


def total_allowances_amount(payroll) -> Decimal:
    t = PayrollAllowanceLine.objects.filter(payroll=payroll).aggregate(s=Sum('amount'))['s']
    return (t or Decimal('0')).quantize(Decimal('0.01'))


def replace_allowance_lines_from_post(payroll, post_data) -> Decimal:
    """
    Replace all allowance lines for a draft payroll from form POST (manual rows).
    Does nothing if payroll is not draft.
    """
    if payroll.status != 'draft':
        return total_allowances_amount(payroll)

    PayrollAllowanceLine.objects.filter(payroll=payroll).delete()

    codes = post_data.getlist('allowance_code[]')
    descriptions = post_data.getlist('allowance_description[]')
    amounts = post_data.getlist('allowance_amount[]')

    for i, code in enumerate(codes):
        code = (code or '').strip()
        if not code:
            continue
        desc = (descriptions[i] if i < len(descriptions) else '').strip() or template_default_description(code)
        raw_amt = (amounts[i] if i < len(amounts) else '') or '0'
        try:
            amt = Decimal(str(raw_amt).replace(',', '').strip())
        except Exception:
            amt = Decimal('0')
        if amt <= 0:
            continue
        amt = amt.quantize(Decimal('0.01'))

        PayrollAllowanceLine.objects.create(
            payroll=payroll,
            code=code[:40],
            description=desc[:200],
            amount=amt,
            is_taxable=False,
            source=PayrollAllowanceLine.SOURCE_MANUAL,
        )

    return total_allowances_amount(payroll)
