"""Employee sales commission calculations for payroll."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from apps.hr.models_extended import EmployeeHRProfile
from apps.reports.sales_report import INVOICE_REVENUE_STATUSES


def month_first(d: date) -> date:
    return date(d.year, d.month, 1)


def employee_month_sales_queryset(employee, month: date):
    """Posted invoices in month linked via estimate owner or customer assigned salesman."""
    from apps.sales.models import Invoice

    if not employee or not employee.pk:
        return Invoice.objects.none()

    month = month_first(month)
    link_q = Q(customer__assigned_salesperson_id=employee.pk)
    if employee.user_id:
        link_q |= Q(estimate__assigned_to_id=employee.user_id)

    return (
        Invoice.objects.filter(
            is_active=True,
            status__in=INVOICE_REVENUE_STATUSES,
            invoice_date__year=month.year,
            invoice_date__month=month.month,
        )
        .filter(link_q)
        .distinct()
    )


def total_sales_for_employee_month(employee, month: date) -> Decimal:
    qs = employee_month_sales_queryset(employee, month)
    total = qs.aggregate(
        t=Coalesce(Sum('subtotal'), Decimal('0.00')),
    )['t'] or Decimal('0.00')
    return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def commission_amount_for_employee(employee, total_sales: Decimal) -> Decimal:
    profile = EmployeeHRProfile.objects.filter(employee=employee).first()
    if not profile or not profile.commission_type:
        return Decimal('0.00')

    sales = (total_sales or Decimal('0')).quantize(Decimal('0.01'))
    if profile.commission_type == EmployeeHRProfile.COMMISSION_TYPE_PERCENTAGE:
        rate = profile.commission_percentage or Decimal('0')
        if rate <= 0 or sales <= 0:
            return Decimal('0.00')
        return (sales * rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if profile.commission_type == EmployeeHRProfile.COMMISSION_TYPE_FIXED:
        fixed = profile.commission_fixed_amount or Decimal('0')
        if fixed <= 0:
            return Decimal('0.00')
        return fixed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return Decimal('0.00')


def commission_profile_summary(employee) -> dict:
    profile = EmployeeHRProfile.objects.filter(employee=employee).first()
    if not profile or not profile.commission_type:
        return {
            'configured': False,
            'commission_type': '',
            'commission_type_label': 'Not configured',
            'commission_rate_label': '',
        }

    if profile.commission_type == EmployeeHRProfile.COMMISSION_TYPE_PERCENTAGE:
        rate = profile.commission_percentage or Decimal('0')
        return {
            'configured': True,
            'commission_type': profile.commission_type,
            'commission_type_label': profile.get_commission_type_display(),
            'commission_rate_label': f'{rate}% of sales',
        }

    fixed = profile.commission_fixed_amount or Decimal('0')
    return {
        'configured': True,
        'commission_type': profile.commission_type,
        'commission_type_label': profile.get_commission_type_display(),
        'commission_rate_label': f'AED {fixed} fixed',
    }


def build_commission_preview(employee, month: date) -> dict:
    total_sales = total_sales_for_employee_month(employee, month)
    commission_amount = commission_amount_for_employee(employee, total_sales)
    profile = commission_profile_summary(employee)
    invoice_count = employee_month_sales_queryset(employee, month).count()
    return {
        'total_sales': total_sales,
        'commission_amount': commission_amount,
        'invoice_count': invoice_count,
        **profile,
    }
