"""OpenAI vision counting for Manufacturing → Actual."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.openai_gateway import AiQuotaExceeded, call_openai_json_with_images
from apps.inventory.utils import is_ai_available

from ..models import ActualCountCapture, ActualCountDailyLog, ActualCountSetting

logger = logging.getLogger(__name__)

# Fast vision model — count integers only, no reasoning chain.
ACTUAL_COUNT_MODEL = 'gpt-4o-mini'


def _normalize_item_name(name: str) -> str:
    return re.sub(r'\s+', ' ', (name or '').strip())


def _match_count_to_config(raw_name: str, configured: list[str]) -> str | None:
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


def _count_schema(item_names: list[str]) -> dict:
    """Strict schema: label -> integer count only (no extra fields)."""
    properties = {name: {'type': 'integer', 'minimum': 0} for name in item_names}
    return {
        'type': 'object',
        'properties': properties,
        'required': list(item_names),
        'additionalProperties': False,
    }


def _counts_from_ai_payload(payload: dict | list, configured: list[str]) -> dict[str, int]:
    result: dict[str, int] = {name: 0 for name in configured}
    if not isinstance(payload, dict):
        return result

    for cfg in configured:
        if cfg in payload:
            try:
                result[cfg] = max(0, int(payload[cfg]))
            except (TypeError, ValueError):
                result[cfg] = 0
            continue
        for key, val in payload.items():
            if key == 'counts':
                continue
            if _match_count_to_config(str(key), [cfg]):
                try:
                    result[cfg] = max(0, int(val))
                except (TypeError, ValueError):
                    result[cfg] = 0
                break

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
        image_url = b64
    else:
        image_url = f'data:image/jpeg;base64,{b64}'

    example = json.dumps({name: 0 for name in items}, ensure_ascii=False)
    label_list = ', '.join(f'"{name}"' for name in items)
    system = (
        'You count physical objects in a live camera image. Return json only. '
        'For each label, count every separate visible instance — identical items '
        'each count as 1 (e.g. 5 bottles on screen = 5). Use 0 when none are visible. '
        'Integer counts only; no notes or extra json keys.'
    )
    user_text = (
        f'Count how many of each item are visible right now: {label_list}. '
        f'Return json like: {example}'
    )

    payload = call_openai_json_with_images(
        system=system,
        user_text=user_text,
        images_base64=[image_url],
        temperature=0,
        feature='mes_actual_count',
        model=ACTUAL_COUNT_MODEL,
        reasoning_effort='none',
        json_schema=_count_schema(items),
        json_schema_name='actual_count',
        json_schema_strict=True,
    )
    return _counts_from_ai_payload(payload, items)


def _compute_deltas(new_counts: dict[str, int], last_counts: dict[str, int]) -> dict[str, int]:
    """
    Add to daily total when more items appear in frame than last scan.
    First scan after reset logs the full visible count (last is empty → full delta).
    """
    added: dict[str, int] = {}
    for item, new_val in new_counts.items():
        old_val = int(last_counts.get(item, 0) or 0)
        if new_val > old_val:
            added[item] = new_val - old_val
    return added


def get_today_totals(company) -> dict[str, int]:
    today = timezone.localdate()
    return {
        row.item_name: row.count
        for row in ActualCountDailyLog.objects.filter(
            company=company, log_date=today, is_active=True,
        )
    }


@transaction.atomic
def process_capture(
    *,
    company,
    user,
    image_base64: str,
    log_date: date | None = None,
) -> dict:
    """Analyze frame, apply delta logic, update daily logs, return summary for the UI."""
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

    capture_id = None
    if added_counts:
        capture = ActualCountCapture.objects.create(
            company=company,
            created_by=user,
            raw_counts=raw_counts,
            added_counts=added_counts,
        )
        capture_id = capture.pk

    return {
        'capture_id': capture_id,
        'raw_counts': raw_counts,
        'added_counts': added_counts,
        'daily_totals': daily_totals,
        'today_totals': get_today_totals(company),
    }


def reset_capture_baseline(company) -> None:
    ActualCountSetting.objects.filter(company=company).update(last_capture_counts={})


def get_daily_log_rows(company, *, days: int = 30) -> list[dict]:
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
