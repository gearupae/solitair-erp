"""Oracle REST connector — talks to oracle_mock or real Oracle via ORACLE_BASE_URL."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.mes.models import MaterialConsumption, OracleSyncLog, ProductionOrder
from apps.mes.utils import get_default_mes_company

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = 0.5

ORACLE_STATUS_MAP = {
    'Released': ProductionOrder.STATUS_RELEASED,
    'In Progress': ProductionOrder.STATUS_IN_PRODUCTION,
    'In Production': ProductionOrder.STATUS_IN_PRODUCTION,
    'On Hold': ProductionOrder.STATUS_ON_HOLD,
    'Complete': ProductionOrder.STATUS_FINISHED,
    'Completed': ProductionOrder.STATUS_FINISHED,
    'Finished': ProductionOrder.STATUS_FINISHED,
}


def _parse_oracle_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class OracleConnector:
    """Bi-directional Oracle REST adapter (mock or production)."""

    def __init__(self, company=None):
        self.company = company or get_default_mes_company()
        self.base_url = getattr(settings, 'ORACLE_BASE_URL', '').rstrip('/')
        self.auth_token = getattr(settings, 'ORACLE_AUTH_TOKEN', '')

    def _headers(self) -> dict[str, str]:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if self.auth_token:
            headers['Authorization'] = f'Bearer {self.auth_token}'
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        direction: str,
        entity: str,
        payload: dict | None = None,
    ) -> dict[str, Any]:
        url = f'{self.base_url}{path}'
        body = json.dumps(payload or {}).encode('utf-8') if payload is not None else None
        log = OracleSyncLog.objects.create(
            company=self.company,
            direction=direction,
            entity=entity,
            payload=payload or {},
            status=OracleSyncLog.STATUS_PENDING,
        )
        last_error = ''
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=self._headers(), method=method)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read().decode('utf-8')
                    data = json.loads(raw) if raw else {}
                log.status = OracleSyncLog.STATUS_SUCCESS
                log.retry_count = attempt - 1
                log.payload = {'request': payload or {}, 'response': data}
                log.save(update_fields=['status', 'retry_count', 'payload', 'updated_at'])
                return data
            except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
                last_error = str(exc)
                log.retry_count = attempt
                log.error = last_error
                log.save(update_fields=['retry_count', 'error', 'updated_at'])
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SECONDS * attempt)
        log.status = OracleSyncLog.STATUS_FAILED
        log.error = last_error
        log.save(update_fields=['status', 'error', 'updated_at'])
        logger.warning('Oracle %s %s failed: %s', method, path, last_error)
        return {}

    def pull_production_orders(self) -> dict[str, int]:
        """Import work orders from Oracle into MES ProductionOrder rows."""
        data = self._request(
            'GET',
            '/production-orders/',
            direction=OracleSyncLog.DIRECTION_IN,
            entity='production_order',
        )
        created = updated = 0
        for row in data.get('items', []):
            po_number = row.get('WorkOrderNumber') or row.get('ProductionOrderNumber')
            if not po_number:
                continue
            status = ORACLE_STATUS_MAP.get(
                row.get('StatusCode', 'Released'),
                ProductionOrder.STATUS_RELEASED,
            )
            defaults = {
                'reference': row.get('WorkOrderDescription') or row.get('Description') or '',
                'quantity': int(row.get('Quantity') or 1),
                'planned_start': _parse_oracle_date(row.get('ScheduledStartDate')),
                'planned_end': _parse_oracle_date(row.get('ScheduledCompletionDate')),
                'status': status,
                'wip_value': Decimal(str(row.get('WIPValue') or '0')),
                'is_active': True,
            }
            obj, was_created = ProductionOrder.objects.update_or_create(
                company=self.company,
                po_number=po_number,
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return {'created': created, 'updated': updated}

    def pull_items(self) -> list[dict]:
        """Fetch item master from Oracle (returns raw items for future BOM mapping)."""
        data = self._request(
            'GET',
            '/items/',
            direction=OracleSyncLog.DIRECTION_IN,
            entity='item_master',
        )
        return data.get('items', [])

    def push_material_consumption(self, consumption: MaterialConsumption) -> bool:
        payload = {
            'OrganizationCode': 'DEPA_MAIN',
            'WorkOrderNumber': consumption.production_order.po_number,
            'ItemNumber': consumption.bom_item.item_code or consumption.bom_item.part_name,
            'Quantity': str(consumption.qty_consumed),
            'UOMCode': consumption.bom_item.unit.upper(),
            'TransactionDate': timezone.localtime(consumption.created_at).date().isoformat(),
        }
        data = self._request(
            'POST',
            '/material-consumption/',
            direction=OracleSyncLog.DIRECTION_OUT,
            entity='material_consumption',
            payload=payload,
        )
        return data.get('Status') == 'SUCCESS'

    def push_wip(self, production_order: ProductionOrder) -> bool:
        payload = {
            'OrganizationCode': 'DEPA_MAIN',
            'WorkOrderNumber': production_order.po_number,
            'WIPValue': str(production_order.wip_value),
            'CurrencyCode': 'AED',
        }
        data = self._request(
            'POST',
            '/wip-valuation/',
            direction=OracleSyncLog.DIRECTION_OUT,
            entity='wip_valuation',
            payload=payload,
        )
        return data.get('Status') == 'SUCCESS'

    def push_dispatch(self, dispatch_note) -> bool:
        payload = {
            'OrganizationCode': 'DEPA_MAIN',
            'DispatchNoteNumber': dispatch_note.note_number,
            'WorkOrderNumber': dispatch_note.production_order.po_number,
            'DeliveryConfirmed': dispatch_note.delivery_confirmed,
            'DispatchedAt': (
                dispatch_note.dispatched_at.isoformat()
                if dispatch_note.dispatched_at
                else None
            ),
        }
        data = self._request(
            'POST',
            '/dispatch-confirm/',
            direction=OracleSyncLog.DIRECTION_OUT,
            entity='dispatch_confirm',
            payload=payload,
        )
        return data.get('Status') == 'SUCCESS'


def _oracle_sync_enabled() -> bool:
    return bool(getattr(settings, 'ORACLE_SYNC_ENABLED', False))


def enqueue_push_wip(production_order: ProductionOrder) -> None:
    """Queue WIP push via Celery when Oracle sync is enabled."""
    if not _oracle_sync_enabled():
        return
    try:
        from apps.mes.tasks import push_wip_task

        push_wip_task.delay(production_order.pk)
    except Exception:
        connector = OracleConnector(company=production_order.company)
        connector.push_wip(production_order)


@transaction.atomic
def sync_material_consumption(consumption: MaterialConsumption) -> None:
    """Push consumption to Oracle and mark posted (when Oracle sync is enabled)."""
    if not _oracle_sync_enabled():
        return
    if consumption.oracle_posted:
        return
    connector = OracleConnector(company=consumption.company)
    if connector.push_material_consumption(consumption):
        consumption.oracle_posted = True
        consumption.save(update_fields=['oracle_posted', 'updated_at'])
