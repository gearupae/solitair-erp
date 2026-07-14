"""OpenAI-generated action summary for the AI forecast report (24h cache)."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from django.utils import timezone

from apps.inventory.models_reporting import InventoryAIActionSummary
from apps.inventory.utils import get_openai_api_key

CACHE_HOURS = 24


def _cache_key(report_snapshot: dict) -> str:
    raw = json.dumps(report_snapshot, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _fetch_bullets_from_openai(snapshot: dict) -> list[str]:
    from apps.core.openai_gateway import call_openai_raw, get_default_ai_model, parse_openai_json
    from apps.inventory.utils import is_ai_available

    if not is_ai_available():
        return _heuristic_bullets(snapshot)

    prompt = (
        'You are an inventory planner. Based on this forecast report snapshot, '
        'return exactly 5 specific, actionable bullet points for this week. '
        'Include item names, quantities, dates, and AED values where relevant. '
        'Return ONLY valid JSON: {"bullets": ["• action one", "• action two", ...]}\n\n'
        f'Snapshot:\n{json.dumps(snapshot, default=str)[:12000]}'
    )
    body = {
        'model': get_default_ai_model(),
        'messages': [
            {
                'role': 'system',
                'content': 'Inventory action assistant. Reply with JSON only, exactly 5 bullets.',
            },
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.3,
    }
    try:
        payload = call_openai_raw(body, feature='ai_action_summary')
        content = payload['choices'][0]['message']['content']
        data = parse_openai_json(content)
        bullets = data.get('bullets') or []
        cleaned = []
        for b in bullets[:5]:
            text = str(b).strip()
            if not text.startswith('•'):
                text = f'• {text.lstrip("-* ")}'
            cleaned.append(text)
        if len(cleaned) >= 3:
            return cleaned
    except Exception:
        pass
    return _heuristic_bullets(snapshot)


def _heuristic_bullets(snapshot: dict) -> list[str]:
    bullets = []
    for row in snapshot.get('priority_items', [])[:5]:
        name = row.get('item_name', 'Item')
        if row.get('stockout_risk') == 'High':
            qty = row.get('suggested_order_qty') or 0
            bullets.append(f'• Reorder {name} — suggested order {qty:g} units (stockout risk)')
        elif row.get('status') == 'Dead':
            val = row.get('dead_value') or 0
            bullets.append(f'• {name} is dead stock — AED {val:,.0f} locked, consider disposal')
        elif row.get('status') == 'Overstocked':
            bullets.append(f'• {name} is overstocked — review safety stock or transfer excess')
        elif row.get('trend') == 'up':
            bullets.append(f'• {name} demand rising — consider increasing safety stock')
        else:
            bullets.append(f'• Review {name} — {row.get("days_left", "—")} days of stock remaining')
    while len(bullets) < 5:
        bullets.append('• Review inventory forecast filters and refresh stale forecasts')
    return bullets[:5]


def get_action_summary(report_payload: dict, *, force: bool = False) -> dict:
    """Return cached or freshly generated action bullets."""
    summary = report_payload.get('summary', {})
    rows = report_payload.get('rows', [])
    priority = sorted(
        rows,
        key=lambda r: (
            0 if r.get('stockout_risk') == 'High' else 1,
            0 if r.get('status') == 'Dead' else 1,
            -(r.get('suggested_order_qty') or 0),
        ),
    )[:15]
    snapshot = {
        'kpis': {
            'stockout_risk_count': summary.get('stockout_risk_count'),
            'dead_stock_value': summary.get('dead_stock_value'),
            'overstock_value': summary.get('overstock_value'),
        },
        'priority_items': priority,
    }
    key = _cache_key(snapshot)
    if not force:
        cached = (
            InventoryAIActionSummary.objects.filter(cache_key=key)
            .order_by('-generated_at')
            .first()
        )
        if cached and cached.generated_at:
            age = timezone.now() - cached.generated_at
            if age.total_seconds() < CACHE_HOURS * 3600:
                return {
                    'bullets': cached.bullets,
                    'generated_at': cached.generated_at.isoformat(),
                    'from_cache': True,
                }

    bullets = _fetch_bullets_from_openai(snapshot)
    now = timezone.now()
    InventoryAIActionSummary.objects.update_or_create(
        cache_key=key,
        defaults={
            'bullets': bullets,
            'generated_at': now,
            'raw_response': json.dumps(snapshot, default=str)[:8000],
        },
    )
    return {
        'bullets': bullets,
        'generated_at': now.isoformat(),
        'from_cache': False,
    }
