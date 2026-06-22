"""Draft payroll generation — shared by management command and UI."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Q

from apps.hr.models import Employee, Payroll
from apps.hr.models_extended import PayrollAllowanceLine, PayrollTemplate
from apps.settings_app.models import Company


def generate_draft_payrolls_for_month(
    year: int,
    month: int,
    *,
    company_id: int | None = None,
    location: str | None = None,
) -> tuple[int, str]:
    """
    Create draft Payroll rows (skip existing employee+month). Uses employee salary template
    when set; else copies allowance lines from last payroll; else picks a matching PayrollTemplate.
    Returns (created_count, descriptive_suffix_for_logging).
    """
    mf = date(year, month, 1)

    emps = Employee.objects.filter(is_active=True, status='active').select_related('company', 'salary_template')
    if company_id:
        emps = emps.filter(company_id=company_id)
    if location and location.upper() in ('UAE', 'KSA'):
        loc = location.lower()
        emps = emps.filter(location=loc)

    created = 0
    for emp in emps:
        pay, was_created = Payroll.objects.get_or_create(
            employee=emp,
            month=mf,
            defaults={
                'basic_salary': emp.basic_salary or Decimal('0'),
                'allowances': Decimal('0'),
                'deductions': Decimal('0'),
                'status': 'draft',
                'company_id': emp.company_id,
            },
        )
        if not was_created:
            continue

        if not pay.company_id and emp.company_id:
            Payroll.objects.filter(pk=pay.pk).update(company_id=emp.company_id)

        bs = emp.basic_salary or Decimal('0')
        Payroll.objects.filter(pk=pay.pk).update(basic_salary=bs)

        if getattr(emp, 'salary_template_id', None):
            tmpl = emp.salary_template
            for row in tmpl.allowance_lines or []:
                if not isinstance(row, dict):
                    continue
                code = (row.get('code') or 'OTHER')[:40]
                desc = (row.get('description') or '')[:200]
                try:
                    amt = Decimal(str(row.get('amount') or '0')).quantize(Decimal('0.01'))
                except Exception:
                    amt = Decimal('0')
                if amt <= 0:
                    continue
                PayrollAllowanceLine.objects.create(
                    payroll=pay,
                    code=code,
                    description=desc or code,
                    amount=amt,
                    is_taxable=False,
                    source=PayrollAllowanceLine.SOURCE_AUTO,
                )
        else:
            last = (
                Payroll.objects.filter(employee=emp)
                .exclude(month=mf)
                .order_by('-month')
                .prefetch_related('allowance_lines')
                .first()
            )

            if last and last.allowance_lines.exclude(source=PayrollAllowanceLine.SOURCE_ATTENDANCE).exists():
                for ln in last.allowance_lines.exclude(source=PayrollAllowanceLine.SOURCE_ATTENDANCE):
                    PayrollAllowanceLine.objects.create(
                        payroll=pay,
                        code=ln.code,
                        description=ln.description,
                        amount=ln.amount,
                        is_taxable=ln.is_taxable,
                        source=PayrollAllowanceLine.SOURCE_AUTO,
                    )
                bs_last = last.basic_salary or emp.basic_salary or Decimal('0')
                Payroll.objects.filter(pk=pay.pk).update(basic_salary=bs_last)
            else:
                tmpl = _pick_template(emp)
                if tmpl:
                    for row in tmpl.allowance_lines or []:
                        if not isinstance(row, dict):
                            continue
                        code = (row.get('code') or 'OTHER')[:40]
                        desc = (row.get('description') or '')[:200]
                        try:
                            amt = Decimal(str(row.get('amount') or '0')).quantize(Decimal('0.01'))
                        except Exception:
                            amt = Decimal('0')
                        if amt <= 0:
                            continue
                        PayrollAllowanceLine.objects.create(
                            payroll=pay,
                            code=code,
                            description=desc or code,
                            amount=amt,
                            is_taxable=False,
                            source=PayrollAllowanceLine.SOURCE_AUTO,
                        )
                    bs_t = tmpl.basic_salary or emp.basic_salary or Decimal('0')
                    if bs_t and bs_t != bs:
                        Payroll.objects.filter(pk=pay.pk).update(basic_salary=bs_t)

        pay.refresh_from_db()
        from apps.hr.payroll_processing import apply_payroll_computations

        apply_payroll_computations(pay)
        created += 1

    suffix = f'{mf:%B %Y}'
    if company_id:
        co = Company.objects.filter(pk=company_id).first()
        if co:
            suffix = f'{co.name} · {suffix}'
    if location:
        suffix = f'{suffix} ({location.upper()})'
    return created, suffix


def _pick_template(emp: Employee) -> PayrollTemplate | None:
    loc = (emp.location or 'uae').lower()
    qs = PayrollTemplate.objects.filter(is_active=True).filter(
        Q(company_id=emp.company_id) | Q(company__isnull=True)
    )
    qs = qs.filter(Q(location='both') | Q(location=loc))
    return qs.order_by('-company_id', 'name').first()
