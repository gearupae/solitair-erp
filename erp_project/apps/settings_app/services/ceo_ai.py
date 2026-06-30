"""Gearup AI features for the CEO dashboard."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

BRIEFING_CACHE_PREFIX = 'ceo:daily_briefing:'
RISK_CACHE_PREFIX = 'ceo:risk_alerts:'
PREDICTIVE_CASH_PREFIX = 'ceo:predictive_cash:'
COLLECTIONS_PREFIX = 'ceo:collections:'
OPERATIONS_PREFIX = 'ceo:operations:'
CACHE_HOURS = 20


def _ceo_model() -> str:
    from django.conf import settings
    from apps.core.openai_gateway import resolve_openai_model

    override = getattr(settings, 'OPENAI_CEO_MODEL', '') or 'gpt-5.5-mini'
    return resolve_openai_model(override)


def _ai_available() -> bool:
    from apps.inventory.utils import is_ai_available

    return is_ai_available()


def generate_daily_briefing(metrics_snapshot: dict, *, force: bool = False) -> dict:
    """One-paragraph executive summary from live metrics — cash first."""
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
MANDATORY: The FIRST sentence must state cash position and runway urgency (AED amount, weeks left if critical).
Then cover receivables/overdue, revenue vs MTD target, pipeline, and top risks.
Be direct and decision-focused. No bullet points. No markdown. Plain English only.
End with one clear priority action for today."""

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
    runway = metrics.get('runway', {})
    pipe = metrics.get('pipeline', {})
    parts = [
        f"Cash is AED {cash:,.0f}",
    ]
    if runway.get('weeks') is not None:
        parts[0] += f" — about {runway['weeks']:.0f} weeks runway at current burn"
        if runway.get('critical'):
            parts[0] += ' (critical)'
    parts[0] += '.'
    if recv.get('overdue', 0):
        parts.append(f"AED {recv['overdue']:,.0f} in receivables is overdue against AED {recv.get('total', 0):,.0f} outstanding.")
    if rev.get('pct_of_target') is not None:
        parts.append(
            f"MTD revenue is {rev['pct_of_target']}% of prorated target "
            f"(AED {rev.get('actual', 0):,.0f} vs AED {rev.get('target_mtd', 0):,.0f})."
        )
    parts.append(
        f"Pipeline AED {pipe.get('pipeline_total', 0):,.0f} "
        f"(weighted forecast AED {pipe.get('weighted_forecast', 0):,.0f})."
    )
    if runway.get('critical') or recv.get('overdue', 0):
        parts.append('Priority: chase overdue receivables today.')
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
Every alert MUST end with a concrete action. Merge with existing alerts; do not duplicate. Keep total under 10."""

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


def generate_predictive_cash_alert(metrics_snapshot: dict, *, force: bool = False) -> dict:
    """Predict when cash hits zero based on collection pace and payables."""
    today = timezone.localdate().isoformat()
    cache_key = f'{PREDICTIVE_CASH_PREFIX}{today}'
    if not force:
        cached = cache.get(cache_key)
        if cached:
            return {**cached, 'from_cache': True}

    fallback = _fallback_predictive_cash(metrics_snapshot)
    if not _ai_available():
        return {'text': fallback, 'from_cache': False, 'ai_used': False}

    from apps.core.openai_gateway import call_openai_json

    schema = {
        'type': 'object',
        'properties': {
            'alert': {'type': 'string'},
            'zero_date': {'type': 'string'},
            'top_clients': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['alert'],
        'additionalProperties': False,
    }

    system = """You are Gearup AI cash analyst for a UAE CEO.
Using live metrics (cash, burn, receivables, overdue, payables due, collection candidates), predict when cash could hit zero.
Output plain English in 'alert' field, format like:
"At current collection pace, cash reaches zero around [date] unless you collect from [top clients]."
Be specific with AED amounts and client names from the data. Keep under 3 sentences. Always suggest who to collect from first."""

    try:
        data = call_openai_json(
            system=system,
            user_payload={'date': today, 'metrics': metrics_snapshot},
            temperature=0,
            feature='ceo_predictive_cash',
            model=_ceo_model(),
            reasoning_effort='low',
            json_schema=schema,
            json_schema_name='ceo_predictive_cash',
            json_schema_strict=False,
        )
        text = (data.get('alert') or '').strip() or fallback
        result = {
            'text': text,
            'zero_date': data.get('zero_date') or '',
            'top_clients': data.get('top_clients') or [],
            'from_cache': False,
            'ai_used': True,
        }
    except Exception as exc:
        logger.warning('CEO predictive cash AI failed: %s', exc)
        result = {'text': fallback, 'from_cache': False, 'ai_used': False}

    cache.set(cache_key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def _fallback_predictive_cash(metrics: dict) -> str:
    cash = metrics.get('cash_position', 0)
    burn = metrics.get('monthly_burn') or metrics.get('runway', {}).get('burn', 0)
    recv = metrics.get('receivables', {})
    candidates = metrics.get('collection_candidates') or []
    names = [c.get('name') for c in candidates[:3] if c.get('name')]
    if burn and cash:
        months = cash / burn
        weeks = months * 4.33
        date_hint = f"in about {weeks:.0f} weeks" if weeks < 52 else f"in about {months:.0f} months"
    else:
        date_hint = 'soon if burn continues'
    client_part = ', '.join(names) if names else 'top overdue clients'
    return (
        f"At current burn (~AED {burn:,.0f}/mo), cash of AED {cash:,.0f} may run out {date_hint} "
        f"unless you collect AED {recv.get('overdue', 0):,.0f} overdue from {client_part}."
    )


def generate_ranked_collections(metrics_snapshot: dict, candidates: list, *, force: bool = False) -> dict:
    """AI-ranked collections list with 'why prioritise' for each client."""
    today = timezone.localdate().isoformat()
    cache_key = f'{COLLECTIONS_PREFIX}{today}'
    if not force:
        cached = cache.get(cache_key)
        if cached:
            return {**cached, 'from_cache': True}

    fallback = _fallback_collections(metrics_snapshot, candidates)
    if not _ai_available():
        return {**fallback, 'from_cache': False, 'ai_used': False}

    from apps.core.openai_gateway import call_openai_json

    schema = {
        'type': 'object',
        'properties': {
            'headline': {'type': 'string'},
            'items': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'days_overdue': {'type': 'integer'},
                        'why': {'type': 'string'},
                    },
                    'required': ['name', 'amount', 'days_overdue', 'why'],
                    'additionalProperties': False,
                },
            },
        },
        'required': ['headline', 'items'],
        'additionalProperties': False,
    }

    system = """You are Gearup AI collections advisor for a UAE CEO.
Rank overdue clients to chase first using: amount owed × days overdue × payment slowness.
Return top 5 in 'items' with short 'why prioritise' (one line each).
'headline' must be one line like: "Collecting these covers payroll / this week's payables" with AED totals from data.
Use client names from candidates; never say Unknown — use Client #ID if name missing."""

    try:
        data = call_openai_json(
            system=system,
            user_payload={
                'date': today,
                'metrics': metrics_snapshot,
                'candidates': candidates,
            },
            temperature=0,
            feature='ceo_collections',
            model=_ceo_model(),
            reasoning_effort='low',
            json_schema=schema,
            json_schema_name='ceo_collections',
            json_schema_strict=False,
        )
        items = data.get('items') or []
        if not items:
            items = fallback['items']
        result = {
            'headline': (data.get('headline') or fallback['headline']).strip(),
            'items': items[:5],
            'from_cache': False,
            'ai_used': True,
        }
    except Exception as exc:
        logger.warning('CEO collections AI failed: %s', exc)
        result = {**fallback, 'from_cache': False, 'ai_used': False}

    cache.set(cache_key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def _fallback_collections(metrics: dict, candidates: list) -> dict:
    burn = metrics.get('monthly_burn') or metrics.get('runway', {}).get('burn', 0)
    pay_week = metrics.get('payables_week', {}).get('total', 0)
    total_top = sum(c.get('amount', 0) for c in candidates[:5])
    need = max(burn / 4, pay_week)
    headline = (
        f"Collecting these AED {total_top:,.0f} covers this week's payables (AED {pay_week:,.0f} due)."
        if pay_week
        else f"Collecting these AED {total_top:,.0f} helps cover ~AED {need:,.0f} near-term cash needs."
    )
    items = []
    for c in candidates[:5]:
        items.append({
            'name': c.get('name', 'Unassigned'),
            'amount': c.get('amount', 0),
            'days_overdue': c.get('max_days_overdue', 0),
            'why': f"AED {c.get('amount', 0):,.0f} · {c.get('max_days_overdue', 0)}d overdue · slow payer score {c.get('slowness', 1):.1f}",
        })
    return {'headline': headline, 'items': items}


def generate_operations_summaries(
    projects_overview: dict,
    hr_overview: dict,
    *,
    force: bool = False,
) -> dict:
    """AI summaries for Projects and HR overview cards."""
    today = timezone.localdate().isoformat()
    cache_key = f'{OPERATIONS_PREFIX}{today}'
    if not force:
        cached = cache.get(cache_key)
        if cached:
            return {**cached, 'from_cache': True}

    projects_fb = _fallback_projects_summary(projects_overview)
    hr_fb = _fallback_hr_summary(hr_overview)

    if not _ai_available():
        return {
            'projects_text': projects_fb,
            'hr_text': hr_fb,
            'from_cache': False,
            'ai_used': False,
        }

    from apps.core.openai_gateway import call_openai_json

    schema = {
        'type': 'object',
        'properties': {
            'projects_summary': {'type': 'string'},
            'hr_summary': {'type': 'string'},
        },
        'required': ['projects_summary', 'hr_summary'],
        'additionalProperties': False,
    }

    system = """You are Gearup AI for a UAE company CEO dashboard.
Write TWO separate summaries (2-3 sentences each, plain English, no markdown).

PROJECTS summary must cover:
- Yesterday: tasks completed, delivery momentum
- This month vs last: completions, pace
- Issues: delays, stalls, overload (only if data shows problems)

HR summary must cover:
- Yesterday: attendance, absences, pending approvals
- This month vs last: headcount change, joiners/leavers
- Issues: expiring docs, absence spikes (only if present)

Be factual, short, decision-focused. Use numbers from the payload."""

    try:
        data = call_openai_json(
            system=system,
            user_payload={
                'date': today,
                'projects': projects_overview,
                'hr': hr_overview,
            },
            temperature=0,
            feature='ceo_operations_summary',
            model=_ceo_model(),
            reasoning_effort='low',
            json_schema=schema,
            json_schema_name='ceo_operations',
            json_schema_strict=False,
        )
        result = {
            'projects_text': (data.get('projects_summary') or projects_fb).strip(),
            'hr_text': (data.get('hr_summary') or hr_fb).strip(),
            'from_cache': False,
            'ai_used': True,
        }
    except Exception as exc:
        logger.warning('CEO operations AI failed: %s', exc)
        result = {
            'projects_text': projects_fb,
            'hr_text': hr_fb,
            'from_cache': False,
            'ai_used': False,
        }

    cache.set(cache_key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def _fallback_projects_summary(p: dict) -> str:
    parts = [
        f"Yesterday: {p.get('tasks_completed_yesterday', 0)} task(s) completed.",
        (
            f"This month: {p.get('completed_mtd', 0)} project(s) delivered "
            f"vs {p.get('completed_last_month', 0)} last month; "
            f"{p.get('on_track_pct', 0)}% on track ({p.get('active_count', 0)} active, "
            f"avg progress {p.get('avg_progress_pct', 0)}%)."
        ),
    ]
    flags = p.get('issue_flags') or []
    if flags:
        parts.append(f"Issues: {flags[0].get('detail', 'Review flagged projects.')}")
    else:
        parts.append('No critical project issues flagged.')
    return ' '.join(parts)


def _fallback_hr_summary(h: dict) -> str:
    att = h.get('attendance_yesterday') or {}
    rate = att.get('attendance_rate')
    rate_txt = f"{rate}%" if rate is not None else 'n/a'
    parts = [
        (
            f"Yesterday: {att.get('present', 0)} present, {att.get('absent', 0)} absent "
            f"({rate_txt} attendance); {h.get('pending_leave', 0)} leave pending."
        ),
        (
            f"This month: headcount {h.get('headcount', 0)} "
            f"({h.get('joiners_mtd', 0)} joined, {h.get('leavers_mtd', 0)} left)."
        ),
    ]
    docs = h.get('docs_expiring_30d', 0)
    if docs:
        parts.append(f"Issues: {docs} employee document(s) expired or expiring within 30 days.")
    elif (h.get('issue_flags') or []):
        parts.append(f"Issues: {h['issue_flags'][0].get('detail', 'Review HR alerts.')}")
    else:
        parts.append('People operations look stable.')
    return ' '.join(parts)
