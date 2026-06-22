"""AI-driven sales / estimate forecasting with project learning."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.db.models import Max, Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.inventory.utils import get_openai_api_key
from apps.projects.models import Project, ProjectExpense
from apps.sales.models import Estimate, EstimateItem, Invoice

CACHE_SECONDS = 30 * 60
OPENAI_MODEL = 'gpt-4o-mini'
HISTORY_MONTHS = 12

ACTIVE_STATUSES = (
    'draft',
    'sent',
    'approved',
    'under_negotiation',
    'quotation_won',
)

LINE_CATEGORY_KEYWORDS = (
    (('labour', 'labor', 'manpower', 'man hour', 'manhour', 'technician'), 'labour'),
    (('travel', 'transport', 'mobil', 'vehicle', 'fuel', 'mileage'), 'travel'),
    (('overhead', 'admin', 'misc', 'contingency', 'supervision'), 'overhead'),
    (('subcontract', 'sub-contract', 'sub contract'), 'subcontract'),
)

SYSTEM_PROMPT_ESTIMATE_FORECAST = """You are a sales and pricing analyst for a UAE fire & safety contracting ERP.

You receive:
1. ACTIVE estimates with cost breakdown (material, labour, travel, overhead) and estimated margin.
2. COMPLETED PROJECTS with estimated vs actual cost and variance.
3. Salesperson historical win rates and pricing accuracy.

You MUST only reference project codes that appear in the completed_projects input array. Do NOT generate or invent codes.

Return JSON: {"estimates": [{"estimate_id": <int>, "predicted_outcome": "Win"|"Loss"|"Stalled"|"Under Negotiation",
"win_probability": 0-100, "predicted_close_date": "DD/MM/YYYY", "predicted_actual_margin_pct": <float>,
"margin_erosion_risk_aed": <float>, "risk_flag": "red"|"amber"|"green", "matched_project_code": "<code or null>",
"match_reason": "<one sentence>", "top_insight": "<one sentence>", "ai_action": "<one actionable sentence>",
"confidence": 0.0-1.0, "reasoning": "<2-3 sentences>"}]}

Rules for risk_flag:
- RED if cost structure matches a completed project that ran at a loss, OR predicted outcome is Loss
- AMBER if predicted actual margin is 5%+ lower than estimated margin
- GREEN if well-priced and likely profitable

Match by customer, job_type/work classification, cost ratios, salesperson accuracy. Cite only real project codes from input."""

SYSTEM_PROMPT_PATTERNS = """You are surfacing actionable pricing patterns from completed project data for a UAE fire & safety contractor.

You MUST only reference project codes from the completed_projects input. Do NOT invent codes.

Return JSON: {"patterns": [{"pattern_name": "<short label>", "frequency": <int>, "avg_margin_impact_pct": <float>,
"category": "customer"|"job_type"|"cost_component"|"salesperson"|"geography", "recommendation": "<one sentence>",
"supporting_project_codes": ["PROJ-XXXX"]}]}

Surface only patterns supported by 3+ projects when possible. Order by absolute margin impact desc. Max 8 patterns."""

SYSTEM_PROMPT_NEXT_MONTH = """Forecast next month's sales for a UAE fire & safety ERP.
Input: active estimate pipeline, salesperson stats, historical conversion.

Return JSON:
{
  "expected_wins_count": <int>,
  "expected_won_value_aed": <float>,
  "expected_won_value_low_aed": <float>,
  "expected_won_value_high_aed": <float>,
  "expected_profit_aed": <float>,
  "expected_new_estimates": <int>,
  "confidence_pct": <int>,
  "top_risks": ["..."],
  "key_assumptions": ["..."]
}
Base on actual historical velocity. Do not extrapolate optimistically."""

SYSTEM_PROMPT_SP_QUALITY = """You are a sales pricing quality analyst for a UAE fire & safety ERP.
Input: salesperson stats with estimated vs actual margins on completed projects.

Return JSON: {"salespeople": [{"user_id": <int|null>, "label": "<name>", "pricing_accuracy_pct": <float>,
"ai_verdict": "<one short sentence>"}]}
Verdicts must reflect real data — underpricing labour, accurate benchmark, etc."""

SYSTEM_PROMPT_BRIEF = """You are a sales forecasting analyst for a UAE fire & safety contractor.
Given forecast results, patterns, project learning, and next month outlook, return JSON:
{"brief": "<5-8 lines plain English executive summary>"}
Mention estimate numbers, AED amounts, project codes from input only. No bullet points."""


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
    return _parse_openai_json(content)


def _classify_line_category(item: EstimateItem) -> str:
    if item.inventory_item_id:
        return 'material'
    text = f'{(item.group_name or "").lower()} {(item.description or "").lower()}'
    for keywords, cat in LINE_CATEGORY_KEYWORDS:
        if any(k in text for k in keywords):
            return cat
    return 'overhead'


def _line_base_cost(item: EstimateItem) -> Decimal:
    qty = item.effective_quantity
    return (qty * (item.unit_price or Decimal('0'))).quantize(Decimal('0.01'))


def _line_sell_amount(item: EstimateItem) -> Decimal:
    return item.total or Decimal('0')


def _estimate_cost_breakdown(estimate: Estimate) -> dict[str, float]:
    buckets = {'material': 0.0, 'labour': 0.0, 'travel': 0.0, 'overhead': 0.0, 'subcontract': 0.0}
    for item in estimate.items.all():
        cat = _classify_line_category(item)
        if cat not in buckets:
            buckets['overhead'] += _decimal(_line_base_cost(item))
        else:
            buckets[cat] += _decimal(_line_base_cost(item))
    return buckets


def _estimate_sell_breakdown(estimate: Estimate) -> dict[str, float]:
    buckets = {'material': 0.0, 'labour': 0.0, 'travel': 0.0, 'overhead': 0.0, 'subcontract': 0.0}
    for item in estimate.items.all():
        cat = _classify_line_category(item)
        key = cat if cat in buckets else 'overhead'
        buckets[key] += _decimal(_line_sell_amount(item))
    return buckets


def _margin_pct(revenue: float, cost: float) -> float:
    if revenue <= 0:
        return 0.0
    return round((revenue - cost) / revenue * 100, 1)


def _estimate_margin_pct(estimate: Estimate) -> float:
    sell = _decimal(estimate.subtotal) - _decimal(estimate.discount_applied)
    cost = _decimal(estimate.total_cost())
    return _margin_pct(sell, cost)


def _is_fully_invoiced_won(estimate: Estimate) -> bool:
    if estimate.status != 'quotation_won':
        return False
    try:
        remaining = estimate.proforma_remaining_total
        if remaining is not None and remaining <= Decimal('0.01'):
            return True
    except Exception:
        pass
    invoiced = (
        Invoice.objects.filter(estimate=estimate, is_active=True)
        .exclude(status='cancelled')
        .aggregate(t=Sum('total_amount'))['t']
        or Decimal('0')
    )
    total = estimate.total_amount or Decimal('0')
    return total > 0 and invoiced >= total * Decimal('0.99')


def _job_type_label(estimate: Estimate) -> str:
    labels = estimate.scope_display_labels
    if labels:
        return ' / '.join(labels)
    if estimate.customer_id and estimate.customer.job_type:
        return ', '.join(estimate.customer.job_type_display_labels)
    return estimate.type_of_work or ''


def _days_in_status(estimate: Estimate, today: date) -> int | None:
    if estimate.updated_at:
        return max(0, (today - timezone.localtime(estimate.updated_at).date()).days)
    if estimate.date:
        return max(0, (today - estimate.date).days)
    return None


def build_estimate_features(estimate: Estimate, *, today: date | None = None) -> dict[str, Any]:
    today = today or timezone.localdate()
    breakdown = _estimate_cost_breakdown(estimate)
    sell_bd = _estimate_sell_breakdown(estimate)
    total_cost = sum(breakdown.values())
    sell_net = _decimal(estimate.subtotal) - _decimal(estimate.discount_applied)
    sp = estimate.assigned_to

    return {
        'estimate_id': estimate.pk,
        'estimate_number': estimate.display_estimate_number,
        'customer': estimate.customer.display_name if estimate.customer_id else '',
        'customer_id': estimate.customer_id,
        'job_type': _job_type_label(estimate),
        'salesperson': (sp.get_full_name() or sp.username) if sp else '',
        'salesperson_id': sp.pk if sp else None,
        'preparer': estimate.prepared_by or '',
        'status': estimate.status,
        'status_label': estimate.get_status_display(),
        'date': estimate.date.isoformat() if estimate.date else None,
        'total_value_aed': _decimal(estimate.total_amount),
        'subtotal_aed': _decimal(estimate.subtotal),
        'vat_aed': _decimal(estimate.vat_amount),
        'line_count': estimate.items.count(),
        'material_cost_aed': breakdown['material'],
        'labour_cost_aed': breakdown['labour'],
        'travel_cost_aed': breakdown['travel'],
        'overhead_aed': breakdown['overhead'] + breakdown.get('subcontract', 0),
        'total_cost_aed': total_cost,
        'sell_net_aed': sell_net,
        'estimated_margin_pct': _estimate_margin_pct(estimate),
        'cost_ratios': {
            k: round(v / total_cost, 3) if total_cost else 0
            for k, v in breakdown.items()
        },
        'scope': estimate.scope_display_labels,
        'days_since_created': max(0, (today - estimate.date).days) if estimate.date else None,
        'days_in_current_status': _days_in_status(estimate, today),
        'linked_project_id': estimate.project_id,
        'invoiced_aed': _decimal(
            Invoice.objects.filter(estimate=estimate, is_active=True)
            .exclude(status='cancelled')
            .aggregate(t=Sum('total_amount'))['t']
        ),
    }


def _project_expense_breakdown(project: Project) -> dict[str, float]:
    qs = (
        ProjectExpense.objects.filter(project=project, is_active=True)
        .exclude(status='rejected')
        .values('category')
        .annotate(total=Sum('total_amount'))
    )
    mapping = {
        'material': 'material',
        'labor': 'labour',
        'subcontract': 'subcontract',
        'travel': 'travel',
        'equipment': 'material',
        'other': 'overhead',
    }
    buckets = {'material': 0.0, 'labour': 0.0, 'travel': 0.0, 'overhead': 0.0, 'subcontract': 0.0}
    for row in qs:
        key = mapping.get(row['category'], 'overhead')
        buckets[key] += _decimal(row['total'])
    return buckets


def _linked_estimate_for_project(project: Project) -> Estimate | None:
    return (
        Estimate.objects.filter(project=project, is_active=True)
        .order_by('-date', '-created_at')
        .first()
    )


def build_completed_project_features(project: Project) -> dict[str, Any]:
    est = _linked_estimate_for_project(project)
    est_breakdown = _estimate_cost_breakdown(est) if est else {}
    act_breakdown = _project_expense_breakdown(project)

    contract = _decimal(project.contract_value or project.budget)
    actual_cost = _decimal(project.total_expenses)
    est_cost = _decimal(project.estimated_cost or (est.total_cost() if est else 0))
    revenue = _decimal(project.total_revenue or contract)

    est_margin = _margin_pct(contract, est_cost)
    act_margin = _margin_pct(revenue, actual_cost)
    variance = 0.0
    if est_cost > 0:
        variance = round((actual_cost - est_cost) / est_cost * 100, 1)

    sp_label = ''
    preparer = ''
    if est:
        if est.assigned_to_id:
            sp_label = est.assigned_to.get_full_name() or est.assigned_to.username
        preparer = est.prepared_by or ''

    end_date = project.end_date or (
        timezone.localtime(project.updated_at).date() if project.updated_at else None
    )

    ai_liner = ''
    worst_cat = None
    worst_delta = 0.0
    for cat in ('labour', 'travel', 'material'):
        est_v = est_breakdown.get(cat, 0)
        act_v = act_breakdown.get(cat if cat != 'material' else 'material', 0)
        if est_v > 0:
            delta_pct = (act_v - est_v) / est_v * 100
            if abs(delta_pct) > abs(worst_delta):
                worst_delta = delta_pct
                worst_cat = cat
    if worst_cat and worst_delta > 10:
        ai_liner = f'{worst_cat.title()} {worst_delta:+.0f}% vs estimate — review assumptions'
    elif variance < -5:
        ai_liner = f'Under budget by {abs(variance):.0f}% — favourable execution'
    elif variance > 10:
        ai_liner = f'Over budget by {variance:.0f}% — cost overrun on delivery'
    else:
        ai_liner = 'Costs tracked close to estimate'

    return {
        'project_id': project.pk,
        'project_code': project.project_code,
        'project_name': project.name,
        'customer': project.customer.display_name if project.customer_id else '',
        'customer_id': project.customer_id,
        'job_type': _job_type_label(est) if est else '',
        'estimated_cost_aed': est_cost,
        'actual_cost_aed': actual_cost,
        'contract_value_aed': contract,
        'actual_revenue_aed': revenue,
        'estimated_margin_pct': est_margin,
        'actual_margin_pct': act_margin,
        'variance_pct': variance,
        'expense_breakdown': act_breakdown,
        'estimated_breakdown': est_breakdown,
        'salesperson': sp_label,
        'preparer': preparer,
        'completion_date': end_date.isoformat() if end_date else None,
        'status': project.status,
        'ai_one_liner': ai_liner,
        'detail_url': reverse('projects:project_detail', args=[project.pk]),
    }


def get_completed_projects_queryset(*, limit: int = 200) -> list[Project]:
    qs = (
        Project.objects.filter(is_active=True, status='completed')
        .select_related('customer', 'manager')
        .order_by('-end_date', '-updated_at')[:limit]
    )
    return list(qs)


def get_forecast_estimates_queryset(
    *,
    start_date: date,
    end_date: date,
    status: str = '',
    salesperson_id: str = '',
    customer_id: str = '',
    job_type: str = '',
):
    qs = (
        Estimate.objects.filter(is_active=True)
        .exclude(status__in=('quotation_lost', 'rejected'))
        .select_related('customer', 'assigned_to', 'project')
        .prefetch_related('items')
    )

    qs = qs.filter(
        Q(date__gte=start_date, date__lte=end_date)
        | Q(updated_at__date__gte=start_date, updated_at__date__lte=end_date)
        | Q(date__lt=start_date, status__in=ACTIVE_STATUSES)
    )

    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.filter(status__in=ACTIVE_STATUSES)

    if salesperson_id == 'none':
        qs = qs.filter(assigned_to__isnull=True)
    elif salesperson_id:
        try:
            qs = qs.filter(assigned_to_id=int(salesperson_id))
        except (TypeError, ValueError):
            pass

    if customer_id:
        try:
            qs = qs.filter(customer_id=int(customer_id))
        except (TypeError, ValueError):
            pass

    estimates = [e for e in qs.order_by('-date', '-created_at') if not _is_fully_invoiced_won(e)]

    if job_type:
        jt = job_type.lower()
        estimates = [e for e in estimates if jt in _job_type_label(e).lower()]

    return estimates


def build_salesperson_stats(completed: list[dict], estimates: list[dict]) -> list[dict]:
    by_user: dict[str, dict] = {}

    def bucket(label: str, user_id=None):
        key = str(user_id) if user_id else label or 'unknown'
        if key not in by_user:
            by_user[key] = {
                'user_id': user_id,
                'label': label or 'Unassigned',
                'estimates_prepared': 0,
                'wins': 0,
                'losses': 0,
                'completed_projects': 0,
                'margin_deltas': [],
            }
        return by_user[key]

    for e in estimates:
        b = bucket(e.get('salesperson') or e.get('preparer', ''), e.get('salesperson_id'))
        b['estimates_prepared'] += 1
        if e.get('status') == 'quotation_won':
            b['wins'] += 1
        elif e.get('status') == 'quotation_lost':
            b['losses'] += 1

    for p in completed:
        label = p.get('salesperson') or p.get('preparer') or 'Unknown'
        b = bucket(label)
        b['completed_projects'] += 1
        est_m = p.get('estimated_margin_pct', 0)
        act_m = p.get('actual_margin_pct', 0)
        b.setdefault('est_margins', []).append(est_m)
        b.setdefault('act_margins', []).append(act_m)
        b['margin_deltas'].append(act_m - est_m)

    rows = []
    for b in by_user.values():
        total = b['wins'] + b['losses'] + b['estimates_prepared']
        win_rate = round(b['wins'] / total * 100, 1) if total else 0.0
        est_margins = b.get('est_margins', [])
        act_margins = b.get('act_margins', [])
        avg_est_margin = round(sum(est_margins) / len(est_margins), 1) if est_margins else 0.0
        avg_act_margin = round(sum(act_margins) / len(act_margins), 1) if act_margins else 0.0
        pricing_accuracy = 100.0
        if b['margin_deltas']:
            avg_delta = sum(abs(d) for d in b['margin_deltas']) / len(b['margin_deltas'])
            pricing_accuracy = max(0.0, round(100 - avg_delta, 1))
        rows.append(
            {
                **b,
                'win_rate_pct': win_rate,
                'avg_estimated_margin_pct': avg_est_margin,
                'avg_actual_margin_pct': avg_act_margin,
                'pricing_accuracy_pct': pricing_accuracy,
            }
        )
    return rows


def _cost_similarity(est: dict, project: dict) -> float:
    er = est.get('cost_ratios') or {}
    pb = project.get('estimated_breakdown') or {}
    total = sum(pb.values()) or 1
    pr = {k: v / total for k, v in pb.items()}
    keys = set(er.keys()) | set(pr.keys())
    if not keys:
        return 0.0
    return sum(abs(er.get(k, 0) - pr.get(k, 0)) for k in keys) / len(keys)


def _find_best_project_match(est: dict, completed: list[dict]) -> dict | None:
    candidates = []
    for p in completed:
        score = 100.0
        if est.get('customer_id') and p.get('customer_id') == est['customer_id']:
            score -= 30
        if est.get('job_type') and p.get('job_type') and est['job_type'].lower() in p['job_type'].lower():
            score -= 20
        score += _cost_similarity(est, p) * 50
        candidates.append((score, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    best = candidates[0][1]
    if candidates[0][0] > 80:
        return None
    return best


def _heuristic_estimate_forecast(f: dict, completed: list[dict]) -> dict:
    status = f.get('status', 'draft')
    est_margin = f.get('estimated_margin_pct', 0)
    match = _find_best_project_match(f, completed)

    win_prob = {'draft': 25, 'sent': 40, 'approved': 55, 'under_negotiation': 50, 'quotation_won': 85}.get(
        status, 35
    )
    predicted_margin = est_margin
    risk = 'green'
    outcome = 'Win' if win_prob >= 55 else 'Stalled' if win_prob >= 35 else 'Loss'
    matched_code = None
    match_reason = ''
    top_insight = 'Pipeline progressing normally'
    ai_action = 'Follow up with customer this week'

    if match:
        matched_code = match.get('project_code')
        act_m = match.get('actual_margin_pct', 0)
        predicted_margin = act_m
        if act_m < 0 or match.get('variance_pct', 0) > 15:
            risk = 'red'
            outcome = 'Loss' if win_prob < 50 else 'Win'
            match_reason = f'Similar cost mix to {matched_code} (actual margin {act_m:.0f}%)'
            top_insight = f'Matches loss pattern of {matched_code}'
            ai_action = 'Review labour and travel assumptions before closing'
        elif est_margin - act_m > 5:
            risk = 'amber'
            match_reason = f'Similar scope to {matched_code}'
            top_insight = f'Expected margin erosion vs estimate ({est_margin:.0f}% → {act_m:.0f}%)'
            ai_action = 'Add contingency or revise labour rates'

    if status == 'under_negotiation':
        outcome = 'Under Negotiation'
    if est_margin < 5 and risk == 'green':
        risk = 'amber'
        top_insight = 'Thin estimated margin — limited buffer for overruns'

    close = timezone.localdate() + timedelta(days=30 if status == 'sent' else 45)
    erosion = max(0, (est_margin - predicted_margin) / 100 * f.get('sell_net_aed', 0))

    return {
        'estimate_id': f['estimate_id'],
        'predicted_outcome': outcome,
        'win_probability': win_prob,
        'predicted_close_date': close.strftime('%d/%m/%Y'),
        'predicted_actual_margin_pct': round(predicted_margin, 1),
        'margin_erosion_risk_aed': round(erosion, 0),
        'risk_flag': risk,
        'matched_project_code': matched_code,
        'match_reason': match_reason,
        'top_insight': top_insight,
        'ai_action': ai_action,
        'confidence': 0.6,
        'reasoning': match_reason or top_insight,
    }


def _deterministic_patterns(completed: list[dict]) -> list[dict]:
    patterns = []
    by_customer: dict[str, list] = {}
    by_job: dict[str, list] = {}
    for p in completed:
        c = p.get('customer') or 'Unknown'
        by_customer.setdefault(c, []).append(p)
        j = p.get('job_type') or 'General'
        by_job.setdefault(j, []).append(p)

    for name, group in by_customer.items():
        if len(group) < 2:
            continue
        impacts = [(g.get('actual_margin_pct', 0) - g.get('estimated_margin_pct', 0)) for g in group]
        avg_impact = round(sum(impacts) / len(impacts), 1)
        patterns.append(
            {
                'pattern_name': f'{name} jobs',
                'frequency': len(group),
                'avg_margin_impact_pct': avg_impact,
                'category': 'customer',
                'recommendation': 'Add labour buffer' if avg_impact < -5 else 'Maintain current pricing',
                'supporting_project_codes': [g['project_code'] for g in group[:4]],
            }
        )

    for name, group in by_job.items():
        if len(group) < 2 or name == 'General':
            continue
        travel_over = []
        for g in group:
            est = g.get('estimated_breakdown', {}).get('travel', 0)
            act = g.get('expense_breakdown', {}).get('travel', 0)
            if est > 0 and act > est * 1.2:
                travel_over.append(g)
        if travel_over:
            patterns.append(
                {
                    'pattern_name': f'{name} — travel overrun',
                    'frequency': len(travel_over),
                    'avg_margin_impact_pct': -8.0,
                    'category': 'cost_component',
                    'recommendation': 'Increase travel allowance on similar estimates',
                    'supporting_project_codes': [g['project_code'] for g in travel_over[:4]],
                }
            )

    patterns.sort(key=lambda p: abs(p.get('avg_margin_impact_pct', 0)), reverse=True)
    return patterns[:8]


def _build_pattern_alerts(rows: list[dict], completed: list[dict]) -> list[dict]:
    alerts = []
    completed_codes = {p['project_code'] for p in completed}
    for row in rows:
        code = row.get('matched_project_code')
        if not code or code not in completed_codes:
            continue
        match = next((p for p in completed if p['project_code'] == code), None)
        if not match:
            continue
        severity = 'high' if row.get('risk_flag') == 'red' else 'medium'
        if row.get('risk_flag') == 'green':
            severity = 'low'
        alerts.append(
            {
                'severity': severity,
                'estimate_id': row.get('estimate_id'),
                'estimate_number': row.get('estimate_number'),
                'estimate_url': row.get('detail_url'),
                'matched_project_code': code,
                'project_url': match.get('detail_url'),
                'description': row.get('top_insight') or row.get('match_reason', ''),
                'suggested_action': row.get('ai_action', ''),
            }
        )
    return alerts


def _merge_estimate_rows(features: list[dict], forecasts: list[dict], completed: list[dict]) -> list[dict]:
    by_id = {f.get('estimate_id'): f for f in forecasts if f.get('estimate_id')}
    rows = []
    for feat in features:
        fc = by_id.get(feat['estimate_id']) or _heuristic_estimate_forecast(feat, completed)
        est_margin = feat.get('estimated_margin_pct', 0)
        pred_margin = fc.get('predicted_actual_margin_pct', est_margin)
        risk = fc.get('risk_flag', 'green')
        matched_url = ''
        if fc.get('matched_project_code'):
            match = next(
                (p for p in completed if p.get('project_code') == fc.get('matched_project_code')),
                None,
            )
            if match:
                matched_url = match.get('detail_url', '')
        rows.append(
            {
                **fc,
                'matched_project_url': matched_url,
                'estimate_number': feat['estimate_number'],
                'customer': feat['customer'],
                'salesperson': feat.get('salesperson') or feat.get('preparer') or '—',
                'status_label': feat.get('status_label', feat.get('status')),
                'total_value_display': f"AED {feat.get('total_value_aed', 0):,.0f}",
                'estimated_margin_display': f'{est_margin:.1f}%',
                'predicted_margin_display': f'{pred_margin:.1f}%',
                'margin_negative': pred_margin < 0,
                'detail_url': reverse('sales:estimate_detail', args=[feat['estimate_id']]),
            }
        )
    risk_order = {'red': 0, 'amber': 1, 'green': 2}
    rows.sort(key=lambda r: (risk_order.get(r.get('risk_flag'), 9), -r.get('win_probability', 0)))
    return rows


def _summary_from_rows(rows: list[dict], features: list[dict]) -> dict:
    feat_by_id = {f['estimate_id']: f for f in features}
    wins = [r for r in rows if r.get('predicted_outcome') == 'Win']
    at_risk = [r for r in rows if r.get('risk_flag') == 'red' or r.get('predicted_outcome') == 'Loss']
    confidences = [float(r.get('confidence', 0.5)) for r in rows]
    won_value = 0.0
    predicted_profit = 0.0
    for r in wins:
        feat = feat_by_id.get(r['estimate_id'], {})
        val = feat.get('total_value_aed', 0)
        prob = (r.get('win_probability') or 0) / 100
        won_value += val * prob
        predicted_profit += val * (r.get('predicted_actual_margin_pct') or 0) / 100 * prob
    return {
        'predicted_closures': len(wins),
        'predicted_won_value': round(won_value, 0),
        'predicted_profit': round(predicted_profit, 0),
        'at_risk_count': len(at_risk),
        'avg_confidence': round(sum(confidences) / len(confidences), 2) if confidences else 0.0,
        'avg_confidence_pct': int(round((sum(confidences) / len(confidences) * 100) if confidences else 0)),
    }


def _heuristic_next_month(rows: list[dict], features: list[dict], historical_wins: int) -> dict:
    feat_by_id = {f['estimate_id']: f for f in features}
    wins = [r for r in rows if (r.get('win_probability') or 0) >= 50]
    value = sum(feat_by_id.get(r['estimate_id'], {}).get('total_value_aed', 0) for r in wins)
    profit = sum(
        feat_by_id.get(r['estimate_id'], {}).get('total_value_aed', 0)
        * (r.get('predicted_actual_margin_pct') or 0)
        / 100
        for r in wins
    )
    monthly_wins = max(1, round(len(wins) * 0.35)) if wins else max(1, historical_wins // 12)
    return {
        'expected_wins_count': monthly_wins,
        'expected_won_value_aed': round(value * 0.35, 0),
        'expected_won_value_low_aed': round(value * 0.25, 0),
        'expected_won_value_high_aed': round(value * 0.45, 0),
        'expected_profit_aed': round(profit * 0.35, 0),
        'expected_new_estimates': max(2, len(rows) // 3),
        'confidence_pct': 65,
        'top_risks': ['Margin erosion on labour-heavy estimates', 'Slow customer payment cycles'],
        'key_assumptions': ['Historical win velocity applied to active pipeline'],
    }


def _heuristic_brief(rows: list[dict], patterns: list[dict], summary: dict, note: str = '') -> str:
    parts = []
    if note and 'Configure OpenAI' in note:
        parts.append('Set OPENAI_API_KEY in .env for richer AI insights.')
    parts.append(
        f"Of {len(rows)} active estimates, AI predicts {summary.get('predicted_closures', 0)} closures "
        f"worth AED {summary.get('predicted_won_value', 0):,.0f} with predicted profit "
        f"AED {summary.get('predicted_profit', 0):,.0f}."
    )
    red = [r for r in rows if r.get('risk_flag') == 'red']
    if red:
        codes = ', '.join(r['estimate_number'] for r in red[:2])
        parts.append(f"At-risk estimates: {codes} — {red[0].get('top_insight', '')}")
    if patterns:
        parts.append(f"Pattern: {patterns[0].get('pattern_name')} — {patterns[0].get('recommendation', '')}")
    return ' '.join(p for p in parts if p)


def _cache_key(filters: dict, est_ids: list[int], proj_ids: list[int], version: str) -> str:
    raw = json.dumps(
        {'filters': filters, 'estimates': est_ids, 'projects': proj_ids, 'version': version},
        sort_keys=True,
    )
    return 'sales_forecast:' + hashlib.sha256(raw.encode()).hexdigest()


def _data_version(estimates: list[Estimate], projects: list[Project]) -> str:
    parts = []
    if estimates:
        agg = Estimate.objects.filter(pk__in=[e.pk for e in estimates]).aggregate(m=Max('updated_at'))
        if agg.get('m'):
            parts.append(agg['m'].isoformat())
    if projects:
        agg = Project.objects.filter(pk__in=[p.pk for p in projects]).aggregate(m=Max('updated_at'))
        if agg.get('m'):
            parts.append(agg['m'].isoformat())
    return '|'.join(parts) or '0'


def forecast_sales(
    estimates: list[Estimate],
    *,
    start_date: date,
    end_date: date,
    filters: dict | None = None,
    force_refresh: bool = False,
    regenerate_brief: bool = False,
) -> dict[str, Any]:
    filters = filters or {}
    today = timezone.localdate()
    features = [build_estimate_features(e, today=today) for e in estimates]
    est_ids = [e.pk for e in estimates]

    projects = get_completed_projects_queryset(limit=200)
    completed = [build_completed_project_features(p) for p in projects]
    proj_ids = [p.pk for p in projects]
    version = _data_version(estimates, projects)

    cache_key = _cache_key(filters, est_ids, proj_ids, version)
    brief_key = cache_key + ':brief'

    cached = None if force_refresh else cache.get(cache_key)
    if cached and not force_refresh and not regenerate_brief:
        cached['from_cache'] = True
        return cached

    ai_used = False
    ai_error = ''

    if cached and regenerate_brief and not force_refresh:
        rows = cached.get('rows') or []
        summary = cached.get('summary') or {}
        patterns = cached.get('patterns') or []
        project_cards = cached.get('project_cards') or []
        pattern_alerts = cached.get('pattern_alerts') or []
        next_month = cached.get('next_month') or {}
        sp_quality = cached.get('sp_quality') or []
        features = cached.get('features') or features
        completed = cached.get('completed') or completed
        ai_used = cached.get('ai_used', False)
        ai_error = cached.get('ai_error', '')
    else:
        sp_stats = build_salesperson_stats(completed, features)

        forecasts_raw: list[dict] = []
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_ESTIMATE_FORECAST,
                user_payload={
                    'active_estimates': features,
                    'completed_projects': completed,
                    'salesperson_stats': sp_stats,
                },
            )
            if isinstance(resp, dict):
                forecasts_raw = resp.get('estimates') or resp.get('items') or []
            ai_used = True
        except OpenAINotConfigured as exc:
            ai_error = str(exc)
            forecasts_raw = [_heuristic_estimate_forecast(f, completed) for f in features]
        except Exception as exc:
            ai_error = str(exc)[:300]
            forecasts_raw = [_heuristic_estimate_forecast(f, completed) for f in features]

        if not forecasts_raw:
            forecasts_raw = [_heuristic_estimate_forecast(f, completed) for f in features]

        rows = _merge_estimate_rows(features, forecasts_raw, completed)
        summary = _summary_from_rows(rows, features)

        patterns = _deterministic_patterns(completed)
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_PATTERNS,
                user_payload={'completed_projects': completed},
            )
            if isinstance(resp, dict):
                ai_patterns = resp.get('patterns') or []
                if ai_patterns:
                    seen = {p.get('pattern_name') for p in patterns}
                    for p in ai_patterns:
                        if p.get('pattern_name') not in seen:
                            patterns.append(p)
                            seen.add(p.get('pattern_name'))
            ai_used = True
        except Exception:
            pass
        patterns = patterns[:8]

        pattern_alerts = _build_pattern_alerts(rows, completed)
        project_cards = completed[:12]

        hist_wins = Estimate.objects.filter(
            status='quotation_won',
            date__gte=end_date - timedelta(days=365),
        ).count()

        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_NEXT_MONTH,
                user_payload={'pipeline': features, 'summary': summary, 'historical_wins': hist_wins},
            )
            next_month = resp if isinstance(resp, dict) else {}
            ai_used = True
        except Exception:
            next_month = _heuristic_next_month(rows, features, hist_wins)
        if not next_month:
            next_month = _heuristic_next_month(rows, features, hist_wins)

        sp_quality = []
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_SP_QUALITY,
                user_payload={'salesperson_stats': sp_stats, 'completed_projects': completed},
            )
            if isinstance(resp, dict):
                sp_quality = resp.get('salespeople') or []
            ai_used = True
        except Exception:
            pass
        if not sp_quality:
            for s in sp_stats:
                delta = sum(abs(d) for d in s.get('margin_deltas', [])) / max(len(s.get('margin_deltas', [])), 1)
                if s.get('margin_deltas') and delta > 8:
                    verdict = 'Consistently underprices labour — review cost build-up'
                elif s.get('pricing_accuracy_pct', 0) >= 85:
                    verdict = 'Accurate pricing — reference benchmark'
                else:
                    verdict = 'Review travel and overhead assumptions'
                sp_quality.append(
                    {
                        'user_id': s.get('user_id'),
                        'label': s.get('label'),
                        'estimates_prepared': s.get('estimates_prepared', 0),
                        'win_rate_pct': s.get('win_rate_pct', 0),
                        'avg_estimated_margin_pct': s.get('avg_estimated_margin_pct', 0),
                        'avg_actual_margin_pct': s.get('avg_actual_margin_pct', 0),
                        'pricing_accuracy_pct': s.get('pricing_accuracy_pct', 0),
                        'ai_verdict': verdict,
                    }
                )

    brief = ''
    if regenerate_brief or force_refresh or not cache.get(brief_key):
        try:
            resp = _call_openai(
                system=SYSTEM_PROMPT_BRIEF,
                user_payload={
                    'summary': summary,
                    'rows': rows[:15],
                    'patterns': patterns,
                    'project_cards': project_cards[:6],
                    'next_month': next_month,
                },
                temperature=0.4,
            )
            if isinstance(resp, dict):
                brief = resp.get('brief') or ''
            ai_used = True
        except Exception as exc:
            brief = _heuristic_brief(rows, patterns, summary, ai_error or str(exc))
    else:
        brief = cache.get(brief_key) or ''

    if not brief:
        brief = _heuristic_brief(rows, patterns, summary, ai_error)

    result = {
        'features': features,
        'rows': rows,
        'summary': summary,
        'patterns': patterns,
        'project_cards': project_cards,
        'pattern_alerts': pattern_alerts,
        'next_month': next_month,
        'sp_quality': sp_quality,
        'completed': completed,
        'executive_brief': brief.strip(),
        'ai_used': ai_used,
        'ai_error': ai_error,
        'from_cache': False,
        'generated_at': timezone.now(),
    }
    cache.set(cache_key, result, CACHE_SECONDS)
    cache.set(brief_key, result['executive_brief'], CACHE_SECONDS)
    return result


def filter_choice_customers(estimates: list[Estimate]) -> list[dict]:
    seen = {}
    for e in estimates:
        if e.customer_id and e.customer_id not in seen:
            seen[e.customer_id] = e.customer.display_name
    return [{'id': k, 'label': v} for k, v in sorted(seen.items(), key=lambda x: x[1].lower())]


def filter_choice_salespeople(estimates: list[Estimate]) -> list[dict]:
    seen = {}
    for e in estimates:
        if e.assigned_to_id and e.assigned_to_id not in seen:
            u = e.assigned_to
            seen[e.assigned_to_id] = u.get_full_name() or u.username
    return [{'id': k, 'label': v} for k, v in sorted(seen.items(), key=lambda x: x[1].lower())]


def filter_choice_job_types(estimates: list[Estimate]) -> list[dict]:
    seen = {}
    for e in estimates:
        jt = _job_type_label(e)
        if jt:
            seen[jt.lower()] = jt
    return [{'id': k, 'label': v} for k, v in sorted(seen.items(), key=lambda x: x[1].lower())]


def build_sales_forecast_report_context(
    *,
    start_date: date,
    end_date: date,
    status: str,
    salesperson_id: str,
    customer_id: str,
    job_type: str,
    force_refresh: bool = False,
    regenerate_brief: bool = False,
) -> dict[str, Any]:
    all_for_choices = get_forecast_estimates_queryset(
        start_date=start_date,
        end_date=end_date,
        status='',
        salesperson_id='',
        customer_id='',
        job_type='',
    )
    estimates = get_forecast_estimates_queryset(
        start_date=start_date,
        end_date=end_date,
        status=status,
        salesperson_id=salesperson_id,
        customer_id=customer_id,
        job_type=job_type,
    )
    filters = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'status': status,
        'salesperson_id': salesperson_id,
        'customer_id': customer_id,
        'job_type': job_type,
    }
    analysis = forecast_sales(
        estimates,
        start_date=start_date,
        end_date=end_date,
        filters=filters,
        force_refresh=force_refresh,
        regenerate_brief=regenerate_brief,
    )
    return {
        'start_date': start_date,
        'end_date': end_date,
        'status_filter': status,
        'salesperson_filter': salesperson_id,
        'customer_filter': customer_id,
        'job_type_filter': job_type,
        'status_choices': [('', 'All statuses')] + list(Estimate.STATUS_CHOICES),
        'customer_choices': filter_choice_customers(all_for_choices),
        'salesperson_choices': filter_choice_salespeople(all_for_choices),
        'job_type_choices': [{'id': '', 'label': 'All job types'}] + filter_choice_job_types(all_for_choices),
        'estimate_count': len(estimates),
        'openai_configured': bool(get_openai_api_key()),
        **analysis,
    }
