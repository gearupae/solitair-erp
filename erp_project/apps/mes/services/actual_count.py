"""OpenAI vision counting for Manufacturing → Actual."""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.openai_gateway import AiQuotaExceeded, call_openai_json_with_images, get_default_ai_model
from apps.inventory.utils import is_ai_available

from ..models import ActualCountCapture, ActualCountDailyLog, ActualCountExampleImage, ActualCountSetting

logger = logging.getLogger(__name__)


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


def _load_example_images(*, company, item_names: list[str]) -> dict[str, list[str]]:
    """Return base64 data URLs grouped by item name for reference photos."""
    if not item_names:
        return {}
    names_lower = {_normalize_item_name(n).lower(): _normalize_item_name(n) for n in item_names}
    grouped: dict[str, list[str]] = {n: [] for n in item_names}
    qs = ActualCountExampleImage.objects.filter(
        company=company,
        is_active=True,
        item_name__in=item_names,
    ).order_by('item_name', 'id')
    for row in qs:
        canonical = names_lower.get(_normalize_item_name(row.item_name).lower(), row.item_name)
        if canonical not in grouped:
            grouped[canonical] = []
        try:
            with row.image.open('rb') as fh:
                raw = fh.read()
            mime = 'image/jpeg'
            name = (row.image.name or '').lower()
            if name.endswith('.png'):
                mime = 'image/png'
            elif name.endswith('.webp'):
                mime = 'image/webp'
            b64 = base64.b64encode(raw).decode('ascii')
            grouped[canonical].append(f'data:{mime};base64,{b64}')
        except OSError:
            logger.warning('Could not read example image pk=%s', row.pk)
    return grouped


def count_objects_in_image(
    *,
    image_base64: str,
    item_names: list[str],
    example_images: dict[str, list[str]] | None = None,
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

    examples = example_images or {}
    has_examples = any(examples.get(name) for name in items)

    example = json.dumps({name: 0 for name in items}, ensure_ascii=False)
    label_list = ', '.join(f'"{name}"' for name in items)

    system = (
        'You count physical objects in a live camera image. Return json only. '
        'For each label, count every separate visible instance in the CURRENT frame only. '
        'Use 0 when none are visible. Integer counts only; no notes or extra json keys.'
    )
    if has_examples:
        system += (
            ' Reference photos (if provided) show what each label looks like — match the same '
            'product type and shape (e.g. bottle-shaped containers count as "bottle" even if '
            'colour or label differs). Ignore similar-looking objects that are not the target item.'
        )
    else:
        system += (
            ' Match items by name and typical shape (e.g. "bottle" includes bottle-shaped '
            'containers and similar cylindrical vessels).'
        )

    user_parts = [
        f'Count how many of each item are visible in the LIVE camera image: {label_list}.',
        f'Return json like: {example}',
    ]
    if has_examples:
        user_parts.append(
            'Reference photos for each label are attached before the live frame — use them to '
            'recognise shape and appearance. The last image is the live camera frame.'
        )
    else:
        user_parts.append('The attached image is the live camera frame.')

    user_text = ' '.join(user_parts)

    images_payload: list[str] = []
    for name in items:
        for ref in examples.get(name) or []:
            images_payload.append(ref)
    images_payload.append(image_url)

    payload = call_openai_json_with_images(
        system=system,
        user_text=user_text,
        images_base64=images_payload,
        temperature=0,
        feature='mes_actual_count',
        model=get_default_ai_model(),
        reasoning_effort='none',
        json_schema=_count_schema(items),
        json_schema_name='actual_count',
        json_schema_strict=True,
    )
    return _counts_from_ai_payload(payload, items)


def _compute_deltas(
    new_counts: dict[str, int],
    last_counts: dict[str, int],
    presence_state: dict[str, bool],
) -> tuple[dict[str, int], dict[str, bool]]:
    """
    Increment daily totals using presence-aware deltas.

    - First sighting after frame was clear (or monitor start): log visible count.
    - While the same object(s) stay in frame: do not re-count on every scan.
    - If more instances appear while others remain visible: log only the increase.
    - When count drops to 0, clear presence so the next appearance counts again.
    """
    added: dict[str, int] = {}
    new_presence = dict(presence_state or {})

    for item, new_val in new_counts.items():
        new_val = max(0, int(new_val or 0))
        old_val = max(0, int(last_counts.get(item, 0) or 0))
        was_present = bool(presence_state.get(item))

        if new_val <= 0:
            new_presence[item] = False
            continue

        if not was_present:
            added[item] = new_val
            new_presence[item] = True
        elif new_val > old_val:
            added[item] = new_val - old_val

    return added, new_presence


def get_today_totals(company) -> dict[str, int]:
    today = timezone.localdate()
    return {
        row.item_name: row.count
        for row in ActualCountDailyLog.objects.filter(
            company=company, log_date=today, is_active=True,
        )
    }


def get_example_images_for_ui(company, item_names: list[str]) -> dict[str, list[dict]]:
    """Return example photo metadata for the template."""
    if not item_names:
        return {}
    qs = ActualCountExampleImage.objects.filter(
        company=company,
        is_active=True,
        item_name__in=item_names,
    ).order_by('item_name', 'id')
    grouped: dict[str, list[dict]] = {}
    for row in qs:
        grouped.setdefault(row.item_name, []).append({
            'id': row.pk,
            'url': row.image.url if row.image else '',
        })
    return grouped


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
        defaults={'item_names': [], 'last_capture_counts': {}, 'presence_state': {}},
    )
    item_names = [_normalize_item_name(n) for n in (setting.item_names or []) if _normalize_item_name(n)]
    if not item_names:
        raise ValueError('Add at least one item name before starting the camera count.')

    examples = _load_example_images(company=company, item_names=item_names)
    raw_counts = count_objects_in_image(
        image_base64=image_base64,
        item_names=item_names,
        example_images=examples,
    )
    last_counts = {k: int(v or 0) for k, v in (setting.last_capture_counts or {}).items()}
    presence_state = {k: bool(v) for k, v in (setting.presence_state or {}).items()}
    added_counts, new_presence = _compute_deltas(raw_counts, last_counts, presence_state)

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
    setting.presence_state = new_presence
    setting.save(update_fields=['last_capture_counts', 'presence_state', 'updated_at'])

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
    ActualCountSetting.objects.filter(company=company).update(
        last_capture_counts={},
        presence_state={},
    )


@transaction.atomic
def increment_counts(
    *,
    company,
    user,
    increments: dict[str, int],
    log_date: date | None = None,
) -> dict:
    """Fast path — client-side detection logs +1 (or more) without OpenAI."""
    setting, _ = ActualCountSetting.objects.select_for_update().get_or_create(
        company=company,
        defaults={'item_names': [], 'last_capture_counts': {}, 'presence_state': {}},
    )
    configured = [
        _normalize_item_name(n)
        for n in (setting.item_names or [])
        if _normalize_item_name(n)
    ]
    if not configured:
        raise ValueError('Add at least one item name before counting.')

    day = log_date or timezone.localdate()
    added: dict[str, int] = {}
    daily_totals: dict[str, int] = {}

    for raw_name, delta in increments.items():
        matched = _match_count_to_config(str(raw_name), configured)
        if not matched:
            continue
        try:
            qty = max(0, int(delta))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        log, _ = ActualCountDailyLog.objects.select_for_update().get_or_create(
            company=company,
            item_name=matched,
            log_date=day,
            defaults={'count': 0},
        )
        log.count += qty
        log.save(update_fields=['count', 'updated_at'])
        added[matched] = qty
        daily_totals[matched] = log.count

    if added:
        ActualCountCapture.objects.create(
            company=company,
            created_by=user,
            raw_counts={k: v for k, v in added.items()},
            added_counts=added,
        )

    return {
        'added_counts': added,
        'daily_totals': daily_totals,
        'today_totals': get_today_totals(company),
    }


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
