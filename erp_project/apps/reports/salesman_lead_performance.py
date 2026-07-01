"""Salesman lead performance report."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.crm.models import Customer
from apps.crm.utils import (
    filter_customers_for_user,
    get_sales_employee_queryset,
    salesperson_display_name,
)
from apps.sales.models import Estimate
from apps.settings_app.models import AuditLog

ZERO = Decimal('0.00')


def _converted_in_period(lead_ids, start_date, end_date) -> set[int]:
    converted: set[int] = set()
    logs = AuditLog.objects.filter(
        model='Customer',
        record_id__in=[str(i) for i in lead_ids],
        timestamp__date__gte=start_date,
        timestamp__date__lte=end_date,
    ).filter(
        Q(changes__action='converted_to_customer')
        | Q(changes__converted_to_customer=True)
        | Q(changes__action='kanban_won')
    )
    for log in logs.values_list('record_id', flat=True):
        try:
            converted.add(int(log))
        except (TypeError, ValueError):
            pass
    return converted


def build_salesman_lead_performance_report(
    *,
    start_date,
    end_date,
    salesperson_id='',
    user=None,
):
    """Per-salesperson lead metrics for leads created in the date range."""
    base = Customer.objects.filter(
        is_active=True,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )
    if user:
        base = filter_customers_for_user(base, user)

    latest_estimate_subq = (
        Estimate.objects.filter(customer=OuterRef('pk'), is_active=True)
        .order_by('-date', '-id')
        .values('total_amount')[:1]
    )

    lost_ids = set(
        Customer.objects.filter(
            is_active=True,
            customer_type='lead',
            lead_kanban_stage__slug__icontains='lost',
        ).values_list('pk', flat=True)
    )

    employees = get_sales_employee_queryset()
    if salesperson_id == 'none':
        employees = employees.none()
        target_ids = [None]
    elif salesperson_id:
        try:
            employees = employees.filter(pk=int(salesperson_id))
        except (TypeError, ValueError):
            employees = employees.none()
        target_ids = list(employees.values_list('pk', flat=True)) or []
    else:
        target_ids = list(employees.values_list('pk', flat=True))
        if base.filter(assigned_salesperson__isnull=True).exists():
            target_ids.append(None)

    rows = []
    for emp_id in target_ids:
        if emp_id is None:
            bucket = base.filter(assigned_salesperson__isnull=True)
            label = 'Unassigned'
        else:
            emp = employees.filter(pk=emp_id).first()
            if not emp and salesperson_id:
                continue
            bucket = base.filter(assigned_salesperson_id=emp_id)
            label = salesperson_display_name(emp) if emp else f'Employee #{emp_id}'

        lead_ids = list(bucket.values_list('pk', flat=True))
        leads_created = len(lead_ids)
        if not leads_created and salesperson_id and emp_id is not None:
            continue

        open_leads = bucket.filter(customer_type='lead').exclude(pk__in=lost_ids)
        open_count = open_leads.count()

        won_from_type = bucket.filter(customer_type='customer').count()
        converted_ids = _converted_in_period(lead_ids, start_date, end_date)
        won_count = max(won_from_type, len(converted_ids))

        lost_count = bucket.filter(customer_type='lead', pk__in=lost_ids).count()

        open_with_value = open_leads.annotate(
            latest_estimate_value=Subquery(latest_estimate_subq),
        )
        pipeline_value = (
            open_with_value.aggregate(
                total=Coalesce(Sum('latest_estimate_value'), ZERO),
            )['total']
            or ZERO
        )

        conversion_rate = round(won_count / leads_created * 100, 1) if leads_created else 0.0

        rows.append({
            'salesperson_id': emp_id,
            'salesperson_name': label,
            'leads_created': leads_created,
            'open_leads': open_count,
            'won': won_count,
            'lost': lost_count,
            'pipeline_value': pipeline_value,
            'conversion_rate': conversion_rate,
        })

    rows.sort(key=lambda r: (-r['leads_created'], r['salesperson_name']))

    salespeople = [
        {'id': emp.pk, 'label': salesperson_display_name(emp)}
        for emp in get_sales_employee_queryset()
    ]

    return {
        'start_date': start_date,
        'end_date': end_date,
        'filter_salesperson': salesperson_id,
        'filter_salespeople': salespeople,
        'performance_rows': rows,
        'single_salesperson': bool(salesperson_id and salesperson_id != 'none'),
    }
