"""AI-driven lead pipeline forecasting (OpenAI + deterministic features)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Max, Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.crm.models import CrmLeadKanbanStage, Customer
from apps.crm.utils import (
    filter_customers_for_user,
    get_sales_employee_queryset,
    salesperson_display_name,
)
from apps.hr.models import Employee
from apps.inventory.utils import get_openai_api_key, is_ai_available
from apps.sales.models import Estimate
from apps.settings_app.models import AuditLog

CACHE_SECONDS = 30 * 60
OPENAI_MODEL = 'gpt-4o-mini'
HISTORY_MONTHS = 12

STAGE_STUCK_DAYS = {
    'hot': 14,
    'warm': 21,
    'cold': 45,
}

SOURCE_KEYWORDS = (
    ('facebook', 'Facebook'),
    ('whatsapp', 'WhatsApp'),
    ('google', 'Google'),
    ('reference', 'Reference'),
    ('referral', 'Reference'),
    ('physical', 'Physical'),
    ('walk-in', 'Physical'),
    ('walk in', 'Physical'),
)

SYSTEM_PROMPT_LEAD_LEVEL = """You are a sales pipeline analyst for a UAE fire & safety contracting company.
Input: active leads with features, salesperson historical stats, and 12-month context.
Return JSON: {"leads": [{"lead_id": <int>, "win_probability": 0-100, "predicted_outcome": "Win"|"Loss"|"Stalled",
"predicted_close_date": "DD/MM/YYYY", "top_factor": "<one short sentence>", "ai_action": "<one short actionable sentence>", "confidence": 0.0-1.0}]}

Rules:
- Heavily weight salesperson's historical conversion rate for that source/stage
- Stuck in stage (Hot >14d, Warm >21d, Cold >45d) → reduce win probability
- No activity 7+ days → reduce confidence, suggest follow-up
- High-value leads with active follow-up + Hot stage → high probability
- Be honest about Loss/Stalled — don't inflate predictions
- Predicted close date based on salesperson avg days-to-close for similar leads
"""

SYSTEM_PROMPT_SALESPERSON = """You are a sales performance analyst for a UAE fire & safety ERP.
Input: salesperson pipeline stats with historical conversion data.
Return JSON: {"salespeople": [{"employee_id": <int>, "predicted_conversions": <float>, "ai_verdict": "<one short sentence>"}]}
Base verdicts on real conversion rates and trends — identify top performers and those slipping."""

SYSTEM_PROMPT_ANOMALIES = """You are a CRM anomaly analyst for a UAE fire & safety ERP.
Input: lead features, stage history, and historical context.
Return JSON: {"anomalies": [{"category": "<Stuck Leads|Stage Skip Anomaly|Reassignment Pattern|Source Performance Shift|Salesperson Slump|Underutilized High-Value Leads|Duplicate Lead Detection|Lost Reason Clustering>", "severity": "high"|"medium", "lead_id": <int|null>, "salesperson_label": "<name or empty>", "description": "<one line>", "suggested_action": "<one line>"}]}
Only include genuine anomalies supported by data. Empty array if none."""

SYSTEM_PROMPT_NEXT_MONTH = """You are forecasting next month's sales pipeline for a UAE fire & safety ERP.
Input: current pipeline snapshot, 12 months historical lead data, salesperson capacity.
Output JSON:
{
  "expected_new_leads": <int>,
  "expected_conversions": <int>,
  "expected_pipeline_value_won_aed": <float>,
  "expected_losses": <int>,
  "value_low_aed": <float>,
  "value_high_aed": <float>,
  "confidence_pct": <int>,
  "key_assumptions": ["..."],
  "risks": ["..."]
}
Base on actual historical velocity and current pipeline. Do not extrapolate optimistically."""

SYSTEM_PROMPT_BRIEF = """You are a sales pipeline analyst for a UAE fire & safety contractor.
Given forecast results (summary, lead predictions, salesperson verdicts, anomalies, next month), return JSON:
{"brief": "<5-7 lines plain English executive summary>"}
Mention salesperson names, AED amounts, lead counts. No bullet points."""


class OpenAINotConfigured(Exception):
    pass


def _decimal(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_openai_json(content: str) -> dict | list:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def _call_openai(*, system: str, user_payload: dict | list, temperature: float = 0.25) -> dict | list:
    from apps.core.openai_gateway import call_openai_json

    try:
        return call_openai_json(
            system=system,
            user_payload=user_payload,
            temperature=temperature,
            feature='lead_forecasting',
        )
    except Exception as exc:
        if exc.__class__.__name__ == 'OpenAINotConfigured':
            raise OpenAINotConfigured('Configure OpenAI API key — set OPENAI_API_KEY in .env') from exc
        raise


def _infer_lead_source(lead: Customer) -> str:
    haystack = ' '.join(
        filter(
            None,
            [
                (lead.notes or '').lower(),
                (lead.company or '').lower(),
            ],
        )
    )
    for keyword, label in SOURCE_KEYWORDS:
        if keyword in haystack:
            return label
    if lead.public_uploads.filter(is_active=True).exists():
        return 'Public Form'
    return 'Not recorded'


def _stage_slug(lead: Customer) -> str:
    if lead.lead_kanban_stage_id:
        return lead.lead_kanban_stage.slug or lead.lead_kanban_stage.name.lower()
    return 'unassigned'


def _stage_name(lead: Customer) -> str:
    if lead.lead_kanban_stage_id:
        return lead.lead_kanban_stage.name
    return 'Unassigned'


def _latest_estimate(lead: Customer) -> Estimate | None:
    return (
        Estimate.objects.filter(customer=lead, is_active=True)
        .order_by('-date', '-created_at')
        .first()
    )


def _lead_estimated_value(lead: Customer) -> float:
    est = _latest_estimate(lead)
    return _decimal(est.total_amount) if est else 0.0


def _stage_transitions(lead: Customer, *, limit: int = 20) -> list[dict]:
    logs = (
        AuditLog.objects.filter(model='Customer', record_id=str(lead.pk))
        .order_by('-timestamp')[: limit * 3]
    )
    transitions = []
    for log in logs:
        changes = log.changes or {}
        if 'lead_kanban_stage' not in changes:
            continue
        val = changes['lead_kanban_stage']
        if isinstance(val, dict):
            val = val.get('new', val)
        transitions.append(
            {
                'at': timezone.localtime(log.timestamp).isoformat(),
                'stage': val,
            }
        )
        if len(transitions) >= limit:
            break
    return list(reversed(transitions))


def _days_in_current_stage(lead: Customer, today: date) -> int | None:
    transitions = _stage_transitions(lead, limit=1)
    if transitions:
        try:
            last_at = date.fromisoformat(transitions[-1]['at'][:10])
            return max(0, (today - last_at).days)
        except (ValueError, TypeError):
            pass
    if lead.updated_at:
        return max(0, (today - timezone.localtime(lead.updated_at).date()).days)
    if lead.created_at:
        return max(0, (today - timezone.localtime(lead.created_at).date()).days)
    return None


def _last_activity_days_ago(lead: Customer, today: date) -> int | None:
    candidates = []
    if lead.updated_at:
        candidates.append(timezone.localtime(lead.updated_at).date())
    est = _latest_estimate(lead)
    if est and est.updated_at:
        candidates.append(timezone.localtime(est.updated_at).date())
    upload = lead.public_uploads.filter(is_active=True).order_by('-created_at').first()
    if upload:
        candidates.append(timezone.localtime(upload.created_at).date())
    if not candidates:
        return None
    last = max(candidates)
    return max(0, (today - last).days)


def _conversion_audit_qs(since: date, until: date):
    return AuditLog.objects.filter(
        model='Customer',
        timestamp__date__gte=since,
        timestamp__date__lte=until,
    ).filter(
        Q(changes__action='kanban_won')
        | Q(changes__converted_to_customer=True)
        | Q(changes__action='converted_to_customer')
    )


def _converted_lead_ids(since: date, until: date) -> set[int]:
    ids = set()
    for log in _conversion_audit_qs(since, until).only('record_id', 'changes'):
        try:
            ids.add(int(log.record_id))
        except (TypeError, ValueError):
            pass
    return ids


def _lost_lead_ids(since: date, until: date) -> set[int]:
    lost_stage = CrmLeadKanbanStage.objects.filter(slug='lost', is_active=True).first()
    if not lost_stage:
        return set()
    ids = set()
    logs = AuditLog.objects.filter(
        model='Customer',
        timestamp__date__gte=since,
        timestamp__date__lte=until,
    )
    for log in logs.only('record_id', 'changes'):
        ch = log.changes or {}
        stage_val = ch.get('lead_kanban_stage')
        if stage_val in ('lost', lost_stage.slug):
            try:
                ids.add(int(log.record_id))
            except (TypeError, ValueError):
                pass
    return ids


def get_forecast_leads_queryset(
    *,
    start_date: date,
    end_date: date,
    stage: str = '',
    salesperson: str = '',
    source: str = '',
    user=None,
):
    """Active pipeline leads for the report window."""
    qs = (
        Customer.objects.filter(is_active=True, customer_type='lead')
        .exclude(lead_kanban_stage__slug='lost')
        .select_related('lead_kanban_stage', 'assigned_salesperson', 'assigned_salesperson__user')
    )
    if user:
        qs = filter_customers_for_user(qs, user)

    qs = qs.filter(
        Q(created_at__date__lte=end_date)
        & (
            Q(created_at__date__gte=start_date)
            | Q(updated_at__date__gte=start_date, updated_at__date__lte=end_date)
        )
    )

    if salesperson == 'none':
        qs = qs.filter(assigned_salesperson__isnull=True)
    elif salesperson:
        try:
            qs = qs.filter(assigned_salesperson_id=int(salesperson))
        except (TypeError, ValueError):
            pass

    if stage == 'unassigned':
        qs = qs.filter(lead_kanban_stage__isnull=True)
    elif stage:
        try:
            qs = qs.filter(lead_kanban_stage_id=int(stage))
        except (TypeError, ValueError):
            pass

    leads = list(qs.order_by('-created_at'))
    if source:
        source_lower = source.lower()
        leads = [l for l in leads if _infer_lead_source(l).lower() == source_lower]
    return leads


def build_lead_features(lead: Customer, *, today: date | None = None) -> dict[str, Any]:
    today = today or timezone.localdate()
    slug = _stage_slug(lead)
    days_in_stage = _days_in_current_stage(lead, today)
    last_activity = _last_activity_days_ago(lead, today)
    est = _latest_estimate(lead)
    sp = lead.assigned_salesperson

    return {
        'lead_id': lead.pk,
        'name': lead.display_name or lead.name or lead.customer_number,
        'customer_number': lead.customer_number,
        'salesperson_id': sp.pk if sp else None,
        'salesperson': salesperson_display_name(sp) if sp else 'Unassigned',
        'source': _infer_lead_source(lead),
        'stage': slug,
        'stage_label': _stage_name(lead),
        'status': lead.status,
        'created_days_ago': max(0, (today - timezone.localtime(lead.created_at).date()).days)
        if lead.created_at
        else None,
        'days_in_current_stage': days_in_stage,
        'stage_transitions': _stage_transitions(lead),
        'last_activity_days_ago': last_activity,
        'estimated_value': _lead_estimated_value(lead),
        'job_type': lead.job_type_display_labels,
        'scope': lead.scope_display_label,
        'has_estimate': est is not None,
        'estimate_value': _decimal(est.total_amount) if est else 0.0,
        'estimate_status': est.status if est else '',
        'notes_excerpt': (lead.notes or '')[:200],
    }


def build_salesperson_features(
    employee: Employee,
    *,
    period_start: date,
    period_end: date,
    today: date,
) -> dict[str, Any]:
    hist_start = period_end - timedelta(days=HISTORY_MONTHS * 31)
    prev_start = period_start - (period_end - period_start) - timedelta(days=1)
    prev_end = period_start - timedelta(days=1)

    assigned_hist = Customer.objects.filter(
        assigned_salesperson=employee,
        is_active=True,
        created_at__date__gte=hist_start,
        created_at__date__lte=period_end,
    )
    lead_ids = set(assigned_hist.values_list('pk', flat=True))
    converted = _converted_lead_ids(hist_start, period_end) & lead_ids
    lost = _lost_lead_ids(hist_start, period_end) & lead_ids

    total_hist = assigned_hist.filter(customer_type='lead').count() + len(converted)
    conv_rate = round(len(converted) / total_hist * 100, 1) if total_hist else 0.0

    prev_assigned = Customer.objects.filter(
        assigned_salesperson=employee,
        created_at__date__gte=prev_start,
        created_at__date__lte=prev_end,
    )
    prev_ids = set(prev_assigned.values_list('pk', flat=True))
    prev_converted = _converted_lead_ids(prev_start, prev_end) & prev_ids
    prev_total = prev_assigned.count() + len(prev_converted)
    prev_rate = len(prev_converted) / prev_total * 100 if prev_total else 0.0

    trend_pct = round(conv_rate - prev_rate, 1) if prev_total else 0.0
    if trend_pct > 2:
        trend = 'up'
    elif trend_pct < -2:
        trend = 'down'
    else:
        trend = 'flat'

    # Best source by conversion
    source_stats: dict[str, dict] = {}
    for lead in assigned_hist.filter(customer_type='lead').iterator():
        src = _infer_lead_source(lead)
        source_stats.setdefault(src, {'total': 0, 'won': 0})
        source_stats[src]['total'] += 1
        if lead.pk in converted:
            source_stats[src]['won'] += 1
    best_source = '—'
    best_rate = -1.0
    for src, st in source_stats.items():
        if st['total'] >= 2:
            rate = st['won'] / st['total']
            if rate > best_rate:
                best_rate = rate
                best_source = src

    deal_values = []
    for lid in converted:
        lead = Customer.objects.filter(pk=lid).first()
        if lead:
            val = _lead_estimated_value(lead)
            if val > 0:
                deal_values.append(val)
    avg_deal = round(sum(deal_values) / len(deal_values), 0) if deal_values else 0.0

    active = Customer.objects.filter(
        assigned_salesperson=employee,
        customer_type='lead',
        is_active=True,
    ).exclude(lead_kanban_stage__slug='lost').count()

    return {
        'employee_id': employee.pk,
        'user': employee.user.username if employee.user_id else employee.employee_code,
        'label': salesperson_display_name(employee),
        'active_leads': active,
        'leads_won_12mo': len(converted),
        'leads_lost_12mo': len(lost),
        'conversion_rate_12mo': conv_rate,
        'conversion_rate_prev_period': round(prev_rate, 1),
        'trend': trend,
        'trend_pct': trend_pct,
        'avg_deal_size': avg_deal,
        'best_source': best_source,
        'avg_days_to_close': 30,
    }


def build_historical_summary(*, end_date: date) -> dict[str, Any]:
    since = end_date - timedelta(days=HISTORY_MONTHS * 31)
    leads_created = Customer.objects.filter(
        customer_type='lead',
        created_at__date__gte=since,
        created_at__date__lte=end_date,
    ).count()
    converted = len(_converted_lead_ids(since, end_date))
    lost = len(_lost_lead_ids(since, end_date))

    by_month = []
    cursor = since.replace(day=1)
    while cursor <= end_date:
        month_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if month_end > end_date:
            month_end = end_date
        cnt = Customer.objects.filter(
            customer_type='lead',
            created_at__date__gte=cursor,
            created_at__date__lte=month_end,
        ).count()
        conv = len(_converted_lead_ids(cursor, month_end))
        by_month.append({'month': cursor.strftime('%Y-%m'), 'new_leads': cnt, 'conversions': conv})
        cursor = month_end + timedelta(days=1)

    source_totals: dict[str, int] = {}
    for lead in Customer.objects.filter(
        customer_type='lead',
        created_at__date__gte=since,
        created_at__date__lte=end_date,
    ).iterator():
        src = _infer_lead_source(lead)
        source_totals[src] = source_totals.get(src, 0) + 1

    return {
        'months': HISTORY_MONTHS,
        'since': since.isoformat(),
        'until': end_date.isoformat(),
        'leads_created': leads_created,
        'conversions': converted,
        'losses': lost,
        'conversion_rate_pct': round(converted / leads_created * 100, 1) if leads_created else 0.0,
        'by_month': by_month,
        'source_totals': source_totals,
    }


def _heuristic_lead_prediction(f: dict, sp_map: dict[int, dict]) -> dict:
    slug = (f.get('stage') or 'unassigned').lower()
    base = {'hot': 68, 'warm': 48, 'cold': 28, 'unassigned': 35}.get(slug, 35)
    days = f.get('days_in_current_stage') or 0
    stuck_limit = STAGE_STUCK_DAYS.get(slug, 30)
    if days > stuck_limit:
        base -= min(25, (days - stuck_limit))

    inactive = f.get('last_activity_days_ago')
    if inactive is not None and inactive >= 7:
        base -= min(20, inactive // 2)

    if f.get('has_estimate'):
        base += 8
    if f.get('estimated_value', 0) >= 50000:
        base += 5

    sp_id = f.get('salesperson_id')
    if sp_id and sp_id in sp_map:
        rate = sp_map[sp_id].get('conversion_rate_12mo', 0)
        base += int((rate - 20) / 5)

    win_prob = max(5, min(92, base))
    if win_prob >= 55:
        outcome = 'Win'
    elif win_prob >= 30 and (inactive or 0) < 14:
        outcome = 'Stalled'
    else:
        outcome = 'Loss'

    close_days = 21 if slug == 'hot' else 45 if slug == 'warm' else 60
    close_date = timezone.localdate() + timedelta(days=close_days)

    reasons = []
    if days > stuck_limit:
        reasons.append(f'{f.get("stage_label", slug)} stage {days} days — stalled')
    if inactive and inactive >= 7:
        reasons.append(f'No activity {inactive} days')
    if f.get('has_estimate') and slug == 'hot':
        reasons.append('Hot lead with active estimate')
    if not reasons:
        reasons.append('Pipeline progressing normally')

    actions = {
        'Win': 'Push to estimation and close this week',
        'Stalled': 'Schedule follow-up call within 48 hours',
        'Loss': 'Confirm status or mark Lost if no response',
    }

    return {
        'lead_id': f['lead_id'],
        'win_probability': win_prob,
        'predicted_outcome': outcome,
        'predicted_close_date': close_date.strftime('%d/%m/%Y'),
        'top_factor': reasons[0],
        'ai_action': actions[outcome],
        'confidence': 0.55,
    }


def _heuristic_sp_verdict(sp: dict) -> dict:
    rate = sp.get('conversion_rate_12mo', 0)
    trend = sp.get('trend', 'flat')
    active = sp.get('active_leads', 0)
    predicted = round(active * rate / 100 * 0.4, 1) if active else 0.0

    if rate >= 40 and trend == 'up':
        verdict = 'Top performer — assign hot leads'
    elif trend == 'down' and sp.get('trend_pct', 0) <= -10:
        verdict = 'Slipping — coach on follow-ups'
    elif sp.get('best_source') and sp.get('best_source') != '—':
        verdict = f"Strong on {sp['best_source']} leads"
    else:
        verdict = 'Steady pipeline — maintain cadence'

    return {
        'employee_id': sp['employee_id'],
        'predicted_conversions': predicted,
        'ai_verdict': verdict,
    }


def _heuristic_next_month(
    leads: list[dict],
    historical: dict,
    summary: dict,
) -> dict:
    hist_conv = historical.get('conversion_rate_pct', 15) / 100
    active_count = len(leads)
    avg_value = (
        sum(l.get('estimated_value', 0) for l in leads) / active_count if active_count else 0
    )
    monthly_new = historical.get('leads_created', 0) // max(HISTORY_MONTHS, 1)
    expected_conv = max(1, round(active_count * hist_conv * 0.35))
    value_won = expected_conv * avg_value if avg_value else expected_conv * 25000

    return {
        'expected_new_leads': monthly_new,
        'expected_conversions': expected_conv,
        'expected_pipeline_value_won_aed': round(value_won, 0),
        'expected_losses': max(0, round(active_count * 0.15)),
        'value_low_aed': round(value_won * 0.75, 0),
        'value_high_aed': round(value_won * 1.35, 0),
        'confidence_pct': 65,
        'key_assumptions': [
            f'Historical conversion rate {historical.get("conversion_rate_pct", 0):.0f}% applied to active pipeline',
            f'{active_count} active leads in current filter set',
        ],
        'risks': ['Inactive leads may convert to Lost without follow-up'],
    }


def _deterministic_anomalies(features: list[dict], historical: dict) -> list[dict]:
    anomalies = []
    seen_phones: dict[str, list] = {}
    seen_emails: dict[str, list] = {}

    for f in features:
        lid = f['lead_id']
        slug = (f.get('stage') or '').lower()
        days = f.get('days_in_current_stage') or 0
        limit = STAGE_STUCK_DAYS.get(slug)
        if limit and days > limit:
            anomalies.append(
                {
                    'category': 'Stuck Leads',
                    'severity': 'high' if days > limit * 1.5 else 'medium',
                    'lead_id': lid,
                    'salesperson_label': f.get('salesperson', ''),
                    'description': (
                        f"{f['name']}: {f.get('stage_label', slug)} for {days} days "
                        f"(threshold {limit}d)"
                    ),
                    'suggested_action': 'Schedule follow-up or advance stage',
                }
            )

        val = f.get('estimated_value') or 0
        inactive = f.get('last_activity_days_ago')
        if val >= 30000 and inactive is not None and inactive >= 7:
            anomalies.append(
                {
                    'category': 'Underutilized High-Value Leads',
                    'severity': 'high',
                    'lead_id': lid,
                    'salesperson_label': f.get('salesperson', ''),
                    'description': f"AED {val:,.0f} lead inactive {inactive} days",
                    'suggested_action': 'Priority call and site visit',
                }
            )

        transitions = f.get('stage_transitions') or []
        if len(transitions) >= 2:
            stages = [t.get('stage') for t in transitions]
            if 'won' in stages and 'cold' in stages and stages.index('won') - stages.index('cold') == 1:
                anomalies.append(
                    {
                        'category': 'Stage Skip Anomaly',
                        'severity': 'medium',
                        'lead_id': lid,
                        'salesperson_label': f.get('salesperson', ''),
                        'description': f"Lead jumped Cold → Won ({f['name']})",
                        'suggested_action': 'Verify conversion data accuracy',
                    }
                )

    # Duplicate detection from Customer records
    for lead in Customer.objects.filter(
        pk__in=[f['lead_id'] for f in features],
        customer_type='lead',
    ).only('pk', 'phone', 'email', 'company', 'name'):
        if lead.phone:
            key = re.sub(r'\D', '', lead.phone)[-9:]
            if len(key) >= 7:
                seen_phones.setdefault(key, []).append(lead)
        if lead.email:
            seen_emails.setdefault(lead.email.lower(), []).append(lead)

    for bucket in list(seen_phones.values()) + list(seen_emails.values()):
        if len(bucket) > 1:
            for dup in bucket[1:]:
                anomalies.append(
                    {
                        'category': 'Duplicate Lead Detection',
                        'severity': 'medium',
                        'lead_id': dup.pk,
                        'salesperson_label': '',
                        'description': f'Possible duplicate of {bucket[0].customer_number}',
                        'suggested_action': 'Merge or mark duplicate records',
                    }
                )

    # Lost reason clustering from lost-stage leads in history
    lost_stage = CrmLeadKanbanStage.objects.filter(slug='lost').first()
    if lost_stage:
        lost_leads = Customer.objects.filter(
            customer_type='lead',
            lead_kanban_stage=lost_stage,
        ).exclude(notes='')[:50]
        if lost_leads.exists():
            reason = 'No response / moved to Lost'
            anomalies.append(
                {
                    'category': 'Lost Reason Clustering',
                    'severity': 'medium',
                    'lead_id': None,
                    'salesperson_label': '',
                    'description': f'{lost_leads.count()} leads in Lost stage — top reason: {reason}',
                    'suggested_action': 'Review lost leads for recoverable opportunities',
                }
            )

    return anomalies[:30]


def _summary_from_predictions(
    lead_rows: list[dict],
    next_month: dict,
) -> dict:
    wins = [r for r in lead_rows if r.get('predicted_outcome') == 'Win']
    losses = [r for r in lead_rows if r.get('predicted_outcome') == 'Loss']
    confidences = [float(r.get('confidence', 0.5)) for r in lead_rows if r.get('confidence') is not None]
    pipeline_won = sum(
        (r.get('estimated_value') or 0) * (r.get('win_probability', 0) / 100)
        for r in lead_rows
    )
    return {
        'predicted_conversions': len(wins),
        'predicted_pipeline_value_won': round(pipeline_won, 0),
        'predicted_loss_count': len(losses),
        'avg_confidence': round(sum(confidences) / len(confidences), 2) if confidences else 0.0,
        'avg_confidence_pct': int(round((sum(confidences) / len(confidences) * 100) if confidences else 0)),
    }


def _merge_lead_predictions(
    features: list[dict], predictions: list[dict], sp_map: dict | None = None
) -> list[dict]:
    sp_map = sp_map or {}
    by_id = {p.get('lead_id'): p for p in predictions if p.get('lead_id') is not None}
    rows = []
    for f in features:
        pred = by_id.get(f['lead_id']) or _heuristic_lead_prediction(f, sp_map)
        prob = pred.get('win_probability', 0)
        if prob > 70:
            row_class = 'high'
        elif prob >= 40:
            row_class = 'mid'
        else:
            row_class = 'low'
        rows.append(
            {
                **pred,
                'lead_name': f['name'],
                'customer_number': f['customer_number'],
                'salesperson': f.get('salesperson', '—'),
                'stage_label': f.get('stage_label', '—'),
                'days_in_stage': f.get('days_in_current_stage'),
                'estimated_value': f.get('estimated_value', 0),
                'source': f.get('source', ''),
                'row_class': row_class,
                'detail_url': reverse('crm:customer_detail', args=[f['lead_id']]),
            }
        )
    rows.sort(key=lambda r: r.get('win_probability', 0), reverse=True)
    return rows


def _merge_sp_rows(sp_features: list[dict], verdicts: list[dict]) -> list[dict]:
    by_id = {v.get('employee_id'): v for v in verdicts if v.get('employee_id')}
    rows = []
    for sp in sp_features:
        v = by_id.get(sp['employee_id']) or _heuristic_sp_verdict(sp)
        trend = sp.get('trend', 'flat')
        trend_pct = sp.get('trend_pct', 0)
        if trend == 'up':
            trend_display = f'↑ {abs(trend_pct):.0f}%'
            trend_class = 'text-success'
        elif trend == 'down':
            trend_display = f'↓ {abs(trend_pct):.0f}%'
            trend_class = 'text-danger'
        else:
            trend_display = f'→ {abs(trend_pct):.0f}%'
            trend_class = 'text-muted'

        rows.append(
            {
                **sp,
                'predicted_conversions': v.get('predicted_conversions', 0),
                'ai_verdict': v.get('ai_verdict', ''),
                'conversion_rate_display': f"{sp.get('conversion_rate_12mo', 0):.1f}%",
                'avg_deal_display': f"AED {sp.get('avg_deal_size', 0):,.0f}",
                'trend_display': trend_display,
                'trend_class': trend_class,
            }
        )
    rows.sort(key=lambda r: float(r.get('predicted_conversions') or 0), reverse=True)
    return rows


def _leads_data_version(leads: list[Customer]) -> str:
    if not leads:
        return '0'
    ids = [l.pk for l in leads]
    agg = Customer.objects.filter(pk__in=ids).aggregate(m=Max('updated_at'))
    ts = agg.get('m')
    return ts.isoformat() if ts else '0'


def _cache_key(filters: dict, lead_ids: list[int], data_version: str) -> str:
    raw = json.dumps({'filters': filters, 'leads': lead_ids, 'version': data_version}, sort_keys=True)
    return 'lead_forecast:' + hashlib.sha256(raw.encode()).hexdigest()


def forecast_leads(
    leads: list[Customer],
    *,
    start_date: date,
    end_date: date,
    filters: dict | None = None,
    force_refresh: bool = False,
    regenerate_brief: bool = False,
) -> dict[str, Any]:
    filters = filters or {}
    today = timezone.localdate()
    features = [build_lead_features(l, today=today) for l in leads]
    lead_ids = [l.pk for l in leads]
    data_version = _leads_data_version(leads)

    cache_key = _cache_key(filters, lead_ids, data_version)
    brief_key = cache_key + ':brief'

    cached = None if force_refresh else cache.get(cache_key)
    if cached and not force_refresh and not regenerate_brief:
        cached['from_cache'] = True
        return cached

    ai_used = False
    ai_error = ''

    if cached and regenerate_brief and not force_refresh:
        lead_rows = cached.get('lead_rows') or []
        sp_rows = cached.get('sp_rows') or []
        summary = cached.get('summary') or {}
        next_month = cached.get('next_month') or {}
        anomalies = cached.get('anomalies') or []
        historical = cached.get('historical') or {}
        features = cached.get('features') or features
        ai_used = cached.get('ai_used', False)
        ai_error = cached.get('ai_error', '')
    else:
        cached = None
        historical = build_historical_summary(end_date=end_date)

        employee_ids = {l.assigned_salesperson_id for l in leads if l.assigned_salesperson_id}
        for emp in get_sales_employee_queryset():
            if emp.pk in employee_ids or emp.assigned_crm_leads.filter(customer_type='lead').exists():
                employee_ids.add(emp.pk)

        sp_features = []
        for eid in employee_ids:
            emp = Employee.objects.filter(pk=eid).select_related('user').first()
            if emp:
                sp_features.append(
                    build_salesperson_features(
                        emp, period_start=start_date, period_end=end_date, today=today
                    )
                )

        sp_map = {s['employee_id']: s for s in sp_features}

        # AI call 1: lead predictions
        lead_preds: list[dict] = []
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_LEAD_LEVEL,
                user_payload={
                    'leads': features,
                    'salesperson_stats': sp_features,
                    'historical_context': historical,
                },
            )
            if isinstance(resp, dict):
                lead_preds = resp.get('leads') or resp.get('items') or []
            ai_used = True
        except OpenAINotConfigured as exc:
            ai_error = str(exc)
            lead_preds = [_heuristic_lead_prediction(f, sp_map) for f in features]
        except Exception as exc:
            ai_error = str(exc)[:300]
            lead_preds = [_heuristic_lead_prediction(f, sp_map) for f in features]

        if not lead_preds:
            lead_preds = [_heuristic_lead_prediction(f, sp_map) for f in features]

        lead_rows = _merge_lead_predictions(features, lead_preds, sp_map)

        # AI call 2: salesperson verdicts
        sp_verdicts: list[dict] = []
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_SALESPERSON,
                user_payload={'salespeople': sp_features, 'historical_context': historical},
            )
            if isinstance(resp, dict):
                sp_verdicts = resp.get('salespeople') or resp.get('items') or []
            ai_used = True
        except Exception:
            sp_verdicts = [_heuristic_sp_verdict(s) for s in sp_features]

        sp_rows = _merge_sp_rows(sp_features, sp_verdicts)

        summary = _summary_from_predictions(lead_rows, {})

        # AI call 3: anomalies
        anomalies = _deterministic_anomalies(features, historical)
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_ANOMALIES,
                user_payload={'leads': features, 'historical_context': historical},
            )
            if isinstance(resp, dict):
                ai_anomalies = resp.get('anomalies') or []
                seen = {(a.get('lead_id'), a.get('category')) for a in anomalies}
                for a in ai_anomalies:
                    key = (a.get('lead_id'), a.get('category'))
                    if key not in seen:
                        anomalies.append(a)
                        seen.add(key)
            ai_used = True
        except Exception:
            pass

        # AI call 4: next month
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_NEXT_MONTH,
                user_payload={
                    'pipeline': features,
                    'summary': summary,
                    'historical_context': historical,
                    'salespeople': sp_features,
                },
            )
            next_month = resp if isinstance(resp, dict) else {}
            ai_used = True
        except Exception:
            next_month = _heuristic_next_month(features, historical, summary)

        if not next_month:
            next_month = _heuristic_next_month(features, historical, summary)

        ai_used = ai_used or False
        ai_error = ai_error or ''

    # AI call 5: executive brief
    brief = ''
    if regenerate_brief or force_refresh or not cache.get(brief_key):
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_BRIEF,
                user_payload={
                    'summary': summary,
                    'lead_rows': lead_rows[:20],
                    'sp_rows': sp_rows,
                    'anomalies': anomalies[:10],
                    'next_month': next_month,
                },
                temperature=0.4,
            )
            if isinstance(resp, dict):
                brief = resp.get('brief') or resp.get('summary') or ''
            ai_used = True
        except Exception as exc:
            brief = _heuristic_brief(lead_rows, sp_rows, summary, ai_error or str(exc))
    else:
        brief = cache.get(brief_key) or ''

    if not brief:
        brief = _heuristic_brief(lead_rows, sp_rows, summary, ai_error)

    for a in anomalies:
        lid = a.get('lead_id')
        if lid and not a.get('detail_url'):
            a['detail_url'] = reverse('crm:customer_detail', args=[lid])

    result = {
        'features': features,
        'lead_rows': lead_rows,
        'sp_rows': sp_rows,
        'summary': summary,
        'next_month': next_month,
        'anomalies': anomalies,
        'historical': historical,
        'executive_brief': brief.strip(),
        'ai_used': ai_used,
        'ai_error': ai_error,
        'from_cache': False,
        'generated_at': timezone.now(),
    }
    cache.set(cache_key, result, CACHE_SECONDS)
    cache.set(brief_key, result['executive_brief'], CACHE_SECONDS)
    return result


def _heuristic_brief(
    lead_rows: list[dict],
    sp_rows: list[dict],
    summary: dict,
    note: str = '',
) -> str:
    parts = []
    if note and 'Configure OpenAI' in note:
        parts.append(
            'AI brief unavailable — set OPENAI_API_KEY in .env for richer insights.'
        )
    parts.append(
        f"Forecast: {summary.get('predicted_conversions', 0)} likely conversions worth "
        f"AED {summary.get('predicted_pipeline_value_won', 0):,.0f}, "
        f"{summary.get('predicted_loss_count', 0)} at risk of Loss."
    )
    if sp_rows:
        top = sp_rows[0]
        parts.append(
            f"{top.get('label', 'Top rep')} leads with {top.get('predicted_conversions', 0)} "
            f"predicted conversions — {top.get('ai_verdict', '')}."
        )
    hot = [r for r in lead_rows if r.get('win_probability', 0) >= 70]
    if hot:
        parts.append(f"{len(hot)} high-probability leads need immediate follow-up.")
    elif lead_rows:
        parts.append(f"Watch {lead_rows[0].get('lead_name', 'top lead')}: {lead_rows[0].get('top_factor', '')}.")
    return ' '.join(p for p in parts if p)


def filter_choice_stages() -> list[dict]:
    stages = CrmLeadKanbanStage.objects.filter(is_active=True, converts_to_customer=False).order_by(
        'sort_order', 'id'
    )
    return [{'id': s.pk, 'label': s.name, 'slug': s.slug} for s in stages]


def filter_choice_sources(leads: list[Customer]) -> list[dict]:
    seen = {}
    for lead in leads:
        src = _infer_lead_source(lead)
        seen[src] = seen.get(src, 0) + 1
    return [{'id': k, 'label': k, 'count': v} for k, v in sorted(seen.items(), key=lambda x: (-x[1], x[0]))]


def build_lead_forecast_report_context(
    *,
    start_date: date,
    end_date: date,
    stage: str,
    salesperson: str,
    source: str,
    user=None,
    force_refresh: bool = False,
    regenerate_brief: bool = False,
) -> dict[str, Any]:
    all_leads = get_forecast_leads_queryset(
        start_date=start_date,
        end_date=end_date,
        stage='',
        salesperson='',
        source='',
        user=user,
    )
    leads = get_forecast_leads_queryset(
        start_date=start_date,
        end_date=end_date,
        stage=stage,
        salesperson=salesperson,
        source=source,
        user=user,
    )
    filters = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'stage': stage,
        'salesperson': salesperson,
        'source': source,
    }
    analysis = forecast_leads(
        leads,
        start_date=start_date,
        end_date=end_date,
        filters=filters,
        force_refresh=force_refresh,
        regenerate_brief=regenerate_brief,
    )
    salespeople = [
        {'id': emp.pk, 'label': salesperson_display_name(emp)}
        for emp in get_sales_employee_queryset()
    ]
    return {
        'start_date': start_date,
        'end_date': end_date,
        'stage_filter': stage,
        'salesperson_filter': salesperson,
        'source_filter': source,
        'stage_choices': [{'id': '', 'label': 'All stages'}]
        + [{'id': 'unassigned', 'label': 'Unassigned'}]
        + [{'id': str(s['id']), 'label': s['label']} for s in filter_choice_stages()],
        'salesperson_choices': salespeople,
        'source_choices': [{'id': '', 'label': 'All sources'}]
        + [{'id': s['id'], 'label': f"{s['label']} ({s['count']})"} for s in filter_choice_sources(all_leads)],
        'lead_count': len(leads),
        'openai_configured': is_ai_available(),
        **analysis,
    }
