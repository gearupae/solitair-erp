"""Optional Celery tasks for Oracle sync (no-op when Celery is not configured)."""

from __future__ import annotations

try:
    from celery import shared_task
except ImportError:
    def shared_task(func=None, **_kwargs):
        def decorator(fn):
            return fn
        return decorator(func) if func else decorator


@shared_task
def push_wip_task(production_order_id: int) -> None:
    from django.conf import settings

    from apps.mes.models import ProductionOrder
    from apps.mes.services.oracle import OracleConnector

    if not getattr(settings, 'ORACLE_SYNC_ENABLED', False):
        return
    po = ProductionOrder.objects.filter(pk=production_order_id, is_active=True).first()
    if po:
        OracleConnector(company=po.company).push_wip(po)
