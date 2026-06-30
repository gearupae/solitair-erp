"""Shared financial helpers for project portfolio reports."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum

from apps.projects.models import Project, ProjectItemDelivery, ProjectItemReturn
from apps.projects.project_spend import project_proposed_budget_ex_vat
from apps.sales.models import Invoice

COMPLETED_STATUSES = ('completed', 'completed_payment_pending')

STATUS_LABELS = {
    'completed': 'Completed',
    'completed_payment_pending': 'Completed Payment Pending',
    'ongoing': 'Ongoing',
    'ongoing_payment_received': 'Ongoing Payment Received',
    'planning': 'Planning',
    'on_hold': 'On Hold',
    'draft': 'Draft',
    'cancelled': 'Cancelled',
}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def project_status_label(project: Project) -> str:
    return STATUS_LABELS.get(project.status, project.get_status_display())


def is_project_completed(project: Project) -> bool:
    return project.status in COMPLETED_STATUSES


def project_contract_value(project: Project) -> Decimal:
    """Customer project value (V / P) — contract value, else estimate net excl. VAT."""
    value = project.contract_value or Decimal('0.00')
    if value > 0:
        return value
    return project.estimated_cost or Decimal('0.00')


def customer_project_label(project: Project, estimate=None) -> str:
    """Customer name with project / quotation title."""
    if estimate is None:
        from apps.projects.member_roles import get_project_source_estimate

        estimate = get_project_source_estimate(project)

    customer_name = project.customer.name if project.customer_id else '—'
    title = (project.name or '').strip()
    if not title and estimate:
        title = (estimate.subject or estimate.display_estimate_number or '').strip()
    if title and title != customer_name:
        return f'{customer_name} — {title}'
    return customer_name


def salesman_label(project: Project) -> str:
    from apps.projects.member_roles import resolve_salesman_user, user_role_label

    user = resolve_salesman_user(project)
    return user_role_label(user) if user else '—'


def project_estimated_expense(project: Project, estimate=None) -> Decimal:
    return project_proposed_budget_ex_vat(project, source_estimate=estimate)


def _date_filter(qs, *, date_field: str, as_of_date: date | None, start_date: date | None):
    if as_of_date:
        qs = qs.filter(**{f'{date_field}__lte': as_of_date})
    if start_date:
        qs = qs.filter(**{f'{date_field}__gte': start_date})
    return qs


def project_expense_spend(
    project: Project,
    *,
    as_of_date: date | None = None,
    start_date: date | None = None,
) -> Decimal:
    """Manual project expenses + vendor bill subtotals (excl. VAT)."""
    manual_qs = project.project_expenses.filter(is_active=True).exclude(status='rejected').exclude(
        vendor_bill__isnull=False
    )
    manual_qs = _date_filter(manual_qs, date_field='expense_date', as_of_date=as_of_date, start_date=start_date)
    manual = manual_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    bills_qs = project.vendor_bills.filter(is_active=True).exclude(status='cancelled')
    bills_qs = _date_filter(bills_qs, date_field='bill_date', as_of_date=as_of_date, start_date=start_date)
    bills = bills_qs.aggregate(s=Sum('subtotal'))['s'] or Decimal('0.00')
    return _quantize(manual + bills)


def project_material_spend(
    project: Project,
    *,
    as_of_date: date | None = None,
    start_date: date | None = None,
) -> Decimal:
    """Inventory / materials spend from deliveries minus returns (excl. VAT unit cost)."""
    if not as_of_date and not start_date:
        from apps.projects.item_delivery import project_inventory_spend_total

        return project_inventory_spend_total(project)

    from apps.inventory.models import ItemSerialNumber
    from apps.projects.item_delivery import _project_item_budget_unit_cost

    total = Decimal('0.00')

    delivery_qs = ProjectItemDelivery.objects.filter(project=project).select_related('item')
    delivery_qs = _date_filter(delivery_qs, date_field='delivered_date', as_of_date=as_of_date, start_date=start_date)
    for delivery in delivery_qs:
        if not delivery.item_id or delivery.item.track_by_serial:
            continue
        unit = _project_item_budget_unit_cost(project, delivery.item)
        total += (delivery.quantity or Decimal('0')) * unit

    return_qs = ProjectItemReturn.objects.filter(project=project, serial_number__isnull=True).select_related('item')
    return_qs = _date_filter(return_qs, date_field='returned_date', as_of_date=as_of_date, start_date=start_date)
    for ret in return_qs:
        if not ret.item_id:
            continue
        unit = _project_item_budget_unit_cost(project, ret.item)
        total -= (ret.quantity or Decimal('0')) * unit

    serial_qs = ItemSerialNumber.objects.filter(
        assigned_project=project,
        status=ItemSerialNumber.STATUS_DELIVERED,
        is_active=True,
    ).select_related('item', 'warehouse')
    serial_qs = _date_filter(serial_qs, date_field='delivered_date', as_of_date=as_of_date, start_date=start_date)

    returned_serial_ids = set()
    serial_return_qs = ProjectItemReturn.objects.filter(project=project, serial_number__isnull=False)
    serial_return_qs = _date_filter(
        serial_return_qs, date_field='returned_date', as_of_date=as_of_date, start_date=None
    )
    returned_serial_ids = set(serial_return_qs.values_list('serial_number_id', flat=True))

    for sn in serial_qs:
        if sn.pk in returned_serial_ids:
            continue
        total += _project_item_budget_unit_cost(project, sn.item, warehouse=sn.warehouse)

    return _quantize(max(total, Decimal('0.00')))


def project_labour_spend(
    project: Project,
    *,
    as_of_date: date | None = None,
    start_date: date | None = None,
) -> Decimal:
    from apps.hr.models import Employee
    from apps.projects.labour_utils import (
        implied_hourly_rate_from_basic,
        labour_attendance_queryset,
        sum_labour_hours,
    )

    total = Decimal('0.00')
    for user in project.technicians.filter(is_active=True):
        emp = Employee.objects.filter(user=user, is_active=True).only('basic_salary').first()
        if not emp:
            continue
        attendance = labour_attendance_queryset(emp, project)
        attendance = _date_filter(attendance, date_field='date', as_of_date=as_of_date, start_date=start_date)
        hours = sum_labour_hours(attendance)
        rate = implied_hourly_rate_from_basic(emp.basic_salary or Decimal('0'))
        total += hours * rate
    return _quantize(total)


def project_spend_breakdown(
    project: Project,
    *,
    as_of_date: date | None = None,
    start_date: date | None = None,
) -> dict:
    """Return material, expense, labour and total actual spend (excl. VAT)."""
    material = project_material_spend(project, as_of_date=as_of_date, start_date=start_date)
    labour = project_labour_spend(project, as_of_date=as_of_date, start_date=start_date)
    expense = project_expense_spend(project, as_of_date=as_of_date, start_date=start_date)
    actual = _quantize(material + expense + labour)
    return {
        'material': material,
        'expense': expense,
        'labour': labour,
        'actual_expense': actual,
        'total_actual_expense': actual,
    }


def project_payment_collected(
    project: Project,
    *,
    as_of_date: date | None = None,
) -> Decimal:
    """Sum of paid amounts on invoices linked to the project."""
    qs = Invoice.objects.filter(
        Q(project=project) | Q(project_links__project=project),
        is_active=True,
    ).exclude(status__in=('draft', 'cancelled')).distinct()
    if as_of_date:
        qs = qs.filter(invoice_date__lte=as_of_date)
    total = qs.aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')
    return _quantize(total)


def iter_month_end_dates(start_date: date, end_date: date):
    """Yield month-end dates from start_date through end_date (inclusive)."""
    cursor = start_date.replace(day=1)
    while cursor <= end_date:
        last_day = monthrange(cursor.year, cursor.month)[1]
        month_end = cursor.replace(day=last_day)
        if month_end >= start_date:
            yield min(month_end, end_date)
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)


def sum_row_totals(rows: list[dict], keys: list[str]) -> dict:
    totals = {key: Decimal('0.00') for key in keys}
    for row in rows:
        for key in keys:
            totals[key] += row.get(key) or Decimal('0.00')
    return {key: _quantize(value) for key, value in totals.items()}


PROJECT_LIST_SORT_FIELDS = {
    'total_actual': 'total_actual_expense',
    'total_estimated': 'total_estimated_value',
    'actual_project_value': 'actual_project_value',
    'project_actual_value': 'project_actual_value',
    'profit_aed': 'profit_aed',
    'profit_pct': 'profit_pct',
    'project_completion_pct': 'project_completion_pct',
}


def build_project_financial_snapshot(
    project: Project,
    *,
    as_of_date: date | None = None,
    estimate=None,
) -> dict:
    """
    Single snapshot for project list, detail-aligned expense totals, and both portfolio reports.
    """
    from apps.projects.member_roles import get_project_source_estimate
    from apps.reports.project_report_actual_invoice import _build_row as build_invoice_row
    from apps.reports.project_report_actual_value import _build_row as build_value_row

    as_of = as_of_date or date.today()
    if estimate is None:
        estimate = get_project_source_estimate(project)

    total_estimated = project_estimated_expense(project, estimate)
    total_actual = project_spend_breakdown(project, as_of_date=as_of)['total_actual_expense']

    invoice = build_invoice_row(project, end_date=as_of, estimate=estimate)
    value = build_value_row(project, row_date=as_of, estimate=estimate)

    profit_aed = _quantize(total_estimated - total_actual)
    if total_estimated > 0:
        profit_pct = _quantize_pct(profit_aed / total_estimated * Decimal('100'))
    else:
        profit_pct = Decimal('0.0')

    return {
        'total_actual_expense': total_actual,
        'total_estimated_value': total_estimated,
        'actual_project_value': value['actual_project_value'],
        'project_actual_value': invoice['invoice_value'],
        'profit_aed': profit_aed,
        'profit_pct': profit_pct,
        'project_completion_pct': value['work_completion_pct'],
    }


def attach_project_list_financials(projects, *, as_of_date: date | None = None):
    """Attach list_financials dict to each project using build_project_financial_snapshot."""
    as_of = as_of_date or date.today()
    for project in projects:
        project.list_financials = build_project_financial_snapshot(project, as_of_date=as_of)
    return projects
