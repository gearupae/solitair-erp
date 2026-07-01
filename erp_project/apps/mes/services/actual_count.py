"""OpenAI vision counting for Manufacturing → Actual."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.openai_gateway import AiQuotaExceeded, call_openai_json_with_images
from apps.inventory.utils import is_ai_available

from ..models import ActualCountCapture, ActualCountDailyLog, ActualCountSetting

logger = logging.getLogger(__name__)

_COUNT_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'counts': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'item_name': {'type': 'string'},
                    'count': {'type': 'integer', 'minimum': 0},
                },
                'required': ['item_name', 'count'],
                'additionalProperties': False,
            },
        },
        'notes': {'type': 'string'},
    },
    'required': ['counts'],
    'additionalProperties': False,
}


def _normalize_item_name(name: str) -> str:
    return re.sub(r'\s+', ' ', (name or '').strip())


def _match_count_to_config(raw_name: str, configured: list[str]) -> str | None:
    """Map AI-returned label to a configured item name (case-insensitive)."""
    raw = _normalize_item_name(raw_name).lower()
    if not raw:
        return None
    for cfg in configured:
        if _normalize_item_name(cfg).lower() == raw:
            return _normalize_item_name(cfg)
    for cfg in configured:
        cfg_l = _normalize_item_name(cfg).lower()
        if raw in cfg_l or cfg_l in raw:
            return _normalize_item_name(cfg)
    return None


def _counts_from_ai_payload(payload: dict | list, configured: list[str]) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    result: dict[str, int] = {name: 0 for name in configured}
    for row in payload.get('counts') or []:
        if not isinstance(row, dict):
            continue
        matched = _match_count_to_config(str(row.get('item_name', '')), configured)
        if not matched:
            continue
        try:
            qty = max(0, int(row.get('count', 0)))
        except (TypeError, ValueError):
            qty = 0
        result[matched] = max(result.get(matched, 0), qty)
    return result


def count_objects_in_image(
    *,
    image_base64: str,
    item_names: list[str],
) -> dict[str, int]:
    """Send a camera frame to OpenAI vision and return counts per configured item."""
    items = [_normalize_item_name(n) for n in item_names if _normalize_item_name(n)]
    if not items:
        raise ValueError('Configure at least one item name to count.')
    if not is_ai_available():
        raise RuntimeError('OpenAI is not configured. Add an API key under Settings → Company.')

    b64 = image_base64.strip()
    if b64.startswith('data:'):
        b64 = b64.split(',', 1)[-1]

    system = (
        'You count physical objects visible in a factory or warehouse camera image. '
        'Return JSON only. For each requested item label, count distinct visible instances '
        'in the frame (not partial guesses). Match labels flexibly (synonyms, packaging text). '
        'If none are visible, return count 0 for that item.'
    )
    user_text = (
        'Count how many of each of these items are clearly visible in the image:\n'
        + '\n'.join(f'- {name}' for name in items)
    )

    payload = call_openai_json_with_images(
        system=system,
        user_text=user_text,
        images_base64=[b64],
        temperature=0.1,
        feature='mes_actual_count',
        json_schema=_COUNT_JSON_SCHEMA,
        json_schema_name='actual_count',
        json_schema_strict=True,
    )
    return _counts_from_ai_payload(payload, items)


def _compute_deltas(new_counts: dict[str, int], last_counts: dict[str, int]) -> dict[str, int]:
    """Increment only when count rises (object entered frame); reset baseline when count drops."""
    added: dict[str, int] = {}
    for item, new_val in new_counts.items():
        old_val = int(last_counts.get(item, 0) or 0)
        if new_val > old_val:
            added[item] = new_val - old_val
    return added


@transaction.atomic
def process_capture(
    *,
    company,
    user,
    image_base64: str,
    log_date: date | None = None,
) -> dict:
    """
    Analyze frame, apply delta logic, update daily logs, return summary for the UI.
    """
    setting, _ = ActualCountSetting.objects.select_for_update().get_or_create(
        company=company,
        defaults={'item_names': [], 'last_capture_counts': {}},
    )
    item_names = [_normalize_item_name(n) for n in (setting.item_names or []) if _normalize_item_name(n)]
    if not item_names:
        raise ValueError('Add at least one item name before starting the camera count.')

    raw_counts = count_objects_in_image(image_base64=image_base64, item_names=item_names)
    last_counts = {k: int(v or 0) for k, v in (setting.last_capture_counts or {}).items()}
    added_counts = _compute_deltas(raw_counts, last_counts)

    day = log_date or timezone.localdate()
    daily_totals: dict[str, int] = {}

    for item, delta in added_counts.items():
        if delta <= 0:
            continue
        log, _ = ActualCountDailyLog.objects.select_for_update().get_or_create(
            company=company,
            item_name=item,
            log_date=day,
            defaults={'count': 0},
        )
        log.count += delta
        log.save(update_fields=['count', 'updated_at'])
        daily_totals[item] = log.count

    setting.last_capture_counts = raw_counts
    setting.save(update_fields=['last_capture_counts', 'updated_at'])

    capture = ActualCountCapture.objects.create(
        company=company,
        created_by=user,
        raw_counts=raw_counts,
        added_counts=added_counts,
    )

    return {
        'capture_id': capture.pk,
        'captured_at': capture.captured_at.isoformat(),
        'raw_counts': raw_counts,
        'added_counts': added_counts,
        'daily_totals': daily_totals,
    }


def reset_capture_baseline(company) -> None:
    """Clear last-frame counts (e.g. when camera monitoring restarts)."""
    ActualCountSetting.objects.filter(company=company).update(last_capture_counts={})


def get_daily_log_rows(company, *, days: int = 30) -> list[dict]:
    """Grouped daily counts for the log table."""
    cutoff = timezone.localdate() - timedelta(days=max(1, days) - 1)
    qs = (
        ActualCountDailyLog.objects.filter(company=company, log_date__gte=cutoff, is_active=True)
        .order_by('-log_date', 'item_name')
    )
    return [
        {
            'item_name': row.item_name,
            'log_date': row.log_date.isoformat(),
            'count': row.count,
        }
        for row in qs
    ]
