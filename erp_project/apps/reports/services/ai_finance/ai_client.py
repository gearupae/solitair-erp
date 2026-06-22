"""Shared OpenAI client, JSON parsing, and cache for AI Finance reports."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.core.cache import cache

from apps.inventory.utils import get_openai_api_key

CACHE_SECONDS = 30 * 60
OPENAI_MODEL = 'gpt-4o-mini'


class OpenAINotConfigured(Exception):
    pass


def parse_openai_json(content: str) -> dict | list:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def call_openai_json(*, system: str, user_payload: dict | list, temperature: float = 0.2) -> dict | list:
    api_key = get_openai_api_key()
    if not api_key:
        raise OpenAINotConfigured('Configure OpenAI API key — set OPENAI_API_KEY in .env')

    import urllib.error
    import urllib.request

    body = json.dumps(
        {
            'model': OPENAI_MODEL,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(user_payload, default=str)},
            ],
            'temperature': temperature,
            'response_format': {'type': 'json_object'},
        }
    ).encode('utf-8')

    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode('utf-8', errors='replace')[:500]
        raise RuntimeError(f'OpenAI API error ({exc.code}): {err_body}') from exc

    content = payload['choices'][0]['message']['content']
    return parse_openai_json(content)


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
