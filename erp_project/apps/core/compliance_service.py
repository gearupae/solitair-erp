"""Auto compliance evaluation, dashboard alerts, and in-app notifications."""
from __future__ import annotations

from django.urls import reverse

from apps.core.notification_utils import notify_user
from apps.core.utils import PermissionChecker
from apps.settings_app.models import Notification

MAX_RECORDS_PER_MODULE = 40


def _alert(
    *,
    module: str,
    module_label: str,
    record_label: str,
    link: str,
    title: str,
    detail: str,
    severity: str = 'red',
) -> dict:
    return {
        'module': module,
        'module_label': module_label,
        'record_label': record_label,
        'link': link,
        'title': title,
        'detail': detail,
        'severity': severity,
    }


def alerts_from_evaluation(
    *,
    module: str,
    module_label: str,
    record_label: str,
    link: str,
    evaluation: dict | None,
) -> list[dict]:
    if not evaluation:
        return []
    out = []
    for flag in evaluation.get('flags') or []:
        if str(flag.get('severity', '')).lower() != 'red':
            continue
        out.append(
            _alert(
                module=module,
                module_label=module_label,
                record_label=record_label,
                link=link,
                title=str(flag.get('title') or 'Compliance issue'),
                detail=str(flag.get('detail') or ''),
            )
        )
    return out


def alerts_from_pr_analysis(*, pr, analysis: dict | None) -> list[dict]:
    if not analysis or not analysis.get('ok'):
        return []
    link = reverse('purchase:pr_detail', args=[pr.pk])
    record_label = pr.pr_number
    out = []
    review = analysis.get('compliance_review') or {}
    risk = str(review.get('overall_risk') or '').lower()
    if risk == 'high':
        out.append(
            _alert(
                module='purchase_request',
                module_label='Purchase request',
                record_label=record_label,
                link=link,
                title='High compliance risk in vendor quotes',
                detail='Review terms and compliance issues on attached vendor quotations.',
            )
        )
    for issue in review.get('issues') or []:
        sev = str(issue.get('severity') or '').lower()
        if sev not in ('high', 'medium'):
            continue
        if sev != 'high':
            continue
        out.append(
            _alert(
                module='purchase_request',
                module_label='Purchase request',
                record_label=record_label,
                link=link,
                title=str(issue.get('topic') or 'Quote compliance issue'),
                detail=str(issue.get('detail') or ''),
            )
        )
    return out


def sync_compliance_notifications(user, alerts: list[dict]) -> None:
    """Create unread notifications for red compliance alerts (deduped per record)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return
    grouped: dict[str, list[dict]] = {}
    for row in alerts:
        if row.get('severity') != 'red':
            continue
        grouped.setdefault(row['link'], []).append(row)

    for link, items in grouped.items():
        first = items[0]
        title = f"Compliance: {first['module_label']} {first['record_label']}"
        parts = [f"{item['title']}" for item in items[:4]]
        if len(items) > 4:
            parts.append(f"+{len(items) - 4} more")
        message = '; '.join(parts)
        if any(item.get('detail') for item in items):
            message += f" — {items[0].get('detail', '')[:200]}"
        exists = Notification.objects.filter(
            user=user,
            is_read=False,
            link=link,
            title=title,
        ).exists()
        if not exists:
            notify_user(user, title, message, link)


def run_estimate_compliance(estimate, *, full_run: bool = True) -> dict:
    from apps.sales.estimate_evaluate_ai import (
        build_estimate_snapshot,
        evaluate_estimate,
        get_cached_estimate_evaluation,
        _heuristic_evaluation,
    )

    if full_run:
        return evaluate_estimate(estimate)
    cached = get_cached_estimate_evaluation(estimate)
    if cached:
        return cached
    return _heuristic_evaluation(build_estimate_snapshot(estimate))


def run_po_compliance(po, *, full_run: bool = True) -> dict:
    from apps.purchase.po_evaluate_ai import (
        build_po_snapshot,
        evaluate_purchase_order,
        get_cached_po_evaluation,
        _heuristic_evaluation,
    )

    if full_run:
        return evaluate_purchase_order(po)
    cached = get_cached_po_evaluation(po)
    if cached:
        return cached
    return _heuristic_evaluation(build_po_snapshot(po))


def run_project_compliance(project, *, full_run: bool = True, recorded_expenses=None, budget_pct_used=None) -> dict:
    from apps.projects.project_evaluate_ai import (
        build_project_snapshot,
        evaluate_project,
        get_cached_project_evaluation,
        _heuristic_evaluation,
    )

    if full_run:
        return evaluate_project(
            project,
            recorded_expenses=recorded_expenses,
            budget_pct_used=budget_pct_used,
        )
    cached = get_cached_project_evaluation(
        project,
        recorded_expenses=recorded_expenses,
        budget_pct_used=budget_pct_used,
    )
    if cached:
        return cached
    return _heuristic_evaluation(
        build_project_snapshot(
            project,
            recorded_expenses=recorded_expenses,
            budget_pct_used=budget_pct_used,
        )
    )


def run_employee_compliance(employee, *, full_run: bool = True) -> dict:
    from apps.hr.employee_evaluate_ai import (
        build_employee_snapshot,
        evaluate_employee,
        get_cached_employee_evaluation,
        _heuristic_evaluation,
    )

    if full_run:
        return evaluate_employee(employee)
    cached = get_cached_employee_evaluation(employee)
    if cached:
        return cached
    return _heuristic_evaluation(build_employee_snapshot(employee))


def _project_expense_context(project):
    from decimal import Decimal

    from django.db.models import Count, Sum

    from apps.projects.item_delivery import project_inventory_spend_total

    pe = project.project_expenses.filter(is_active=True).exclude(status='rejected').exclude(
        vendor_bill__isnull=False
    )
    manual_total = pe.aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')
    bills_total = (
        project.vendor_bills.filter(is_active=True).exclude(status='cancelled')
        .aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')
    )
    inventory_spend = project_inventory_spend_total(project)
    recorded = manual_total + bills_total + inventory_spend
    budget_pct_used = None
    if project.budget and project.budget > 0:
        budget_pct_used = (recorded / project.budget * Decimal('100')).quantize(Decimal('0.1'))
    return recorded, budget_pct_used


def auto_compliance_on_detail(user, module: str, evaluation: dict, *, record_label: str, link: str) -> dict:
    """Notify current user when red flags are found on a detail page they opened."""
    alerts = alerts_from_evaluation(
        module=module,
        module_label=_module_label(module),
        record_label=record_label,
        link=link,
        evaluation=evaluation,
    )
    sync_compliance_notifications(user, alerts)
    return evaluation


def auto_pr_compliance_on_detail(user, pr, analysis: dict) -> dict:
    alerts = alerts_from_pr_analysis(pr=pr, analysis=analysis)
    sync_compliance_notifications(user, alerts)
    return analysis


def _module_label(module: str) -> str:
    return {
        'estimate': 'Quotation',
        'purchase_order': 'Purchase order',
        'purchase_request': 'Purchase request',
        'project': 'Project',
        'employee': 'Employee',
    }.get(module, module.replace('_', ' ').title())


def get_compliance_dashboard_alerts(user) -> list[dict]:
    """Red compliance flags across modules the user can access (cached or heuristic)."""
    alerts: list[dict] = []

    if user.is_superuser or PermissionChecker.has_permission(user, 'sales', 'view'):
        from apps.core.visibility import filter_estimates_for_user
        from apps.sales.models import Estimate

        qs = filter_estimates_for_user(
            Estimate.objects.filter(is_active=True).exclude(status='cancelled').order_by('-updated_at'),
            user,
        )[:MAX_RECORDS_PER_MODULE]
        for est in qs:
            ev = run_estimate_compliance(est, full_run=False)
            link = reverse('sales:estimate_detail', args=[est.pk])
            alerts.extend(
                alerts_from_evaluation(
                    module='estimate',
                    module_label='Quotation',
                    record_label=est.display_estimate_number,
                    link=link,
                    evaluation=ev,
                )
            )

    if user.is_superuser or PermissionChecker.has_permission(user, 'purchase', 'view'):
        from django.db.models import Count

        from apps.core.visibility import filter_purchase_orders_for_user, filter_purchase_requests_for_user
        from apps.purchase.models import PurchaseOrder, PurchaseRequest

        po_qs = filter_purchase_orders_for_user(
            PurchaseOrder.objects.filter(is_active=True).exclude(status='cancelled').order_by('-updated_at'),
            user,
        )[:MAX_RECORDS_PER_MODULE]
        for po in po_qs:
            ev = run_po_compliance(po, full_run=False)
            link = reverse('purchase:po_detail', args=[po.pk])
            alerts.extend(
                alerts_from_evaluation(
                    module='purchase_order',
                    module_label='Purchase order',
                    record_label=po.po_number,
                    link=link,
                    evaluation=ev,
                )
            )

        pr_qs = filter_purchase_requests_for_user(
            PurchaseRequest.objects.filter(is_active=True)
            .exclude(status='cancelled')
            .annotate(_att_count=Count('attachments'))
            .filter(_att_count__gt=0)
            .order_by('-updated_at'),
            user,
        )[:MAX_RECORDS_PER_MODULE]
        from apps.purchase.services.vendor_quote_ai import get_cached_pr_quote_analysis

        for pr in pr_qs:
            analysis = get_cached_pr_quote_analysis(pr)
            alerts.extend(alerts_from_pr_analysis(pr=pr, analysis=analysis))

    if user.is_superuser or PermissionChecker.has_permission(user, 'projects', 'view'):
        from apps.core.visibility import filter_projects_for_user
        from apps.projects.models import Project

        qs = filter_projects_for_user(
            Project.objects.filter(is_active=True).exclude(status='cancelled').order_by('-updated_at'),
            user,
        )[:MAX_RECORDS_PER_MODULE]
        for project in qs:
            recorded, budget_pct = _project_expense_context(project)
            ev = run_project_compliance(
                project,
                full_run=False,
                recorded_expenses=recorded,
                budget_pct_used=budget_pct,
            )
            link = reverse('projects:project_detail', args=[project.pk])
            alerts.extend(
                alerts_from_evaluation(
                    module='project',
                    module_label='Project',
                    record_label=project.project_code,
                    link=link,
                    evaluation=ev,
                )
            )

    if user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'view'):
        from apps.hr.models import Employee

        qs = Employee.objects.filter(is_active=True).order_by('-updated_at')[:MAX_RECORDS_PER_MODULE]
        for emp in qs:
            ev = run_employee_compliance(emp, full_run=False)
            link = reverse('hr:employee_detail', args=[emp.pk])
            alerts.extend(
                alerts_from_evaluation(
                    module='employee',
                    module_label='Employee',
                    record_label=emp.employee_code,
                    link=link,
                    evaluation=ev,
                )
            )

    alerts.sort(key=lambda row: (row['module_label'], row['record_label'], row['title']))
    return alerts
