"""Structural salary / gross (basic + non-variable allowances) for payroll and daily-rate logic."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from apps.hr.models_extended import PayrollAllowanceLine, PayrollTemplate

_OT_LINE = Q(source=PayrollAllowanceLine.SOURCE_ATTENDANCE, code=PayrollAllowanceLine.CODE_OVERTIME)


def template_allowances_total(tmpl: PayrollTemplate | None) -> Decimal:
    if not tmpl or not tmpl.allowance_lines:
        return Decimal('0.00')
    total = Decimal('0')
    for row in tmpl.allowance_lines:
        if not isinstance(row, dict):
            continue
        try:
            total += Decimal(str(row.get('amount') or '0').replace(',', '').strip() or '0')
        except Exception:
            continue
    return total.quantize(Decimal('0.01'))


def structural_allowances_total(payroll) -> Decimal:
    """Sum allowance lines except variable attendance overtime."""
    t = PayrollAllowanceLine.objects.filter(payroll=payroll).exclude(_OT_LINE).aggregate(s=Sum('amount'))['s']
    return (t or Decimal('0')).quantize(Decimal('0.01'))


def total_salary_for_daily_rate(payroll) -> Decimal:
    """Gross package used for unpaid / absence / sick daily rate (excludes overtime)."""
    basic = payroll.basic_salary or Decimal('0')
    return (basic + structural_allowances_total(payroll)).quantize(Decimal('0.01'))


def compute_gross_salary_structural(payroll) -> Decimal:
    """Persisted gross_salary: basic + structural allowances (no OT)."""
    return total_salary_for_daily_rate(payroll)


def working_days_divisor_from_settings(settings) -> int:
    return max(int(getattr(settings, 'working_days_in_month', None) or 30), 1)


def seed_allowance_lines_from_template(payroll, tmpl: PayrollTemplate) -> None:
    """Replace non-attendance allowance lines with template JSON (draft payroll)."""
    if payroll.status != 'draft':
        return
    PayrollAllowanceLine.objects.filter(payroll=payroll).exclude(
        source=PayrollAllowanceLine.SOURCE_ATTENDANCE
    ).delete()
    for row in tmpl.allowance_lines or []:
        if not isinstance(row, dict):
            continue
        code = (row.get('code') or 'OTHER')[:40]
        desc = (row.get('description') or '')[:200] or code
        try:
            amt = Decimal(str(row.get('amount') or '0').replace(',', '').strip()).quantize(Decimal('0.01'))
        except Exception:
            amt = Decimal('0')
        if amt <= 0:
            continue
        PayrollAllowanceLine.objects.create(
            payroll=payroll,
            code=code,
            description=desc,
            amount=amt,
            is_taxable=False,
            source=PayrollAllowanceLine.SOURCE_AUTO,
        )


def ensure_payroll_allowances_from_employee_template(payroll, employee) -> None:
    """
    If draft payroll has no structural allowance lines and employee has salary_template,
    populate from template. Does not override basic_salary (caller sets from employee).
    """
    if payroll.status != 'draft' or not employee or not getattr(employee, 'salary_template_id', None):
        return
    has_structural = PayrollAllowanceLine.objects.filter(payroll=payroll).exclude(_OT_LINE).exists()
    # Allow OT-only attendance lines
    if has_structural:
        return
    tmpl = employee.salary_template
    if tmpl:
        seed_allowance_lines_from_template(payroll, tmpl)


def refresh_payroll_gross_and_allowances(payroll, *, save: bool = True) -> None:
    from apps.hr.payroll_allowances import total_allowances_amount

    payroll.allowances = total_allowances_amount(payroll)
    payroll.gross_salary = compute_gross_salary_structural(payroll)
    ded = payroll.deductions or Decimal('0')
    payroll.net_salary = (
        (payroll.basic_salary or Decimal('0')) + payroll.allowances - ded
    ).quantize(Decimal('0.01'))
    if save:
        payroll.save(update_fields=['allowances', 'gross_salary', 'net_salary'])
