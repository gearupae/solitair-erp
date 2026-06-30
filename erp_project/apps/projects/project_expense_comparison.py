"""Estimated (quotation) vs actual project expense breakdown for project detail."""
from __future__ import annotations

from decimal import Decimal


def build_project_expense_comparison_context(
    *,
    project,
    source_estimate,
    manual_expenses_total: Decimal,
    bills_total: Decimal,
    inventory_spend: Decimal,
    labour_cost: Decimal,
):
    """
    Estimated: expense-type totals from the linked quotation (excl. VAT).
    Actual: labour timesheets, items delivered value, project expenses, vendor bills.
    """
    estimated_rows = []
    estimated_grand = Decimal('0.00')
    if source_estimate:
        from apps.sales.estimate_pdf_groups import build_expense_type_totals_for_estimate

        for row in build_expense_type_totals_for_estimate(source_estimate):
            amount = row.get('line_subtotal') or Decimal('0.00')
            estimated_rows.append({
                'label': row['expense_type_name'],
                'amount': amount,
            })
        if estimated_rows:
            estimated_grand = sum((r['amount'] for r in estimated_rows), Decimal('0.00'))

    actual_rows = [
        {'label': 'Labour (timesheets)', 'amount': labour_cost or Decimal('0.00')},
        {'label': 'Items delivered (unit cost, excl. VAT)', 'amount': inventory_spend or Decimal('0.00')},
        {'label': 'Project expenses (excl. VAT)', 'amount': manual_expenses_total or Decimal('0.00')},
        {'label': 'Vendor bills (excl. VAT)', 'amount': bills_total or Decimal('0.00')},
    ]
    actual_grand = sum((r['amount'] for r in actual_rows), Decimal('0.00'))

    return {
        'estimated_expense_rows': estimated_rows,
        'estimated_expense_grand_total': estimated_grand,
        'actual_expense_rows': actual_rows,
        'actual_expense_grand_total': actual_grand,
        'show_expense_comparison_card': bool(source_estimate or actual_grand > 0),
    }
