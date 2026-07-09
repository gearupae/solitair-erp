"""Daily Visit Record (DVR) report."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.crm.models import SiteVisitLog
from apps.crm.utils import filter_customers_for_user, get_sales_employee_queryset, salesperson_display_name

User = get_user_model()


def _salesman_label(user) -> str:
    if not user:
        return '—'
    name = user.get_full_name() or user.get_username()
    return name.strip() or str(user)


def build_dvr_report(*, start_date, end_date, salesman_user_id='', user=None):
    qs = (
        SiteVisitLog.objects.filter(
            is_active=True,
            visit_date__gte=start_date,
            visit_date__lte=end_date,
        )
        .select_related('lead', 'salesman')
        .order_by('-visit_date', '-created_at')
    )

    if user:
        allowed_leads = filter_customers_for_user(
            qs.model.lead.field.related_model.objects.filter(is_active=True),
            user,
        ).values_list('pk', flat=True)
        qs = qs.filter(lead_id__in=allowed_leads)

    if salesman_user_id == 'none':
        qs = qs.filter(salesman__isnull=True)
    elif salesman_user_id:
        try:
            qs = qs.filter(salesman_id=int(salesman_user_id))
        except (TypeError, ValueError):
            pass

    rows = []
    for visit in qs[:1000]:
        lead = visit.lead
        visit_when = visit.visit_datetime or visit.created_at
        rows.append({
            'pk': visit.pk,
            'visit_date': visit.visit_date,
            'visit_datetime': visit_when,
            'visit_time_display': timezone.localtime(visit_when).strftime('%H:%M') if visit_when else '',
            'lead_pk': lead.pk if lead else None,
            'lead_label': lead.display_name or lead.customer_number if lead else '—',
            'lead_number': lead.customer_number if lead else '',
            'salesman_name': _salesman_label(visit.salesman),
            'location': visit.location or '—',
            'outcome': visit.get_outcome_display(),
            'outcome_code': visit.outcome,
            'notes': visit.notes or '',
            'has_selfie': bool(visit.selfie),
        })

    salespeople = []
    seen = set()
    for emp in get_sales_employee_queryset():
        if emp.user_id and emp.user_id not in seen:
            seen.add(emp.user_id)
            salespeople.append({'id': emp.user_id, 'label': salesperson_display_name(emp)})
    for u in User.objects.filter(is_active=True).order_by('first_name', 'username')[:200]:
        if u.pk not in seen:
            salespeople.append({'id': u.pk, 'label': _salesman_label(u)})

    return {
        'start_date': start_date,
        'end_date': end_date,
        'filter_salesman': salesman_user_id,
        'filter_salespeople': salespeople,
        'visit_rows': rows,
        'total_visits': len(rows),
    }
