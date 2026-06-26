"""Gearup AI features for the CEO dashboard."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

BRIEFING_CACHE_PREFIX = 'ceo:daily_briefing:'
RISK_CACHE_PREFIX = 'ceo:risk_alerts:'
CACHE_HOURS = 20


def _ceo_model() -> str:
    from django.conf import settings
    from apps.core.openai_gateway import resolve_openai_model

    override = getattr(settings, 'OPENAI_CEO_MODEL', '') or 'gpt-5.4-mini'
    return resolve_openai_model(override)


def _ai_available() -> bool:
    from apps.inventory.utils import is_ai_available

    return is_ai_available()


def generate_daily_briefing(metrics_snapshot: dict, *, force: bool = False) -> dict:
    """One-paragraph executive summary from live metrics."""
    today = timezone.localdate().isoformat()
    cache_key = f'{BRIEFING_CACHE_PREFIX}{today}'
    if not force:
        cached = cache.get(cache_key)
        if cached:
            return {**cached, 'from_cache': True}

    fallback = _fallback_briefing(metrics_snapshot)
    if not _ai_available():
        return {'text': fallback, 'from_cache': False, 'ai_used': False}

    from apps.core.openai_gateway import call_openai_json

    system = """You are Gearup AI, an executive briefing assistant for a UAE company CEO.
Write ONE concise paragraph (4–6 sentences) summarising today's business state.
Cover: revenue vs target, cash position, top receivable/payable risks, pipeline health, anything materially changed.
Be direct and decision-focused. No bullet points. No markdown. Plain English only."""

    try:
        briefing_schema = {
            'type': 'object',
            'properties': {'briefing': {'type': 'string'}},
            'required': ['briefing'],
            'additionalProperties': False,
        }
        data = call_openai_json(
            system=system,
            user_payload={'date': today, 'metrics': metrics_snapshot},
            temperature=0,
            feature='ceo_daily_briefing',
            model=_ceo_model(),
            reasoning_effort='low',
            json_schema=briefing_schema,
            json_schema_name='ceo_briefing',
            json_schema_strict=False,
        )
        text = (data.get('briefing') or '').strip()
        if not text:
            text = fallback
        result = {'text': text, 'from_cache': False, 'ai_used': True}
    except Exception as exc:
        logger.warning('CEO briefing AI failed: %s', exc)
        result = {'text': fallback, 'from_cache': False, 'ai_used': False}

    cache.set(cache_key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def _fallback_briefing(metrics: dict) -> str:
    rev = metrics.get('revenue_month', {})
    recv = metrics.get('receivables', {})
    cash = metrics.get('cash_position', 0)
    pipe = metrics.get('pipeline', {})
    parts = [
        f"Cash position is AED {cash:,.0f}.",
    ]
    if rev.get('pct_of_target') is not None:
        parts.append(
            f"Revenue this month is at {rev['pct_of_target']}% of target "
            f"(AED {rev.get('actual', 0):,.0f})."
        )
    if recv.get('overdue', 0):
        parts.append(f"AED {recv['overdue']:,.0f} in receivables is overdue.")
    parts.append(
        f"Sales pipeline stands at AED {pipe.get('pipeline_total', 0):,.0f} "
        f"with weighted forecast AED {pipe.get('weighted_forecast', 0):,.0f}."
    )
    return ' '.join(parts)


def generate_risk_alerts(metrics_snapshot: dict, rule_alerts: list, *, force: bool = False) -> dict:
    """AI-enhanced risk alerts on top of rule-based flags."""
    today = timezone.localdate().isoformat()
    cache_key = f'{RISK_CACHE_PREFIX}{today}'
    if not force:
        cached = cache.get(cache_key)
        if cached:
            return {**cached, 'from_cache': True}

    alerts = list(rule_alerts)
    if not _ai_available():
        return {'alerts': alerts, 'from_cache': False, 'ai_used': False}

    from apps.core.openai_gateway import call_openai_json

    schema = {
        'type': 'object',
        'properties': {
            'alerts': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'severity': {'type': 'string'},
                        'title': {'type': 'string'},
                        'detail': {'type': 'string'},
                        'action': {'type': 'string'},
                    },
                    'required': ['severity', 'title', 'detail', 'action'],
                    'additionalProperties': False,
                },
            },
        },
        'required': ['alerts'],
        'additionalProperties': False,
    }

    system = """You are Gearup AI risk analyst for a CEO dashboard.
Given live ERP metrics and existing rule-based alerts, return 3–8 anomaly/risk alerts max.
Flag: slow-paying clients, cost spikes, quiet deals, bad debt risk, concentration, compliance.
Each alert needs severity (high|medium|low), title, one-line detail, one-line suggested action.
Merge with existing alerts; do not duplicate. Keep total alerts under 10."""

    try:
        data = call_openai_json(
            system=system,
            user_payload={
                'date': today,
                'metrics': metrics_snapshot,
                'existing_alerts': rule_alerts,
            },
            temperature=0,
            feature='ceo_risk_alerts',
            model=_ceo_model(),
            reasoning_effort='low',
            json_schema=schema,
            json_schema_name='ceo_risk_alerts',
            json_schema_strict=False,
        )
        ai_alerts = list(data.get('alerts') or []) if isinstance(data, dict) else []
        seen_titles = {a['title'].lower() for a in alerts}
        for row in ai_alerts:
            title = (row.get('title') or '').strip()
            if title and title.lower() not in seen_titles:
                alerts.append({
                    'severity': (row.get('severity') or 'medium').lower(),
                    'title': title,
                    'detail': row.get('detail') or '',
                    'action': row.get('action') or '',
                })
                seen_titles.add(title.lower())
        result = {'alerts': alerts[:12], 'from_cache': False, 'ai_used': True}
    except Exception as exc:
        logger.warning('CEO risk AI failed: %s', exc)
        result = {'alerts': alerts, 'from_cache': False, 'ai_used': False}

    cache.set(cache_key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result
