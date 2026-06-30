"""Report 1 — Project Actual Invoice Report."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Prefetch

from apps.projects.member_roles import get_project_source_estimate
from apps.projects.models import Project
from apps.reports.project_report_period import projects_in_period
from apps.sales.models import Estimate

from .project_report_financial import (
    customer_project_label,
    is_project_completed,
    project_contract_value,
    project_estimated_expense,
    project_spend_breakdown,
    project_status_label,
    sum_row_totals,
    _quantize,
    _quantize_pct,
)


def _build_row(project: Project, *, end_date, estimate=None) -> dict:
    if estimate is None:
        estimate = get_project_source_estimate(project)

    spend = project_spend_breakdown(project, as_of_date=end_date)
    material = spend['material']
    expense = spend['expense']
    labour = spend['labour']
    actual = spend['actual_expense']
    total_actual = actual

    project_value = project_contract_value(project)
    total_estimated = project_estimated_expense(project, estimate)

    if is_project_completed(project):
        total_estimated = total_actual if total_actual > 0 else total_estimated
        status_pct = Decimal('100.0')
        invoice_value = project_value
    elif total_estimated > 0:
        status_pct = _quantize_pct(total_actual / total_estimated * Decimal('100'))
        invoice_value = _quantize(project_value * total_actual / total_estimated)
    else:
        status_pct = Decimal('0.0')
        invoice_value = Decimal('0.00')

    return {
        'project_code': project.project_code,
        'customer_label': customer_project_label(project, estimate),
        'project_value': project_value,
        'material': material,
        'expense': expense,
        'labour': labour,
        'actual_expense': actual,
        'total_actual_expense': total_actual,
        'total_estimated_expense': total_estimated,
        'invoice_value': invoice_value,
        'status_pct': status_pct,
        'status': project_status_label(project),
        'project_pk': project.pk,
    }


def build_project_actual_invoice_report(*, start_date, end_date, status=''):
    qs = (
        projects_in_period(start_date, end_date)
        .select_related('customer')
        .prefetch_related(
            Prefetch(
                'estimates',
                queryset=Estimate.objects.filter(is_active=True).select_related('assigned_to', 'customer'),
            )
        )
        .order_by('project_code', 'pk')
    )
    if status:
        qs = qs.filter(status=status)

    rows = []
    for project in qs:
        estimate = get_project_source_estimate(project)
        rows.append(_build_row(project, end_date=end_date, estimate=estimate))

    footer_keys = [
        'project_value',
        'material',
        'expense',
        'labour',
        'actual_expense',
        'total_actual_expense',
        'total_estimated_expense',
        'invoice_value',
    ]
    return {
        'start_date': start_date,
        'end_date': end_date,
        'status_filter': status,
        'status_choices': Project.STATUS_CHOICES,
        'rows': rows,
        'totals': sum_row_totals(rows, footer_keys),
        'row_count': len(rows),
    }
