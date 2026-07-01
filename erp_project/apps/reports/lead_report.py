"""Lead report aggregations (period-wise)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.crm.models import CrmLeadKanbanStage, Customer
from apps.crm.utils import (
    filter_customers_for_user,
    get_sales_employee_queryset,
    salesperson_display_name,
)
from apps.sales.models import Estimate
from apps.settings_app.models import AuditLog

ZERO = Decimal('0.00')

SOURCE_FILTER_CHOICES = [
    (value, label) for value, label in Customer.LEAD_SOURCE_CHOICES if value
]


def _apply_lead_filters(qs, *, stage='', salesperson='', lead_status='', source=''):
    if lead_status:
        qs = qs.filter(status=lead_status)
    if salesperson == 'none':
        qs = qs.filter(assigned_salesperson__isnull=True)
    elif salesperson:
        try:
            qs = qs.filter(assigned_salesperson_id=int(salesperson))
        except (TypeError, ValueError):
            pass
    if stage == 'unassigned':
        qs = qs.filter(lead_kanban_stage__isnull=True)
    elif stage:
        try:
            qs = qs.filter(lead_kanban_stage_id=int(stage))
        except (TypeError, ValueError):
            pass
    if source == 'none':
        qs = qs.filter(source_of_lead='')
    elif source and source in dict(Customer.LEAD_SOURCE_CHOICES):
        qs = qs.filter(source_of_lead=source)
    return qs


def _latest_estimate_subquery():
    return (
        Estimate.objects.filter(
            customer=OuterRef('pk'),
            is_active=True,
        )
        .order_by('-date', '-id')
        .values('total_amount')[:1]
    )


def _source_rows(leads_with_value) -> list[dict]:
    rows: list[dict] = []
    for value, label in SOURCE_FILTER_CHOICES:
        bucket = leads_with_value.filter(source_of_lead=value)
        count = bucket.count()
        pipeline_value = (
            bucket.aggregate(total=Coalesce(Sum('latest_estimate_value'), ZERO))['total']
            or ZERO
        )
        rows.append({
            'value': value,
            'label': label,
            'slug': value.replace('_', '-'),
            'count': count,
            'pipeline_value': pipeline_value,
        })
    unassigned = leads_with_value.filter(source_of_lead='')
    unassigned_count = unassigned.count()
    unassigned_value = (
        unassigned.aggregate(total=Coalesce(Sum('latest_estimate_value'), ZERO))['total']
        or ZERO
    )
    rows.append({
        'value': '',
        'label': 'Unassigned',
        'slug': 'unassigned',
        'count': unassigned_count,
        'pipeline_value': unassigned_value,
    })
    return rows


def build_lead_report(
    *,
    start_date,
    end_date,
    stage='',
    salesperson='',
    lead_status='',
    source='',
    user=None,
):
    """Period-wise lead metrics with optional filters."""
    leads_created = Customer.objects.filter(
        is_active=True,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )
    if user:
        leads_created = filter_customers_for_user(leads_created, user)

    active_leads = leads_created.filter(customer_type='lead')
    active_leads = _apply_lead_filters(
        active_leads,
        stage=stage,
        salesperson=salesperson,
        lead_status=lead_status,
        source=source,
    )

    latest_estimate_subq = _latest_estimate_subquery()
    leads_with_value = active_leads.annotate(
        latest_estimate_value=Subquery(latest_estimate_subq),
    )
    pipeline_value = (
        leads_with_value.aggregate(
            total=Coalesce(Sum('latest_estimate_value'), ZERO),
        )['total']
        or ZERO
    )

    estimate_value_in_period = (
        Estimate.objects.filter(
            is_active=True,
            customer__in=active_leads,
            date__gte=start_date,
            date__lte=end_date,
        ).aggregate(total=Coalesce(Sum('total_amount'), ZERO))['total']
        or ZERO
    )

    stage_rows = []
    stages = CrmLeadKanbanStage.objects.filter(is_active=True).order_by('sort_order', 'id')
    stage_counts = {
        row['lead_kanban_stage_id']: row['count']
        for row in active_leads.values('lead_kanban_stage_id').annotate(count=Count('id'))
    }
    for st in stages:
        stage_rows.append({
            'id': st.id,
            'name': st.name,
            'slug': st.slug,
            'count': stage_counts.get(st.id, 0),
            'converts_to_customer': st.converts_to_customer,
        })

    unassigned_count = active_leads.filter(lead_kanban_stage__isnull=True).count()
    source_rows = _source_rows(leads_with_value)

    converted_logs = AuditLog.objects.filter(
        model='Customer',
        timestamp__date__gte=start_date,
        timestamp__date__lte=end_date,
    ).filter(
        Q(changes__action='converted_to_customer')
        | Q(changes__converted_to_customer=True)
        | Q(changes__action='kanban_won')
    )
    converted_count = converted_logs.count()

    lead_details = []
    for lead in (
        leads_with_value.select_related(
            'lead_kanban_stage',
            'assigned_salesperson',
            'assigned_salesperson__designation',
        )
        .order_by('-created_at')[:500]
    ):
        lead_details.append({
            'pk': lead.pk,
            'customer_number': lead.customer_number,
            'name': lead.name,
            'company': lead.company,
            'phone': lead.phone,
            'email': lead.email,
            'city': lead.city,
            'job_type': ', '.join(lead.job_type_display_labels) if lead.job_type else '',
            'scope': lead.scope_display_label,
            'status': lead.get_status_display(),
            'status_code': lead.status,
            'created_at': lead.created_at,
            'stage_name': lead.lead_kanban_stage.name if lead.lead_kanban_stage_id else 'Unassigned',
            'stage_slug': lead.lead_kanban_stage.slug if lead.lead_kanban_stage_id else 'unassigned',
            'salesperson_name': salesperson_display_name(lead.assigned_salesperson),
            'source_label': lead.source_of_lead_display_label or '—',
            'latest_estimate_value': lead.latest_estimate_value,
        })

    all_stage_counts = [row['count'] for row in stage_rows] + [unassigned_count]
    stage_max_count = max(all_stage_counts) if any(all_stage_counts) else 1
    all_source_counts = [row['count'] for row in source_rows]
    source_max_count = max(all_source_counts) if any(all_source_counts) else 1

    salespeople = [
        {'id': emp.pk, 'label': salesperson_display_name(emp)}
        for emp in get_sales_employee_queryset()
    ]

    return {
        'start_date': start_date,
        'end_date': end_date,
        'filter_stage': stage,
        'filter_salesperson': salesperson,
        'filter_status': lead_status,
        'filter_source': source,
        'filter_stages': stage_rows,
        'filter_salespeople': salespeople,
        'filter_status_choices': Customer.STATUS_CHOICES,
        'filter_source_choices': SOURCE_FILTER_CHOICES,
        'total_leads_created': leads_created.filter(customer_type='lead').count(),
        'active_leads_count': active_leads.count(),
        'converted_count': converted_count,
        'pipeline_value': pipeline_value,
        'estimate_value_in_period': estimate_value_in_period,
        'stage_rows': stage_rows,
        'source_rows': source_rows,
        'unassigned_count': unassigned_count,
        'lead_details': lead_details,
        'lost_count': next(
            (row['count'] for row in stage_rows if row['slug'] == 'lost'),
            0,
        ),
        'won_stage_count': next(
            (row['count'] for row in stage_rows if row['converts_to_customer']),
            0,
        ),
        'negotiation_count': next(
            (row['count'] for row in stage_rows if 'negotiat' in row['slug'] or 'negotiat' in row['name'].lower()),
            0,
        ),
        'stage_max_count': stage_max_count,
        'source_max_count': source_max_count,
    }
