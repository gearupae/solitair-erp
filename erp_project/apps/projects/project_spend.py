"""Project actual and proposed spend totals (excl. VAT) for detail views and AI."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum


def project_actual_spend_ex_vat(project, *, labour_cost: Decimal | None = None):
    """
    Sum recorded project spend excluding VAT:
    manual expenses (amount), vendor bills (subtotal), inventory on site, labour.
    """
    from .item_delivery import project_inventory_spend_total

    pe = project.project_expenses.filter(is_active=True).exclude(status='rejected').exclude(
        vendor_bill__isnull=False
    )
    agg = pe.aggregate(s=Sum('amount'), c=Count('id'))
    manual = agg['s'] if agg['s'] is not None else Decimal('0.00')
    has_manual = (agg['c'] or 0) > 0

    vendor_bills = (
        project.vendor_bills.filter(is_active=True).exclude(status='cancelled').select_related('vendor')
    )
    bills = vendor_bills.aggregate(s=Sum('subtotal'))['s'] or Decimal('0.00')
    has_bills = vendor_bills.exists()

    inventory = project_inventory_spend_total(project)

    if labour_cost is None:
        from .labour_utils import project_labour_summary

        _, _, labour_cost = project_labour_summary(project)
    labour = labour_cost or Decimal('0.00')

    total = manual + bills + inventory + labour
    return {
        'manual_expenses_total': manual,
        'has_manual_expenses': has_manual,
        'project_vendor_bills': vendor_bills.order_by('-bill_date'),
        'project_vendor_bills_total': bills,
        'has_vendor_bills': has_bills,
        'inventory_spend_total': inventory,
        'labour_spend_total': labour,
        'recorded_expenses_total': total,
    }


def project_proposed_budget_ex_vat(project, source_estimate=None) -> Decimal:
    """
    Planned project spend from the linked quotation expense buckets (excl. VAT),
    including installation cost lines. Falls back to estimated_cost, then budget.
    """
    if source_estimate is None:
        from .member_roles import get_project_source_estimate

        source_estimate = get_project_source_estimate(project)

    if source_estimate:
        from apps.sales.estimate_pdf_groups import build_expense_type_totals_for_estimate

        rows = build_expense_type_totals_for_estimate(source_estimate)
        if rows:
            return sum((row.get('line_subtotal') or Decimal('0.00') for row in rows), Decimal('0.00'))

    est = project.estimated_cost or Decimal('0.00')
    if est > 0:
        return est
    return project.budget or Decimal('0.00')


def project_budget_pct_used(proposed: Decimal, recorded: Decimal):
    if proposed and proposed > 0:
        return (recorded / proposed * Decimal('100')).quantize(Decimal('0.1'))
    return None
