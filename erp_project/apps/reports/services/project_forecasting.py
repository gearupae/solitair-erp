"""AI-driven project risk forecasting (OpenAI + deterministic features)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.db.models import Max, Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.hr.models_extended import AttendanceRecord
from apps.inventory.models import ConsumableRequest
from apps.inventory.utils import get_openai_api_key
from apps.projects.models import (
    Project,
    ProjectExpense,
    ProjectItemDelivery,
    ProjectItemLine,
    Task,
)
from apps.sales.models import Estimate, Invoice

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30 * 60
OPENAI_MODEL = 'gpt-4o-mini'

FORBIDDEN_INSIGHT_PHRASES = (
    'on track against plan',
    'continue monitoring',
    'no issues detected',
    'metrics within expected ranges',
    'continue with the current plan',
    'maintain momentum',
)

DEFAULT_FORECAST_STATUSES = (
    'planning',
    'ongoing',
    'on_hold',
    'completed',
    'completed_payment_pending',
    'ongoing_payment_received',
)

_ONGOING_STATUSES = frozenset({'ongoing', 'in_progress'})

SYSTEM_PROMPT_RISK = """You are a project risk analyst for a UAE fire & safety contracting ERP.
You receive JSON with key "projects" — feature dicts per active project.
Return JSON: {"projects": [{"code": "<project code>", "risk_level": "red"|"amber"|"green", "confidence": 0.0-1.0,
"predicted_end_date": "DD/MM/YYYY", "delay_days": <int>, "predicted_final_cost": <float|null>,
"cost_overrun_pct": <float|null>, "predicted_margin_pct": <float|null>, "top_risk_reason": "<one short sentence>",
"ai_action": "<one actionable sentence>", "reasoning": "<2-3 sentences>"}]}

RED if any of: In Progress 14+ days with zero spend; predicted cost >15% over budget; time elapsed >50% but tasks <25%;
no activity 14+ days; negative margin forecast; past end date still Planning/In Progress.

AMBER if any of: In Progress 7-14 days no spend; cost 5-15% over budget; time >30% but tasks <50%; no activity 7-14 days;
budget missing; schedule lag.

GREEN only when recent activity (≤7 days), spend/time/tasks aligned, no overrun trajectory.

Forbidden in top_risk_reason and ai_action: "On track against plan", "Continue monitoring", "No issues detected".
Write specific observations from the metrics provided. All currency AED."""

SYSTEM_PROMPT_BRIEF = """You are a project portfolio analyst for a UAE fire & safety contracting ERP.

You receive active projects with: code, name, customer, status, start_date, end_date, days_elapsed, days_remaining,
budget, spent_to_date, burn_rate, task_completion_pct, last_activity_days_ago, expense breakdown, manhours.

Return JSON: {"brief": "<5-8 lines plain English executive brief>"} covering:
1. Overall portfolio health — how many at risk and why
2. Specific projects needing immediate attention — name by code
3. Surprising patterns — in progress with no activity, deadline approaching with low completion
4. Recommended next actions — concrete and specific
5. One positive signal if applicable

Be direct. No filler. Use AED for amounts. Reference project codes ONLY from input. Do not invent codes."""

SYSTEM_PROMPT_ANOMALIES = """You are a project operations analyst for a UAE fire & safety ERP.
Given project feature JSON, return JSON: {"anomalies": [{"category": "<Inactivity|Zero-spend In Progress|Expense Spikes|Budget overrun trajectory|Schedule slip|Manhour Overruns|Vendor Concentration Risk|Late Invoicing|Unusual Item Usage|Stale project>", "severity": "high"|"medium"|"low", "project_code": "<code>", "description": "<one line>", "suggested_action": "<one line>"}]}
Detect all applicable patterns from the data. Return empty array only if truly none."""


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


def _urllib_ssl_context():
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _call_openai(*, system: str, user_payload: dict | list, temperature: float = 0.25, call_label: str = 'openai') -> dict | list:
    api_key = get_openai_api_key()
    if not api_key:
        raise OpenAINotConfigured('OpenAI API key not configured (set OPENAI_API_KEY or save key in Company Settings)')

    import urllib.error
    import urllib.request

    payload_preview = json.dumps(user_payload, default=str)
    logger.info(
        'project_forecasting %s: model=%s payload_bytes=%d',
        call_label,
        OPENAI_MODEL,
        len(payload_preview),
    )

    body = json.dumps(
        {
            'model': OPENAI_MODEL,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': payload_preview},
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
        with urllib.request.urlopen(req, timeout=120, context=_urllib_ssl_context()) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode('utf-8', errors='replace')[:500]
        logger.exception('project_forecasting %s HTTP error %s: %s', call_label, exc.code, err_body)
        raise RuntimeError(f'OpenAI API error ({exc.code}): {err_body}') from exc
    except Exception:
        logger.exception('project_forecasting %s request failed', call_label)
        raise

    content = payload['choices'][0]['message']['content']
    logger.info('project_forecasting %s: success response_bytes=%d', call_label, len(content or ''))
    return _parse_openai_json(content)


def _is_fully_closed(project: Project) -> bool:
    if project.status == 'cancelled':
        return True
    if project.status != 'completed':
        return False
    cv = project.contract_value or Decimal('0')
    billed = project.total_billed or Decimal('0')
    return cv > 0 and billed >= cv


def get_forecast_projects_queryset(
    *,
    start_date: date,
    end_date: date,
    status: str = '',
    manager_id: str = '',
    customer_id: str = '',
):
    """Projects overlapping the filter period and still actionable."""
    qs = (
        Project.objects.filter(is_active=True)
        .exclude(status__in=('draft', 'cancelled'))
        .select_related('customer', 'manager')
        .prefetch_related('members')
    )

    # Overlap with reporting window (same idea as period report).
    qs = qs.filter(
        Q(start_date__isnull=True, created_at__date__lte=end_date)
        | Q(start_date__lte=end_date, end_date__isnull=True)
        | Q(start_date__lte=end_date, end_date__gte=start_date)
    )

    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.filter(status__in=DEFAULT_FORECAST_STATUSES)

    if manager_id:
        try:
            qs = qs.filter(manager_id=int(manager_id))
        except (TypeError, ValueError):
            pass

    if customer_id:
        try:
            qs = qs.filter(customer_id=int(customer_id))
        except (TypeError, ValueError):
            pass

    return [p for p in qs.order_by('project_code') if not _is_fully_closed(p)]


def _task_hours_estimated(project: Project) -> float:
    agg = Task.objects.filter(project=project, is_active=True).aggregate(
        s=Sum('estimated_hours')
    )
    return _decimal(agg['s'])


def _manhours_logged(project: Project, since: date | None = None) -> float:
    qs = AttendanceRecord.objects.filter(project=project, is_active=True)
    if since:
        qs = qs.filter(date__gte=since)
    agg = qs.aggregate(
        wh=Sum('working_hours'),
        ot=Sum('overtime_hours'),
    )
    wh = _decimal(agg['wh'])
    ot = _decimal(agg['ot'])
    return wh + ot


def _last_activity_date(project: Project) -> date | None:
    candidates: list[date] = []

    t = Task.objects.filter(project=project, is_active=True).aggregate(m=Max('updated_at'))
    if t['m']:
        candidates.append(timezone.localtime(t['m']).date())

    e = ProjectExpense.objects.filter(project=project, is_active=True).aggregate(
        m=Max('expense_date')
    )
    if e['m']:
        candidates.append(e['m'])

    d = ProjectItemDelivery.objects.filter(project=project).aggregate(m=Max('delivered_date'))
    if d['m']:
        candidates.append(d['m'])

    a = AttendanceRecord.objects.filter(project=project, is_active=True).aggregate(m=Max('date'))
    if a['m']:
        candidates.append(a['m'])

    c = ConsumableRequest.objects.filter(project=project, is_active=True).aggregate(
        m=Max('created_at')
    )
    if c['m']:
        candidates.append(timezone.localtime(c['m']).date())

    return max(candidates) if candidates else None


def _items_consumed_vs_estimate(project: Project) -> list[dict]:
    lines = list(
        ProjectItemLine.objects.filter(project=project).select_related('inventory_item')
    )
    if not lines:
        return []

    delivered = (
        ProjectItemDelivery.objects.filter(project=project)
        .values('item_id')
        .annotate(qty=Sum('quantity'))
    )
    delivered_map = {r['item_id']: _decimal(r['qty']) for r in delivered if r['item_id']}

    rows = []
    for line in lines:
        if not line.inventory_item_id:
            continue
        est_qty = _decimal(line.quantity)
        used = delivered_map.get(line.inventory_item_id, 0.0)
        if est_qty <= 0:
            continue
        ratio = used / est_qty if est_qty else 0.0
        rows.append(
            {
                'item_code': line.inventory_item.item_code,
                'item_name': line.inventory_item.name,
                'estimate_qty': est_qty,
                'consumed_qty': used,
                'ratio': round(ratio, 2),
            }
        )
    return sorted(rows, key=lambda r: r['ratio'], reverse=True)[:8]


def _recent_expenses(project: Project, limit: int = 5) -> list[dict]:
    qs = (
        ProjectExpense.objects.filter(project=project, is_active=True)
        .exclude(status='rejected')
        .select_related('vendor')
        .order_by('-expense_date')[:limit]
    )
    return [
        {
            'date': e.expense_date.isoformat(),
            'amount': _decimal(e.total_amount or e.amount),
            'category': e.category,
            'vendor': (e.vendor.name if e.vendor_id else '') or e.invoice_reference,
            'status': e.status,
        }
        for e in qs
    ]


def _recent_tasks(project: Project, limit: int = 5) -> list[dict]:
    qs = Task.objects.filter(project=project, is_active=True).order_by('-updated_at')[:limit]
    return [
        {
            'name': t.name,
            'status': t.status,
            'due_date': t.due_date.isoformat() if t.due_date else None,
            'assigned_to': (
                t.assigned_to.get_full_name() or t.assigned_to.username
            )
            if t.assigned_to_id
            else '',
        }
        for t in qs
    ]


def _estimate_original_value(project: Project) -> float:
    est = (
        Estimate.objects.filter(project=project, is_active=True)
        .order_by('-created_at')
        .first()
    )
    if not est and project.customer_id:
        est = (
            Estimate.objects.filter(
                customer=project.customer,
                is_active=True,
                status='quotation_won',
            )
            .order_by('-created_at')
            .first()
        )
    return _decimal(est.total_amount) if est else 0.0


def _vendor_spend_share(project: Project) -> list[dict]:
    qs = (
        ProjectExpense.objects.filter(project=project, is_active=True)
        .exclude(status='rejected')
        .exclude(vendor__isnull=True)
        .values('vendor__name')
        .annotate(total=Sum('total_amount'))
        .order_by('-total')
    )
    total = sum(_decimal(r['total']) for r in qs)
    if total <= 0:
        return []
    return [
        {
            'vendor': r['vendor__name'] or 'Unknown',
            'amount': _decimal(r['total']),
            'share_pct': round(_decimal(r['total']) / total * 100, 1),
        }
        for r in qs[:5]
    ]


def build_project_features(project: Project, *, today: date | None = None) -> dict[str, Any]:
    today = today or timezone.localdate()
    start = project.start_date
    end = project.end_date

    days_total = None
    days_elapsed = None
    pct_time_elapsed = None
    if start:
        days_elapsed = max(0, (today - start).days)
        if end and end >= start:
            days_total = (end - start).days or 1
            pct_time_elapsed = round(min(100.0, days_elapsed / days_total * 100), 1)

    total_tasks = project.tasks.filter(is_active=True).count()
    done_tasks = project.tasks.filter(is_active=True, status='completed').count()
    pct_tasks_done = (
        round(done_tasks / total_tasks * 100, 1) if total_tasks else float(project.task_progress_percent)
    )

    budget = _decimal(project.budget)
    estimated_cost = _decimal(project.estimated_cost or project.budget)
    spent = _decimal(project.total_expenses)
    contract = _decimal(project.contract_value)
    billed = _decimal(project.total_billed)
    revenue = _decimal(project.total_revenue)

    burn_rate_ratio = None
    if estimated_cost > 0 and pct_time_elapsed and pct_time_elapsed > 0:
        spend_pct = spent / estimated_cost * 100
        burn_rate_ratio = round(spend_pct / pct_time_elapsed, 2)

    last_act = _last_activity_date(project)
    days_inactive = (today - last_act).days if last_act else None

    mh_est = _task_hours_estimated(project)
    mh_logged = _manhours_logged(project)

    days_remaining = None
    if end and today <= end:
        days_remaining = (end - today).days
    elif end:
        days_remaining = (today - end).days * -1

    burn_rate_per_day = None
    if days_elapsed and days_elapsed > 0 and spent > 0:
        burn_rate_per_day = round(spent / days_elapsed, 2)

    return {
        'id': project.pk,
        'code': project.project_code,
        'name': project.name,
        'customer': (project.customer.company or project.customer.name) if project.customer_id else '',
        'manager': (
            project.manager.get_full_name() or project.manager.username
        )
        if project.manager_id
        else '',
        'status': project.status,
        'status_label': project.get_status_display(),
        'start_date': start.isoformat() if start else None,
        'end_date': end.isoformat() if end else None,
        'days_total': days_total,
        'days_elapsed': days_elapsed,
        'days_remaining': days_remaining,
        'pct_time_elapsed': pct_time_elapsed,
        'pct_tasks_done': pct_tasks_done,
        'task_total': total_tasks,
        'task_done': done_tasks,
        'budget': budget,
        'estimated_cost': estimated_cost,
        'spent_to_date': spent,
        'burn_rate_ratio': burn_rate_ratio,
        'burn_rate_per_day': burn_rate_per_day,
        'days_since_last_activity': days_inactive,
        'manhours_logged': mh_logged,
        'manhours_estimated': mh_est,
        'invoiced_to_date': billed,
        'contract_value': contract,
        'total_revenue': revenue,
        'estimate_original_value': _estimate_original_value(project),
        'consumable_request_count': ConsumableRequest.objects.filter(
            project=project, is_active=True
        ).count(),
        'recent_expenses': _recent_expenses(project),
        'recent_tasks': _recent_tasks(project),
        'items_consumed_vs_estimate': _items_consumed_vs_estimate(project),
        'vendor_spend_share': _vendor_spend_share(project),
    }


def compute_cost_forecast(f: dict) -> dict[str, Any]:
    """Deterministic cost forecast — avoids bogus -100% when spend is zero."""
    spent = f.get('spent_to_date') or 0
    budget = f.get('budget') or f.get('estimated_cost') or 0
    days_elapsed = f.get('days_elapsed') or 0
    days_total = f.get('days_total')
    status = f.get('status') or ''

    if budget <= 0:
        return {
            'status': 'no_budget',
            'predicted_final_cost': None,
            'variance_pct': None,
            'cost_overrun_pct': None,
            'display': 'Budget missing',
        }

    if spent == 0:
        if status == 'planning':
            return {
                'status': 'not_started',
                'predicted_final_cost': budget,
                'variance_pct': 0.0,
                'cost_overrun_pct': 0.0,
                'display': f'AED {budget:,.0f} budget — not started',
            }
        if status in _ONGOING_STATUSES and days_elapsed > 7:
            return {
                'status': 'in_progress_no_spend',
                'predicted_final_cost': None,
                'variance_pct': None,
                'cost_overrun_pct': None,
                'display': 'No activity yet',
                'alert': 'In Progress but no expenses recorded',
            }
        return {
            'status': 'early',
            'predicted_final_cost': budget,
            'variance_pct': 0.0,
            'cost_overrun_pct': 0.0,
            'display': f'AED {budget:,.0f} budget — early stage',
        }

    if days_total and days_elapsed > 0:
        burn_rate = spent / days_elapsed
        predicted_final = burn_rate * days_total
        variance_pct = ((predicted_final - budget) / budget) * 100
        return {
            'status': 'forecast',
            'predicted_final_cost': round(predicted_final, 2),
            'variance_pct': round(variance_pct, 1),
            'cost_overrun_pct': round(variance_pct, 1),
            'display': f'AED {predicted_final:,.0f} / {budget:,.0f} ({variance_pct:+.1f}%)',
        }

    return {
        'status': 'insufficient_data',
        'predicted_final_cost': spent,
        'variance_pct': None,
        'cost_overrun_pct': None,
        'display': f'AED {spent:,.0f} spent — insufficient timeline data',
    }


def compute_margin_forecast(f: dict, cost_fc: dict) -> dict[str, Any]:
    contract = f.get('contract_value') or 0
    revenue = f.get('total_revenue') or 0
    spent = f.get('spent_to_date') or 0
    pred_cost = cost_fc.get('predicted_final_cost')
    cost_status = cost_fc.get('status')

    if spent <= 0 and cost_status in ('not_started', 'early', 'in_progress_no_spend', 'no_budget'):
        return {'display': 'Pending', 'pct': None, 'negative': False}

    if contract <= 0 and revenue <= 0:
        return {'display': 'Pending', 'pct': None, 'negative': False}

    base_revenue = contract or revenue
    if pred_cost is None or cost_status in ('in_progress_no_spend', 'insufficient_data'):
        return {'display': 'Pending', 'pct': None, 'negative': False}

    if base_revenue <= 0:
        return {'display': 'N/A', 'pct': None, 'negative': False}

    pct = round((base_revenue - pred_cost) / base_revenue * 100, 1)
    return {'display': f'{pct:.1f}%', 'pct': pct, 'negative': pct < 0}


def _project_confidence_score(f: dict, cost_fc: dict) -> float:
    """Composite confidence from data completeness, history, horizon, recency."""
    scores: list[float] = []

    key_fields = (
        'budget',
        'start_date',
        'end_date',
        'spent_to_date',
        'pct_tasks_done',
        'contract_value',
    )
    populated = sum(
        1
        for k in key_fields
        if f.get(k) is not None and f.get(k) != '' and f.get(k) != 0
    )
    scores.append(min(1.0, populated / len(key_fields)))

    if f.get('days_elapsed') and (f.get('spent_to_date') or 0) > 0:
        scores.append(min(1.0, (f.get('days_elapsed') or 0) / 30))
    else:
        scores.append(0.25)

    days_total = f.get('days_total')
    days_elapsed = f.get('days_elapsed')
    if days_total and days_elapsed is not None:
        remaining = max(days_total - days_elapsed, 0)
        scores.append(max(0.2, 1.0 - remaining / max(days_total, 1)))
    else:
        scores.append(0.4)

    inactive = f.get('days_since_last_activity')
    if inactive is None:
        scores.append(0.15 if f.get('status') in _ONGOING_STATUSES else 0.35)
    elif inactive <= 7:
        scores.append(1.0)
    elif inactive <= 14:
        scores.append(0.55)
    else:
        scores.append(0.25)

    if cost_fc.get('status') in ('forecast', 'early', 'not_started'):
        scores.append(0.85)
    elif cost_fc.get('status') == 'in_progress_no_spend':
        scores.append(0.35)
    else:
        scores.append(0.5)

    return round(sum(scores) / len(scores), 2)


def _specific_ai_action(f: dict, reasons: list[str], risk: str) -> str:
    status = f.get('status')
    spent = f.get('spent_to_date') or 0
    days_elapsed = f.get('days_elapsed') or 0
    if status in _ONGOING_STATUSES and spent == 0:
        return 'Confirm work has started — call site engineer and log first expense this week'
    if reasons:
        r0 = reasons[0].lower()
        if 'no activity' in r0 or 'zero expenses' in r0:
            return 'Schedule site visit and update task status in ERP'
        if 'schedule lag' in r0 or 'tasks done' in r0:
            return 'Re-baseline task plan or extend deadline with client sign-off'
        if 'over budget' in r0 or 'burn rate' in r0:
            return 'Schedule expense review with site manager and freeze discretionary spend'
        if 'past planned end' in r0:
            return 'Update project status or negotiate deadline extension immediately'
        if 'budget not set' in r0:
            return 'Set approved budget and estimated cost before further work'
    if risk == 'red':
        return f'Escalate {f["code"]} to operations manager for recovery plan'
    if risk == 'amber':
        return f'Weekly check-in on {f["code"]} until metrics normalize'
    return f'Log site activity for {f["code"]} to improve forecast accuracy'


def _deterministic_risk_level(f: dict, cost_fc: dict, margin_fc: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = f.get('status') or ''
    spent = f.get('spent_to_date') or 0
    days_elapsed = f.get('days_elapsed') or 0
    pct_time = f.get('pct_time_elapsed') or 0
    pct_done = f.get('pct_tasks_done') or 0
    inactive = f.get('days_since_last_activity')
    overrun = cost_fc.get('cost_overrun_pct')
    today = timezone.localdate()

    red = False
    amber = False

    if status in _ONGOING_STATUSES and spent == 0 and days_elapsed >= 14:
        red = True
        reasons.append(f'In Progress {days_elapsed} days with zero expenses logged')
    if overrun is not None and overrun > 15:
        red = True
        reasons.append(f'Burn rate projects {overrun:+.0f}% over budget')
    if pct_time > 50 and pct_done < 25:
        red = True
        reasons.append(f'{pct_time:.0f}% time elapsed, only {pct_done:.0f}% tasks done')
    if inactive is not None and inactive >= 14:
        red = True
        reasons.append(f'No task, expense, or site activity for {inactive} days')
    if margin_fc.get('pct') is not None and margin_fc['pct'] < 0:
        red = True
        reasons.append('Predicted margin going negative')
    end_raw = f.get('end_date')
    if end_raw:
        try:
            if date.fromisoformat(end_raw) < today and status in ('planning', *_ONGOING_STATUSES):
                red = True
                reasons.append('Past planned end date with open status')
        except ValueError:
            pass

    if not red:
        if status in _ONGOING_STATUSES and spent == 0 and days_elapsed >= 7:
            amber = True
            reasons.append(f'In Progress {days_elapsed} days — no expenses recorded yet')
        if cost_fc.get('status') == 'no_budget':
            amber = True
            reasons.append('Budget not set on project')
        if cost_fc.get('status') == 'in_progress_no_spend':
            amber = True
            reasons.append('Active status but no spend — verify site work')
        if overrun is not None and 5 < overrun <= 15:
            amber = True
            reasons.append(f'Cost trajectory {overrun:+.0f}% above budget')
        if inactive is not None and 7 <= inactive < 14:
            amber = True
            reasons.append(f'No activity for {inactive} days')
        if pct_time > 30 and pct_done < 50:
            amber = True
            reasons.append(f'Schedule lag: {pct_time:.0f}% time vs {pct_done:.0f}% tasks')
        if margin_fc.get('pct') is not None and 0 <= margin_fc['pct'] < 8:
            amber = True
            reasons.append('Thin margin buffer on forecast')

    if not red and not amber:
        if inactive is not None and inactive <= 7 and spent > 0:
            reasons.append(f'Spend and activity within last {inactive} days')
        elif status == 'planning':
            reasons.append('Planning phase — awaiting mobilization')
        elif spent > 0:
            reasons.append('Cost burn aligned with elapsed timeline')
        else:
            reasons.append('Early stage — limited spend data so far')

    level = 'red' if red else 'amber' if amber else 'green'
    return level, reasons


def _sanitize_insight(text: str, fallback: str) -> str:
    t = (text or '').strip()
    if not t or any(p in t.lower() for p in FORBIDDEN_INSIGHT_PHRASES):
        return fallback
    return t


def _heuristic_project_score(f: dict) -> dict:
    """Fallback scoring when OpenAI is unavailable — strict rules, specific insights."""
    today = timezone.localdate()
    cost_fc = compute_cost_forecast(f)
    margin_fc = compute_margin_forecast(f, cost_fc)
    risk, reasons = _deterministic_risk_level(f, cost_fc, margin_fc)
    confidence = _project_confidence_score(f, cost_fc)

    pct_time = f.get('pct_time_elapsed') or 0
    pct_done = f.get('pct_tasks_done') or 0
    delay_days = 0
    end_raw = f.get('end_date')
    if end_raw and pct_done and pct_done < 100 and pct_done > 0:
        try:
            planned_end = date.fromisoformat(end_raw)
            projected_total_days = (f.get('days_elapsed') or 0) / (pct_done / 100.0)
            start_raw = f.get('start_date')
            projected_end = (
                date.fromisoformat(start_raw) if start_raw else today
            ) + timedelta(days=int(projected_total_days))
            delay_days = max(0, (projected_end - planned_end).days)
        except (ValueError, TypeError):
            pass

    predicted_end = '—'
    if end_raw:
        try:
            pe = date.fromisoformat(end_raw)
            if delay_days:
                pe = pe + timedelta(days=delay_days)
            predicted_end = pe.strftime('%d/%m/%Y')
        except ValueError:
            predicted_end = end_raw

    top_reason = reasons[0] if reasons else f'Status: {f.get("status_label", f.get("status"))}'
    ai_action = _specific_ai_action(f, reasons, risk)

    return {
        'code': f['code'],
        'risk_level': risk,
        'confidence': confidence,
        'predicted_end_date': predicted_end,
        'delay_days': delay_days,
        'predicted_final_cost': cost_fc.get('predicted_final_cost'),
        'cost_overrun_pct': cost_fc.get('cost_overrun_pct'),
        'predicted_margin_pct': margin_fc.get('pct'),
        'top_risk_reason': top_reason,
        'ai_action': ai_action,
        'reasoning': '; '.join(reasons[:3]),
        'cost_forecast': cost_fc,
        'margin_forecast': margin_fc,
    }


def _apply_score_enrichment(f: dict, score: dict) -> dict:
    """Merge AI score with deterministic cost/margin/risk floor."""
    cost_fc = score.get('cost_forecast') or compute_cost_forecast(f)
    margin_fc = score.get('margin_forecast') or compute_margin_forecast(f, cost_fc)

    det_risk, det_reasons = _deterministic_risk_level(f, cost_fc, margin_fc)
    risk_order = {'red': 0, 'amber': 1, 'green': 2}
    ai_risk = score.get('risk_level', 'green')
    final_risk = det_risk if risk_order.get(det_risk, 9) < risk_order.get(ai_risk, 9) else ai_risk

    confidence = score.get('confidence')
    if confidence is None:
        confidence = _project_confidence_score(f, cost_fc)
    else:
        confidence = round((float(confidence) + _project_confidence_score(f, cost_fc)) / 2, 2)

    top_reason = _sanitize_insight(
        score.get('top_risk_reason', ''),
        det_reasons[0] if det_reasons else f'Review {f["code"]} metrics',
    )
    ai_action = _sanitize_insight(
        score.get('ai_action', ''),
        _specific_ai_action(f, det_reasons, final_risk),
    )

    if cost_fc.get('cost_overrun_pct') is None and score.get('cost_overrun_pct') is not None:
        if cost_fc.get('status') == 'forecast':
            cost_fc['cost_overrun_pct'] = score['cost_overrun_pct']

    if margin_fc.get('pct') is None and score.get('predicted_margin_pct') is not None:
        if cost_fc.get('status') == 'forecast':
            margin_fc = {
                'display': f"{score['predicted_margin_pct']:.1f}%",
                'pct': score['predicted_margin_pct'],
                'negative': score['predicted_margin_pct'] < 0,
            }

    return {
        **score,
        'risk_level': final_risk,
        'confidence': confidence,
        'top_risk_reason': top_reason,
        'ai_action': ai_action,
        'predicted_final_cost': cost_fc.get('predicted_final_cost'),
        'cost_overrun_pct': cost_fc.get('cost_overrun_pct'),
        'predicted_margin_pct': margin_fc.get('pct'),
        'cost_forecast': cost_fc,
        'margin_forecast': margin_fc,
        'reasoning': score.get('reasoning') or '; '.join(det_reasons[:3]),
    }


def _deterministic_anomalies(features: list[dict]) -> list[dict]:
    anomalies = []
    today = timezone.localdate()

    for f in features:
        code = f['code']
        budget = f.get('budget') or 0
        spent = f.get('spent_to_date') or 0
        remaining = max(budget - spent, 0) if budget else 0
        inactive = f.get('days_since_last_activity')
        status = f.get('status') or ''
        days_elapsed = f.get('days_elapsed') or 0
        pct_time = f.get('pct_time_elapsed') or 0
        pct_done = f.get('pct_tasks_done') or 0
        cost_fc = compute_cost_forecast(f)

        if status in _ONGOING_STATUSES and spent == 0 and days_elapsed >= 7:
            anomalies.append(
                {
                    'category': 'Zero-spend In Progress',
                    'severity': 'high' if days_elapsed >= 14 else 'medium',
                    'project_code': code,
                    'description': f'In Progress {days_elapsed} days with AED 0 expenses logged',
                    'suggested_action': 'Confirm mobilization — call site engineer and post first expense',
                }
            )

        if inactive is not None and inactive >= 7:
            anomalies.append(
                {
                    'category': 'Inactivity',
                    'severity': 'high' if inactive >= 14 else 'medium',
                    'project_code': code,
                    'description': f'No task, expense, or site activity for {inactive} days',
                    'suggested_action': 'Schedule site visit or update task status',
                }
            )

        end_raw = f.get('end_date')
        if end_raw and status in ('planning', *_ONGOING_STATUSES):
            try:
                if date.fromisoformat(end_raw) < today:
                    anomalies.append(
                        {
                            'category': 'Stale project',
                            'severity': 'high',
                            'project_code': code,
                            'description': f'Past planned end date ({end_raw}) with status {f.get("status_label", status)}',
                            'suggested_action': 'Close out, extend deadline, or update status immediately',
                        }
                    )
            except ValueError:
                pass

        if pct_time > 0 and pct_done >= 0 and pct_time - pct_done >= 25:
            anomalies.append(
                {
                    'category': 'Schedule slip',
                    'severity': 'high' if pct_time - pct_done >= 40 else 'medium',
                    'project_code': code,
                    'description': f'{pct_time:.0f}% time elapsed but only {pct_done:.0f}% tasks complete',
                    'suggested_action': 'Re-baseline schedule or add crew capacity',
                }
            )

        overrun = cost_fc.get('cost_overrun_pct')
        if overrun is not None and overrun > 10 and cost_fc.get('status') == 'forecast':
            anomalies.append(
                {
                    'category': 'Budget overrun trajectory',
                    'severity': 'high' if overrun > 20 else 'medium',
                    'project_code': code,
                    'description': f'Burn rate projects {overrun:+.0f}% over AED {budget:,.0f} budget',
                    'suggested_action': 'Freeze discretionary spend and review cost-to-complete',
                }
            )

        if cost_fc.get('status') == 'no_budget':
            anomalies.append(
                {
                    'category': 'Budget missing',
                    'severity': 'medium',
                    'project_code': code,
                    'description': 'No budget or estimated cost set on active project',
                    'suggested_action': 'Set approved budget before further site work',
                }
            )

        for item in f.get('items_consumed_vs_estimate') or []:
            if item.get('ratio', 0) >= 2.0:
                anomalies.append(
                    {
                        'category': 'Unusual Item Usage',
                        'severity': 'high',
                        'project_code': code,
                        'description': (
                            f"{item['item_code']}: consumed {item['consumed_qty']:.0f} vs "
                            f"estimate {item['estimate_qty']:.0f} ({item['ratio']:.1f}×)"
                        ),
                        'suggested_action': 'Review scope and re-estimate materials',
                    }
                )
            elif item.get('ratio', 0) >= 1.3:
                anomalies.append(
                    {
                        'category': 'Unusual Item Usage',
                        'severity': 'medium',
                        'project_code': code,
                        'description': (
                            f"{item['item_code']}: consumed {item['consumed_qty']:.0f} vs "
                            f"estimate {item['estimate_qty']:.0f}"
                        ),
                        'suggested_action': 'Verify quantities on site',
                    }
                )

        for exp in f.get('recent_expenses') or []:
            amt = exp.get('amount') or 0
            if remaining > 0 and amt > remaining * 0.3:
                anomalies.append(
                    {
                        'category': 'Expense Spikes',
                        'severity': 'high',
                        'project_code': code,
                        'description': f"Expense AED {amt:,.0f} exceeds 30% of remaining budget",
                        'suggested_action': 'Verify invoice and approve before posting',
                    }
                )
                break

        mh_est = f.get('manhours_estimated') or 0
        mh_log = f.get('manhours_logged') or 0
        if mh_est > 0 and mh_log > mh_est * 1.2:
            anomalies.append(
                {
                    'category': 'Manhour Overruns',
                    'severity': 'medium',
                    'project_code': code,
                    'description': f'Logged {mh_log:.0f}h vs {mh_est:.0f}h estimated (+{((mh_log/mh_est)-1)*100:.0f}%)',
                    'suggested_action': 'Review crew allocation and task estimates',
                }
            )

        for v in f.get('vendor_spend_share') or []:
            if v.get('share_pct', 0) > 60:
                anomalies.append(
                    {
                        'category': 'Vendor Concentration Risk',
                        'severity': 'medium',
                        'project_code': code,
                        'description': f"{v['share_pct']:.0f}% of spend with {v['vendor']}",
                        'suggested_action': 'Diversify suppliers or renegotiate rates',
                    }
                )
                break

        contract = f.get('contract_value') or 0
        billed = f.get('invoiced_to_date') or 0
        if pct_done >= 80 and contract > 0 and billed < contract * 0.5:
            anomalies.append(
                {
                    'category': 'Late Invoicing',
                    'severity': 'medium',
                    'project_code': code,
                    'description': f'Work ~{pct_done:.0f}% complete but only {billed/contract*100:.0f}% invoiced',
                    'suggested_action': 'Raise progress invoice with client',
                }
            )

    seen = set()
    deduped = []
    for a in anomalies:
        key = (a.get('project_code'), a.get('category'), a.get('description'))
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    return deduped[:50]


def _merge_scores(features: list[dict], ai_scores: list[dict]) -> list[dict]:
    by_code = {s.get('code'): s for s in ai_scores if s.get('code')}
    merged = []
    for f in features:
        code = f['code']
        raw = by_code.get(code) or _heuristic_project_score(f)
        score = _apply_score_enrichment(f, raw)
        cost_fc = score.get('cost_forecast') or compute_cost_forecast(f)
        margin_fc = score.get('margin_forecast') or compute_margin_forecast(f, cost_fc)
        delay = score.get('delay_days') or 0
        end_display = score.get('predicted_end_date') or '—'
        if f.get('end_date') and delay:
            end_display = f"{end_display} (+{delay} days)" if delay > 0 else end_display

        merged.append(
            {
                **score,
                'project_id': f['id'],
                'project_name': f['name'],
                'customer': f.get('customer') or '—',
                'status': f.get('status'),
                'status_label': f.get('status_label'),
                'completion_forecast': end_display,
                'cost_forecast_display': cost_fc.get('display', '—'),
                'margin_forecast_display': margin_fc.get('display', 'Pending'),
                'margin_negative': margin_fc.get('negative', False),
                'detail_url': reverse('projects:project_detail', args=[f['id']]),
            }
        )

    risk_order = {'red': 0, 'amber': 1, 'green': 2}
    merged.sort(key=lambda r: (risk_order.get(r.get('risk_level'), 9), r.get('code', '')))
    return merged


def _projects_data_version(projects: list[Project]) -> str:
    if not projects:
        return '0'
    ids = [p.pk for p in projects]
    agg = Project.objects.filter(pk__in=ids).aggregate(m=Max('updated_at'))
    ts = agg.get('m')
    return ts.isoformat() if ts else '0'


def _cache_key(filters: dict, project_ids: list[int], data_version: str = '') -> str:
    raw = json.dumps(
        {'filters': filters, 'projects': project_ids, 'version': data_version},
        sort_keys=True,
    )
    return 'project_forecast:' + hashlib.sha256(raw.encode()).hexdigest()


def _summary_counts(rows: list[dict], features: list[dict] | None = None) -> dict:
    counts = {'red': 0, 'amber': 0, 'green': 0}
    confidences = []
    for r in rows:
        lvl = r.get('risk_level', 'green')
        if lvl in counts:
            counts[lvl] += 1
        if r.get('confidence') is not None:
            confidences.append(float(r['confidence']))
    if features and not confidences:
        for f in features:
            cost_fc = compute_cost_forecast(f)
            confidences.append(_project_confidence_score(f, cost_fc))
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
    return {
        'at_risk': counts['red'],
        'watch': counts['amber'],
        'healthy': counts['green'],
        'avg_confidence': avg_conf,
        'avg_confidence_pct': int(round(avg_conf * 100)),
    }


def _heuristic_brief(rows: list[dict], summary: dict) -> str:
    red = [r for r in rows if r.get('risk_level') == 'red']
    amber = [r for r in rows if r.get('risk_level') == 'amber']
    parts = [
        f"Portfolio: {summary.get('at_risk', 0)} at risk, "
        f"{summary.get('watch', 0)} to watch, {summary.get('healthy', 0)} healthy "
        f"(confidence {summary.get('avg_confidence_pct', 0)}%)."
    ]
    if red:
        codes = ', '.join(r['code'] for r in red[:3])
        parts.append(f"Immediate attention: {codes} — {red[0].get('top_risk_reason', '')}")
        parts.append(red[0].get('ai_action', ''))
    elif amber:
        parts.append(f"Monitor {amber[0]['code']}: {amber[0].get('top_risk_reason', '')}")
    zero_spend = [
        r for r in rows
        if 'no expenses' in (r.get('top_risk_reason') or '').lower()
        or 'no activity' in (r.get('top_risk_reason') or '').lower()
    ]
    if zero_spend:
        parts.append(
            f"{len(zero_spend)} In Progress project(s) show no spend — verify site mobilization."
        )
    return ' '.join(p for p in parts if p)


def analyze_projects(
    projects: list[Project],
    *,
    filters: dict | None = None,
    force_refresh: bool = False,
    regenerate_brief: bool = False,
) -> dict[str, Any]:
    """Run feature extraction + AI analysis with 30-minute cache."""
    filters = filters or {}
    today = timezone.localdate()
    features = [build_project_features(p, today=today) for p in projects]
    project_ids = [p.pk for p in projects]
    data_version = _projects_data_version(projects)

    cache_key = _cache_key(filters, project_ids, data_version)
    brief_key = cache_key + ':brief'

    cached = None if force_refresh else cache.get(cache_key)

    if cached and not force_refresh and not regenerate_brief:
        cached['from_cache'] = True
        return cached

    if cached and regenerate_brief and not force_refresh:
        rows = cached.get('rows') or []
        summary = cached.get('summary') or _summary_counts(rows, features)
        features = cached.get('features') or []
        ai_used = cached.get('ai_used', False)
        ai_error = cached.get('ai_error', '')
    else:
        cached = None
        ai_used = False
        ai_error = ''

        # Risk scoring
        scores_raw: list[dict] = []
        try:
            risk_resp = _call_openai(
                system=SYSTEM_PROMPT_RISK,
                user_payload={'projects': features},
                call_label='risk_scoring',
            )
            if isinstance(risk_resp, dict):
                scores_raw = risk_resp.get('projects') or risk_resp.get('items') or []
            elif isinstance(risk_resp, list):
                scores_raw = risk_resp
            ai_used = True
        except OpenAINotConfigured as exc:
            ai_error = str(exc)
            logger.warning('project_forecasting: OpenAI not configured — using deterministic scoring')
            scores_raw = [_heuristic_project_score(f) for f in features]
        except Exception as exc:
            ai_error = str(exc)[:300]
            logger.exception('project_forecasting risk_scoring failed')
            scores_raw = [_heuristic_project_score(f) for f in features]

        rows = _merge_scores(features, scores_raw)
        summary = _summary_counts(rows, features)

    brief_failed = False
    brief_error = ''
    if regenerate_brief or force_refresh or not cache.get(brief_key):
        try:
            brief_resp = _call_openai(
                system=SYSTEM_PROMPT_BRIEF,
                user_payload={'projects': features, 'summary': summary, 'scored_rows': rows},
                temperature=0.4,
                call_label='executive_brief',
            )
            if isinstance(brief_resp, dict):
                brief = brief_resp.get('brief') or brief_resp.get('summary') or brief_resp.get('text') or ''
            else:
                brief = str(brief_resp)
            if not brief:
                brief = _heuristic_brief(rows, summary)
            ai_used = True
        except OpenAINotConfigured as exc:
            brief = _heuristic_brief(rows, summary)
            ai_error = ai_error or str(exc)
        except Exception as exc:
            brief_failed = True
            brief_error = str(exc)[:300]
            logger.exception('project_forecasting executive_brief failed')
            brief = f'AI brief failed: {brief_error}'
    else:
        brief = cache.get(brief_key) or ''

    if not brief and not brief_failed:
        brief = _heuristic_brief(rows, summary)

    # Anomalies (skip on brief-only regeneration)
    if cached and regenerate_brief and not force_refresh:
        anomalies = cached.get('anomalies') or _deterministic_anomalies(features)
    else:
        anomalies = _deterministic_anomalies(features)
        try:
            an_resp = _call_openai(
                system=SYSTEM_PROMPT_ANOMALIES,
                user_payload={'projects': features},
                call_label='anomalies',
            )
            if isinstance(an_resp, dict):
                ai_anomalies = an_resp.get('anomalies') or []
                if ai_anomalies:
                    seen = {(a.get('project_code'), a.get('category')) for a in anomalies}
                    for a in ai_anomalies:
                        key = (a.get('project_code'), a.get('category'))
                        if key not in seen:
                            anomalies.append(a)
                            seen.add(key)
            ai_used = True
        except Exception:
            logger.exception('project_forecasting anomalies AI call failed')

    for a in anomalies:
        code = a.get('project_code')
        match = next((f for f in features if f['code'] == code), None)
        if match:
            a['detail_url'] = reverse('projects:project_detail', args=[match['id']])

    result = {
        'features': features,
        'rows': rows,
        'summary': summary,
        'executive_brief': brief.strip(),
        'anomalies': anomalies,
        'ai_used': ai_used,
        'ai_error': ai_error or (brief_error if brief_failed else ''),
        'brief_failed': brief_failed,
        'from_cache': False,
        'generated_at': timezone.now(),
    }

    cache.set(cache_key, result, CACHE_SECONDS)
    cache.set(brief_key, result['executive_brief'], CACHE_SECONDS)
    return result

def filter_choice_managers(projects: list[Project]) -> list[dict]:
    seen = {}
    for p in projects:
        if p.manager_id and p.manager_id not in seen:
            seen[p.manager_id] = p.manager.get_full_name() or p.manager.username
    return [{'id': k, 'label': v} for k, v in sorted(seen.items(), key=lambda x: x[1].lower())]


def filter_choice_customers(projects: list[Project]) -> list[dict]:
    seen = {}
    for p in projects:
        if p.customer_id and p.customer_id not in seen:
            c = p.customer
            seen[p.customer_id] = c.company or c.name
    return [{'id': k, 'label': v} for k, v in sorted(seen.items(), key=lambda x: x[1].lower())]


def build_forecast_report_context(
    *,
    start_date: date,
    end_date: date,
    status: str,
    manager_id: str,
    customer_id: str,
    force_refresh: bool = False,
    regenerate_brief: bool = False,
) -> dict[str, Any]:
    all_for_choices = get_forecast_projects_queryset(
        start_date=start_date,
        end_date=end_date,
        status='',
        manager_id='',
        customer_id='',
    )
    projects = get_forecast_projects_queryset(
        start_date=start_date,
        end_date=end_date,
        status=status,
        manager_id=manager_id,
        customer_id=customer_id,
    )
    filters = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'status': status,
        'manager_id': manager_id,
        'customer_id': customer_id,
    }
    analysis = analyze_projects(
        projects,
        filters=filters,
        force_refresh=force_refresh,
        regenerate_brief=regenerate_brief,
    )
    return {
        'start_date': start_date,
        'end_date': end_date,
        'status_filter': status,
        'manager_filter': manager_id,
        'customer_filter': customer_id,
        'status_choices': [('', 'All statuses')] + list(Project.STATUS_CHOICES),
        'manager_choices': filter_choice_managers(all_for_choices),
        'customer_choices': filter_choice_customers(all_for_choices),
        'project_count': len(projects),
        'openai_configured': bool(get_openai_api_key()),
        **analysis,
    }
