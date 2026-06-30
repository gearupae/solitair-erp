"""Gearup AI summaries for HR KPI dashboard."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_PREFIX = 'hr:kpi_ai:'
CACHE_HOURS = 12


def _kpi_model() -> str:
    from django.conf import settings
    from apps.core.openai_gateway import resolve_openai_model

    override = getattr(settings, 'OPENAI_CEO_MODEL', '') or 'gpt-5.5-mini'
    return resolve_openai_model(override)


def _ai_available() -> bool:
    from apps.inventory.utils import is_ai_available

    return is_ai_available()


def generate_track_summaries(track: str, rows: list[dict], *, force: bool = False) -> dict:
    """Performance review per employee for a KPI track."""
    today = timezone.localdate().isoformat()
    cache_key = f'{CACHE_PREFIX}{track}:{today}'
    if not force:
        cached = cache.get(cache_key)
        if cached:
            return {**cached, 'from_cache': True}

    summaries = _fallback_summaries(track, rows)
    if not _ai_available() or not rows:
        return {'summaries': summaries, 'from_cache': False, 'ai_used': False}

    from apps.core.openai_gateway import call_openai_json

    schema = {
        'type': 'object',
        'properties': {
            'items': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'employee_id': {'type': 'integer'},
                        'summary': {'type': 'string'},
                    },
                    'required': ['employee_id', 'summary'],
                    'additionalProperties': False,
                },
            },
        },
        'required': ['items'],
        'additionalProperties': False,
    }

    system = """You are Gearup AI HR performance reviewer for a UAE company.
For each employee write ONE sentence (max 28 words) as a performance review.

Must include:
1) Overall verdict: "Overall good" / "Needs improvement" / "At risk" based on score_pct
2) Score context: mention score_pct (includes HR plus/negative points in the %)
3) If tasks_overdue, projects_delayed, or open items are high — flag delays or issues explicitly
4) If HR remark_points are negative, mention the concern

Use only provided data. Plain English, no markdown."""

    payload_rows = []
    for row in rows[:25]:
        payload_rows.append({
            **row,
            'delayed_items': (
                row.get('detail', {}).get('tasks_overdue', 0)
                + row.get('detail', {}).get('projects_delayed', 0)
            ),
        })

    try:
        data = call_openai_json(
            system=system,
            user_payload={'track': track, 'date': today, 'rows': payload_rows},
            temperature=0,
            feature='hr_kpi_summary',
            model=_kpi_model(),
            reasoning_effort='low',
            json_schema=schema,
            json_schema_name='hr_kpi_summaries',
            json_schema_strict=False,
        )
        for item in data.get('items') or []:
            eid = item.get('employee_id')
            text = (item.get('summary') or '').strip()
            if eid and text:
                summaries[str(eid)] = text
        result = {'summaries': summaries, 'from_cache': False, 'ai_used': True}
    except Exception as exc:
        logger.warning('HR KPI AI failed for %s: %s', track, exc)
        result = {'summaries': summaries, 'from_cache': False, 'ai_used': False}

    cache.set(cache_key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def _fallback_summaries(track: str, rows: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        eid = str(row['employee_id'])
        pct = row.get('score_pct', row.get('work_pct', 0))
        remark = row.get('remark_points', 0)
        detail = row.get('detail') or {}
        overdue = detail.get('tasks_overdue', 0) + detail.get('projects_delayed', 0)
        open_cnt = row.get('in_progress', 0)

        if pct >= 75 and overdue == 0:
            verdict = 'Overall good —'
        elif pct >= 50:
            verdict = 'Acceptable —'
        elif row.get('total', 0) > 0:
            verdict = 'Needs improvement —'
        else:
            verdict = 'Limited data —'

        parts = [
            verdict,
            f"score {pct}% ({row.get('completed', 0)}+HR {remark:+d} / {row.get('total', 0)}).",
        ]
        if overdue:
            parts.append(f"{overdue} item(s) completed late or overdue.")
        elif open_cnt:
            parts.append(f"{open_cnt} still open.")
        out[eid] = ' '.join(parts)
    return out
