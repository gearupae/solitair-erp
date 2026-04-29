"""
Payroll computations: attendance deductions, leave deductions, UAE ILOE, KSA GOSI, gratuity (provision).
Updates Payroll allowances, deductions, gross_salary, and net_salary from computed lines.
"""
from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum

from apps.hr.leave_payroll_deductions import (
    half_pay_leave_deduction,
    tiered_sick_leave_deduction,
    unpaid_leave_working_days_in_month_strict,
)
from apps.hr.salary_payroll_utils import (
    structural_allowances_total,
    total_salary_for_daily_rate,
    working_days_divisor_from_settings,
)
from apps.hr.models import Payroll
from apps.hr.models_extended import (
    AdvanceRepayment,
    AttendanceSettings,
    AttendanceSummary,
    EmployeeAdvance,
    EmployeeHRProfile,
    GOSIRecord,
    GratuityRecord,
    KSACompliance,
    PayrollAllowanceLine,
    PayrollDeductionLine,
    PayrollEmployerContribution,
    PayrollSettings,
    UAECompliance,
)

logger = logging.getLogger(__name__)

ILOE_BASIC_THRESHOLD = Decimal('16000')


def compute_iloe_deduction(basic: Decimal) -> tuple[Decimal, str]:
    """
    UAE ILOE employee charge: fixed premium + 5% VAT (not % of basic).
    Category A: basic <= 16,000 → AED 5 + VAT = 5.25
    Category B: basic > 16,000 → AED 10 + VAT = 10.50
    """
    basic = (basic or Decimal('0')).quantize(Decimal('0.01'))
    if basic <= ILOE_BASIC_THRESHOLD:
        premium = Decimal('5.00')
        cat = 'A'
    else:
        premium = Decimal('10.00')
        cat = 'B'
    vat = (premium * Decimal('0.05')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = (premium + vat).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return total, cat


def get_payroll_settings() -> PayrollSettings:
    obj, _ = PayrollSettings.objects.get_or_create(pk=1)
    return obj


def _month_first(d: date) -> date:
    return date(d.year, d.month, 1)


def _years_of_service(join: date | None, as_of: date) -> Decimal:
    if not join:
        return Decimal('0')
    if join > as_of:
        return Decimal('0')
    delta = relativedelta(as_of, join)
    years = delta.years + delta.months / Decimal('12') + delta.days / Decimal('365.25')
    return Decimal(str(round(float(years), 4)))


def calculate_gratuity_uae(basic_monthly: Decimal, years_of_service: Decimal) -> Decimal:
    """UAE-style provision (informational)."""
    if years_of_service < 1:
        return Decimal('0').quantize(Decimal('0.01'))
    daily = (basic_monthly / Decimal('30')).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    if years_of_service <= 5:
        prov = daily * Decimal('21') * years_of_service
    else:
        y = years_of_service
        prov = daily * Decimal('21') * Decimal('5') + daily * Decimal('30') * (y - Decimal('5'))
    return prov.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@transaction.atomic
def apply_payroll_computations(payroll: Payroll) -> None:
    """
    Rebuild auto deduction lines + employer contributions + gratuity snapshot for draft payroll.
    Preserves manual_adjust from Payroll.deductions field as a separate line (HR-entered misc deductions).
    """
    if payroll.status != 'draft':
        return

    payroll.refresh_from_db()
    # HR-entered misc deductions (loans etc.) from draft form — added on top of auto-calculated lines.
    manual_misc = (payroll.deductions or Decimal('0')).quantize(Decimal('0.01'))

    PayrollAllowanceLine.objects.filter(
        payroll=payroll,
        source=PayrollAllowanceLine.SOURCE_ATTENDANCE,
        code=PayrollAllowanceLine.CODE_OVERTIME,
    ).delete()

    PayrollDeductionLine.objects.filter(payroll=payroll).delete()
    PayrollEmployerContribution.objects.filter(payroll=payroll).delete()
    GOSIRecord.objects.filter(payroll=payroll).delete()
    GratuityRecord.objects.filter(payroll=payroll).delete()

    settings = get_payroll_settings()
    emp = payroll.employee

    profile = EmployeeHRProfile.objects.filter(employee=emp).first()
    entity = getattr(emp, 'location', None) or (profile.employment_entity if profile else 'uae')
    uc = UAECompliance.objects.filter(employee=emp).first()
    kc = KSACompliance.objects.filter(employee=emp).first()

    month_start = _month_first(payroll.month)
    summary = AttendanceSummary.objects.filter(employee=emp, month=month_start).first()
    att_set = AttendanceSettings.objects.get_or_create(pk=1)[0]

    wd = working_days_divisor_from_settings(settings)
    basic = payroll.basic_salary
    total_pkg = total_salary_for_daily_rate(payroll)
    per_day = (total_pkg / Decimal(wd)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    finalized = bool(summary and summary.is_finalized)

    if finalized:
        absent_days = int(summary.total_absent or 0)
        absent_amt = (per_day * Decimal(absent_days)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if absent_days > 0:
            PayrollDeductionLine.objects.create(
                payroll=payroll,
                code=PayrollDeductionLine.CODE_ABSENT,
                label=f'Absent Deduction ({absent_days} days @ AED {per_day}/day)',
                amount=absent_amt,
            )

        late_count = summary.total_late if summary else 0
        late_amt = (att_set.late_deduction_amount * Decimal(late_count)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if late_count > 0 and att_set.late_deduction_amount > 0:
            PayrollDeductionLine.objects.create(
                payroll=payroll,
                code=PayrollDeductionLine.CODE_LATE,
                label=f'Late ({late_count}x)',
                amount=late_amt,
            )

        if entity == 'uae':
            from apps.hr.overtime_payroll import compute_uae_overtime_allowance_for_month

            ot_amt, ot_desc, _ot_h = compute_uae_overtime_allowance_for_month(
                employee=emp,
                month_first=month_start,
                basic_salary=basic,
                att_set=att_set,
            )
            if ot_amt > 0 and ot_desc:
                PayrollAllowanceLine.objects.create(
                    payroll=payroll,
                    code=PayrollAllowanceLine.CODE_OVERTIME,
                    description=ot_desc,
                    amount=ot_amt,
                    is_taxable=False,
                    source=PayrollAllowanceLine.SOURCE_ATTENDANCE,
                )
        else:
            wh_day = att_set.working_hours_per_day or Decimal('9')
            hourly_equiv = (per_day / wh_day).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            ot_hours = summary.total_overtime_hours if summary else Decimal('0')
            ot_amt = (
                (ot_hours or Decimal('0')) * hourly_equiv * (att_set.overtime_rate_multiplier or Decimal('1'))
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if ot_amt > 0:
                PayrollAllowanceLine.objects.create(
                    payroll=payroll,
                    code=PayrollAllowanceLine.CODE_OVERTIME,
                    description='Overtime (attendance)',
                    amount=ot_amt,
                    is_taxable=False,
                    source=PayrollAllowanceLine.SOURCE_ATTENDANCE,
                )
    else:
        late_count = 0

    ul_days = unpaid_leave_working_days_in_month_strict(emp, month_start)
    unpaid_amt = (per_day * ul_days).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if ul_days > 0:
        PayrollDeductionLine.objects.create(
            payroll=payroll,
            code=PayrollDeductionLine.CODE_UNPAID_LEAVE,
            label=f'Unpaid Leave ({ul_days} days @ AED {per_day}/day)',
            amount=unpaid_amt,
        )

    half_amt, half_wd = half_pay_leave_deduction(emp, month_start, per_day)
    if half_amt > 0:
        PayrollDeductionLine.objects.create(
            payroll=payroll,
            code=PayrollDeductionLine.CODE_HALF_PAY_LEAVE,
            label=f'Half pay leave ({half_wd} days @ 50% of AED {per_day}/day)',
            amount=half_amt,
        )

    tier_amt, tier_days = tiered_sick_leave_deduction(emp, month_start, per_day)
    if tier_amt > 0:
        PayrollDeductionLine.objects.create(
            payroll=payroll,
            code=PayrollDeductionLine.CODE_SICK_TIERED,
            label=f'Sick Leave Half Pay Deduction ({tier_days} days)',
            amount=tier_amt,
        )

    if entity == 'uae' and (uc is None or uc.iloe_applicable) and settings.iloe_deduct_via_payroll:
        iloe_total, iloe_cat = compute_iloe_deduction(basic)
        if iloe_total > 0:
            PayrollDeductionLine.objects.create(
                payroll=payroll,
                code=PayrollDeductionLine.CODE_ILOE,
                label=f'ILOE Insurance (Cat {iloe_cat})',
                amount=iloe_total,
            )

    loc_norm = (getattr(emp, 'location', None) or '').strip().lower()
    if loc_norm == 'ksa':
        if kc is None or not kc.gosi_applicable:
            logger.warning(
                'GOSI skipped: no KSA compliance or GOSI not applicable for employee %s (%s)',
                emp.pk,
                emp.full_name,
            )
        else:
            gosi_gross = basic
            if kc.nationality == 'saudi':
                emp_pct = Decimal('0.10')
                er_pct = Decimal('0.12')
            else:
                emp_pct = Decimal('0')
                er_pct = Decimal('0.02')

            emp_gosi = (gosi_gross * emp_pct).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            er_gosi = (gosi_gross * er_pct).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_gosi = (emp_gosi + er_gosi).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            nat_code = kc.nationality or 'non_saudi'

            if emp_gosi > 0:
                PayrollDeductionLine.objects.update_or_create(
                    payroll=payroll,
                    code=PayrollDeductionLine.CODE_GOSI_EMPLOYEE,
                    defaults={
                        'label': 'GOSI Employee Contribution',
                        'amount': emp_gosi,
                    },
                )
            if er_gosi > 0:
                PayrollEmployerContribution.objects.update_or_create(
                    payroll=payroll,
                    code=PayrollEmployerContribution.CODE_GOSI_EMPLOYER,
                    defaults={
                        'label': 'GOSI Employer Contribution',
                        'amount': er_gosi,
                    },
                )

            co = payroll.company or getattr(emp, 'company', None)
            GOSIRecord.objects.update_or_create(
                payroll=payroll,
                defaults={
                    'employee': emp,
                    'company': co,
                    'month': month_start,
                    'basic_salary': gosi_gross,
                    'nationality': nat_code,
                    'gosi_number': (kc.gosi_number or '')[:80],
                    'iqama_number': (kc.iqama_number or '')[:20],
                    'employee_rate': emp_pct,
                    'employer_rate': er_pct,
                    'employee_contribution': emp_gosi,
                    'employer_contribution': er_gosi,
                    'total_contribution': total_gosi,
                    'gross_up_basic_for_rates': gosi_gross,
                },
            )

    for adv in EmployeeAdvance.objects.filter(
        employee=emp,
        status=EmployeeAdvance.STATUS_ACTIVE,
        amount_remaining__gt=0,
    ).order_by('pk'):
        rem = adv.amount_remaining
        deduction = adv.monthly_deduction
        if deduction > rem:
            deduction = rem
        if deduction <= 0:
            continue
        PayrollDeductionLine.objects.create(
            payroll=payroll,
            code=PayrollDeductionLine.CODE_ADVANCE_REPAYMENT,
            label=f'Advance repayment ({adv.get_advance_type_display()}) [id:{adv.pk}]',
            amount=deduction,
        )

    if manual_misc > 0:
        PayrollDeductionLine.objects.create(
            payroll=payroll,
            code=PayrollDeductionLine.CODE_MANUAL,
            label='Manual / other deductions',
            amount=manual_misc,
        )

    total_d = (
        PayrollDeductionLine.objects.filter(payroll=payroll).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    ).quantize(Decimal('0.01'))

    total_allow = (
        PayrollAllowanceLine.objects.filter(payroll=payroll).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    ).quantize(Decimal('0.01'))
    payroll.allowances = total_allow
    payroll.gross_salary = (basic + structural_allowances_total(payroll)).quantize(Decimal('0.01'))

    payroll.deductions = total_d
    payroll.save(update_fields=['allowances', 'deductions', 'gross_salary'])
    payroll.calculate_net()

    as_of_day = monthrange(payroll.month.year, payroll.month.month)[1]
    as_of_date = date(payroll.month.year, payroll.month.month, as_of_day)
    if entity == 'uae' and (uc is None or uc.gratuity_applicable):
        yrs = _years_of_service(emp.date_of_joining, as_of_date)
        grat = calculate_gratuity_uae(basic, yrs)
        GratuityRecord.objects.create(
            employee=emp,
            payroll=payroll,
            as_of_date=as_of_date,
            years_of_service=yrs,
            provision_amount=grat,
            notes='Provision per UAE-style rules (informational).',
        )


_ADVANCE_ID_LABEL = re.compile(r'\[id:(\d+)\]')


@transaction.atomic
def finalize_advance_repayments_for_payroll(payroll: Payroll) -> None:
    """After payroll is posted (processed), record repayments and update advance balances."""
    if payroll.status != 'processed':
        return
    for line in payroll.deduction_lines.filter(code=PayrollDeductionLine.CODE_ADVANCE_REPAYMENT):
        m = _ADVANCE_ID_LABEL.search(line.label or '')
        if not m:
            continue
        adv_id = int(m.group(1))
        try:
            adv = EmployeeAdvance.objects.select_for_update().get(pk=adv_id)
        except EmployeeAdvance.DoesNotExist:
            continue
        amt = line.amount
        if AdvanceRepayment.objects.filter(payroll=payroll, advance=adv).exists():
            continue
        AdvanceRepayment.objects.create(
            advance=adv,
            payroll=payroll,
            amount=amt,
            date=payroll.month,
            notes='',
        )
        adv.amount_repaid = (adv.amount_repaid + amt).quantize(Decimal('0.01'))
        adv.amount_remaining = (adv.amount - adv.amount_repaid).quantize(Decimal('0.01'))
        if adv.amount_remaining <= 0:
            adv.amount_remaining = Decimal('0')
            adv.status = EmployeeAdvance.STATUS_FULLY_REPAID
        adv.save(update_fields=['amount_repaid', 'amount_remaining', 'status'])


def estimate_payroll_deductions_preview(
    *,
    employee_pk: int,
    month_first: date,
    basic_salary: Decimal,
    allowances_total: Decimal,
    manual_misc: Decimal,
) -> dict:
    """
    Non-persistent deduction breakdown for the payroll add/edit form.
    Mirrors apply_payroll_computations logic without writing PayrollDeductionLine rows.
    """
    from apps.hr.models import Employee

    emp = Employee.objects.filter(pk=employee_pk, is_active=True).select_related().first()
    if not emp:
        return {
            'absent': Decimal('0'),
            'late': Decimal('0'),
            'unpaid_leave': Decimal('0'),
            'half_pay_leave': Decimal('0'),
            'sick_tiered': Decimal('0'),
            'iloe': Decimal('0'),
            'gosi_employee': Decimal('0'),
            'advance': Decimal('0'),
            'manual': manual_misc,
            'total': manual_misc,
            'estimated_net': basic_salary + allowances_total - manual_misc,
            'attendance_finalized': False,
        }

    settings = get_payroll_settings()
    profile = EmployeeHRProfile.objects.filter(employee=emp).first()
    entity = getattr(emp, 'location', None) or (profile.employment_entity if profile else 'uae')
    uc = UAECompliance.objects.filter(employee=emp).first()
    kc = KSACompliance.objects.filter(employee=emp).first()

    month_start = _month_first(month_first)
    summary = AttendanceSummary.objects.filter(employee=emp, month=month_start).first()
    att_set = AttendanceSettings.objects.get_or_create(pk=1)[0]

    wd = working_days_divisor_from_settings(settings)
    total_pkg = (basic_salary + allowances_total).quantize(Decimal('0.01'))
    finalized = bool(summary and summary.is_finalized)
    per_day = (total_pkg / Decimal(wd)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    absent_amt = Decimal('0')
    late_amt = Decimal('0')
    unpaid_amt = Decimal('0')
    half_amt = Decimal('0')
    tier_amt = Decimal('0')
    if finalized:
        absent_days = int(summary.total_absent or 0)
        absent_amt = (per_day * Decimal(absent_days)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        late_count = summary.total_late if summary else 0
        late_amt = (att_set.late_deduction_amount * Decimal(late_count)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    ul_days = unpaid_leave_working_days_in_month_strict(emp, month_start)
    unpaid_amt = (per_day * ul_days).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    half_amt, _ = half_pay_leave_deduction(emp, month_start, per_day)
    tier_amt, _ = tiered_sick_leave_deduction(emp, month_start, per_day)

    iloe_amt = Decimal('0')
    if entity == 'uae' and (uc is None or uc.iloe_applicable) and settings.iloe_deduct_via_payroll:
        iloe_total, _ = compute_iloe_deduction(basic_salary)
        iloe_amt = iloe_total

    gosi_amt = Decimal('0')
    loc_prev = (getattr(emp, 'location', None) or '').strip().lower()
    if loc_prev == 'ksa' and kc is not None and kc.gosi_applicable:
        emp_pct = Decimal('0.10') if kc.nationality == 'saudi' else Decimal('0')
        gosi_amt = (basic_salary * emp_pct).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    advance_amt = Decimal('0')
    for adv in EmployeeAdvance.objects.filter(
        employee=emp,
        status=EmployeeAdvance.STATUS_ACTIVE,
        amount_remaining__gt=0,
    ).order_by('pk'):
        rem = adv.amount_remaining
        d = adv.monthly_deduction
        if d > rem:
            d = rem
        advance_amt += d

    manual = (manual_misc or Decimal('0')).quantize(Decimal('0.01'))
    total = (
        absent_amt
        + late_amt
        + unpaid_amt
        + half_amt
        + tier_amt
        + iloe_amt
        + gosi_amt
        + advance_amt
        + manual
    ).quantize(Decimal('0.01'))
    est_net = (basic_salary + allowances_total - total).quantize(Decimal('0.01'))

    return {
        'absent': absent_amt,
        'late': late_amt,
        'unpaid_leave': unpaid_amt,
        'half_pay_leave': half_amt,
        'sick_tiered': tier_amt,
        'iloe': iloe_amt,
        'gosi_employee': gosi_amt,
        'advance': advance_amt,
        'manual': manual,
        'total': total,
        'estimated_net': est_net,
        'attendance_finalized': finalized,
    }

