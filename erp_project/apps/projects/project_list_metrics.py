"""Summary metrics for the projects list page."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Q


ACTIVE_PROJECT_STATUSES = (
    'planning',
    'ongoing',
    'on_hold',
    'completed_payment_pending',
    'ongoing_payment_received',
)


def build_project_list_metrics(projects_qs):
    """
    Metrics scoped to the same visibility as the list (not search/status filters):
    - Active projects count
    - Average profit margin %: (estimate excl. VAT − actual spend excl. VAT) / estimate
    - Average task completion %
    """
    from .project_spend import project_actual_spend_ex_vat

    projects = list(
        projects_qs.annotate(
            task_total_count=Count('tasks', filter=Q(tasks__is_active=True)),
            task_done_count=Count(
                'tasks',
                filter=Q(tasks__is_active=True, tasks__status='completed'),
            ),
        ).only('pk', 'estimated_cost', 'status')
    )
    if not projects:
        return {
            'metric_active_projects': 0,
            'metric_avg_profit_margin': None,
            'metric_avg_completion': Decimal('0.0'),
        }

    active_count = 0
    completion_total = Decimal('0.00')
    margin_values = []

    for project in projects:
        if project.status in ACTIVE_PROJECT_STATUSES:
            active_count += 1

        if project.task_total_count:
            completion_total += (
                Decimal(project.task_done_count) / Decimal(project.task_total_count) * Decimal('100')
            )

        est = project.estimated_cost or Decimal('0.00')
        if est <= 0:
            continue

        recorded = project_actual_spend_ex_vat(project)['recorded_expenses_total']
        margin_values.append((est - recorded) / est * Decimal('100'))

    avg_completion = (completion_total / len(projects)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    avg_margin = None
    if margin_values:
        avg_margin = (sum(margin_values) / len(margin_values)).quantize(
            Decimal('0.1'), rounding=ROUND_HALF_UP
        )

    return {
        'metric_active_projects': active_count,
        'metric_avg_profit_margin': avg_margin,
        'metric_avg_completion': avg_completion,
    }
