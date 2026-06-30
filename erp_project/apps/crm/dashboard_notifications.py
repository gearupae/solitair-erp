"""Dashboard notifications for CRM pipeline events (e.g. site visit stage)."""
from __future__ import annotations

from django.urls import reverse

from apps.core.notification_utils import notify_user
from apps.core.utils import PermissionChecker
from apps.settings_app.models import Notification


def _lead_display_name(lead) -> str:
    return (lead.name or lead.company or lead.customer_number or '').strip() or f'Lead #{lead.pk}'


def get_site_visit_dashboard_alerts(user) -> list[dict]:
    """Leads currently in the configured site-visit kanban stage."""
    if not user or not getattr(user, 'is_authenticated', False):
        return []
    if not (user.is_superuser or PermissionChecker.has_permission(user, 'crm', 'view')):
        return []

    from apps.core.visibility import filter_customers_for_user
    from apps.crm.models import CrmLeadKanbanStage, Customer

    stage = CrmLeadKanbanStage.objects.filter(is_active=True, is_site_visit=True).first()
    if not stage:
        return []

    qs = filter_customers_for_user(
        Customer.objects.filter(
            is_active=True,
            customer_type='lead',
            lead_kanban_stage=stage,
        ).select_related('assigned_salesperson', 'lead_kanban_stage'),
        user,
    ).order_by('-updated_at')

    alerts = []
    for lead in qs:
        label = _lead_display_name(lead)
        link = reverse('crm:customer_detail', args=[lead.pk])
        alerts.append(
            {
                'kind': 'site_visit',
                'module_label': 'CRM',
                'record_label': label,
                'title': f'Lead in {stage.name}',
                'detail': lead.company or lead.customer_number,
                'link': link,
            }
        )
    return alerts


def sync_site_visit_notifications(user, alerts: list[dict]) -> None:
    """Create unread in-app notifications for site-visit leads (deduped per lead)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return
    for row in alerts:
        title = f"Site visit: {row['record_label']}"
        message = row['title']
        link = row['link']
        exists = Notification.objects.filter(
            user=user,
            is_read=False,
            link=link,
            title=title,
        ).exists()
        if not exists:
            notify_user(user, title, message, link)


def notify_site_visit_on_kanban_move(*, lead, stage, actor) -> None:
    """Notify assigned salesperson when a lead is moved into the site-visit stage."""
    if not stage or not getattr(stage, 'is_site_visit', False):
        return
    salesperson = getattr(lead, 'assigned_salesperson', None)
    user = getattr(salesperson, 'user', None) if salesperson else None
    if not user or not getattr(user, 'is_authenticated', False):
        return
    if actor and getattr(actor, 'pk', None) and user.pk == actor.pk:
        return
    label = _lead_display_name(lead)
    link = reverse('crm:customer_detail', args=[lead.pk])
    title = f'Site visit: {label}'
    message = f'Lead moved to {stage.name}'
    notify_user(user, title, message, link)


def get_dashboard_notifications(user) -> list[dict]:
    """All dashboard notification rows (extensible — add more kinds here)."""
    return get_site_visit_dashboard_alerts(user)


def sync_dashboard_notifications(user, alerts: list[dict]) -> None:
    sync_site_visit_notifications(user, alerts)
