"""Shared OpenAI client, JSON parsing, and cache for AI Finance reports."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.core.cache import cache

from apps.inventory.utils import get_openai_api_key

from apps.core.openai_gateway import get_default_ai_model

CACHE_SECONDS = 30 * 60


class OpenAINotConfigured(Exception):
    pass


class AiQuotaExceeded(Exception):
    pass


def parse_openai_json(content: str) -> dict | list:
    from apps.core.openai_gateway import parse_openai_json as _parse

    return _parse(content)


def call_openai_json(*, system: str, user_payload: dict | list, temperature: float = 0.2) -> dict | list:
    from apps.core.openai_gateway import AiQuotaExceeded as GatewayQuotaExceeded
    from apps.core.openai_gateway import OpenAINotConfigured as GatewayNotConfigured
    from apps.core.openai_gateway import call_openai_json as gateway_call

    try:
        return gateway_call(
            system=system,
            user_payload=user_payload,
            temperature=temperature,
            feature='ai_finance',
            model=get_default_ai_model(),
        )
    except GatewayNotConfigured as exc:
        raise OpenAINotConfigured(str(exc)) from exc
    except GatewayQuotaExceeded as exc:
        raise AiQuotaExceeded(str(exc)) from exc


def cache_key(prefix: str, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
    return f'ai_finance:{prefix}:{digest}'


def get_cached(prefix: str, payload: dict) -> dict | None:
    key = cache_key(prefix, payload)
    data = cache.get(key)
    if data:
        data = dict(data)
        data['from_cache'] = True
        return data
    return None


def set_cached(prefix: str, payload: dict, result: dict) -> dict:
    key = cache_key(prefix, payload)
    out = dict(result)
    out['from_cache'] = False
    cache.set(key, out, timeout=CACHE_SECONDS)
    return out


def normalize_forecast_rows(raw: list, *, value_key: str = 'value') -> list[dict]:
    out = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        month = str(row.get('month', '')).strip()
        if not month:
            continue
        try:
            val = float(row.get(value_key, row.get('forecast', row.get('amount', 0))) or 0)
        except (TypeError, ValueError):
            val = 0.0
        conf = str(row.get('confidence', 'medium')).lower()
        if conf not in ('high', 'medium', 'low'):
            conf = 'medium'
        out.append({'month': month, 'value': round(val, 2), 'confidence': conf})
    return out


def linear_forecast(historical: list[float], months: int, start_year: int, start_month: int) -> list[dict]:
    """Simple trend forecast when OpenAI unavailable."""
    if not historical:
        return []
    n = len(historical)
    avg = sum(historical) / n
    if n >= 2:
        trend = (historical[-1] - historical[0]) / max(n - 1, 1)
    else:
        trend = 0.0
    out = []
    y, m = start_year, start_month
    for i in range(months):
        val = max(0.0, avg + trend * (i + 1))
        out.append({
            'month': f'{y:04d}-{m:02d}',
            'value': round(val, 2),
            'confidence': 'low',
        })
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out
