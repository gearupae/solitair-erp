"""Report 2 — Actual Project Value Report."""
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
    iter_month_end_dates,
    project_contract_value,
    project_estimated_expense,
    project_payment_collected,
    project_spend_breakdown,
    project_status_label,
    salesman_label,
    sum_row_totals,
    _quantize,
    _quantize_pct,
)


def _work_completion_pct(*, actual_expense: Decimal, estimated_expense: Decimal, completed: bool) -> Decimal:
    if completed:
        return Decimal('100.0')
    if estimated_expense > 0:
        pct = actual_expense / estimated_expense * Decimal('100')
        return _quantize_pct(min(pct, Decimal('100.0')))
    return Decimal('0.0')


def _build_row(project: Project, *, row_date, estimate=None) -> dict:
    if estimate is None:
        estimate = get_project_source_estimate(project)

    spend = project_spend_breakdown(project, as_of_date=row_date)
    total_actual = spend['total_actual_expense']
    total_estimated = project_estimated_expense(project, estimate)
    project_value = project_contract_value(project)
    payment_collected = project_payment_collected(project, as_of_date=row_date)
    completed = is_project_completed(project)

    work_completion = _work_completion_pct(
        actual_expense=total_actual,
        estimated_expense=total_estimated,
        completed=completed,
    )
    work_ratio = work_completion / Decimal('100')
    actual_project_completion = _quantize(project_value * work_ratio)
    actual_project_value = _quantize(actual_project_completion - payment_collected)
    profit = _quantize(payment_collected - total_actual)
    outstanding = _quantize(project_value - payment_collected)

    return {
        'project_code': project.project_code,
        'row_date': row_date,
        'customer_label': customer_project_label(project, estimate),
        'salesman_label': salesman_label(project),
        'project_value': project_value,
        'total_actual_expense': total_actual,
        'total_estimated_expense': total_estimated,
        'payment_collected': payment_collected,
        'project_outstanding': outstanding,
        'work_completion_pct': work_completion,
        'actual_project_completion': actual_project_completion,
        'actual_project_value': actual_project_value,
        'profit': profit,
        'status': project_status_label(project),
        'project_pk': project.pk,
    }


def build_project_actual_value_report(*, start_date, end_date, status='', monthly=False):
    qs = (
        projects_in_period(start_date, end_date)
        .select_related('customer')
        .prefetch_related(
            Prefetch(
                'estimates',
                queryset=Estimate.objects.filter(is_active=True).select_related(
                    'assigned_to', 'assigned_to__employee_profile', 'customer'
                ),
            ),
            'members__employee_profile__designation',
        )
        .order_by('project_code', 'pk')
    )
    if status:
        qs = qs.filter(status=status)

    projects = list(qs)
    snapshot_dates = list(iter_month_end_dates(start_date, end_date)) if monthly else [end_date]

    rows = []
    for project in projects:
        estimate = get_project_source_estimate(project)
        for row_date in snapshot_dates:
            rows.append(_build_row(project, row_date=row_date, estimate=estimate))

    footer_keys = [
        'project_value',
        'total_actual_expense',
        'total_estimated_expense',
        'payment_collected',
        'project_outstanding',
        'actual_project_completion',
        'actual_project_value',
        'profit',
    ]
    return {
        'start_date': start_date,
        'end_date': end_date,
        'status_filter': status,
        'status_choices': Project.STATUS_CHOICES,
        'monthly': monthly,
        'rows': rows,
        'totals': sum_row_totals(rows, footer_keys),
        'row_count': len(rows),
    }
