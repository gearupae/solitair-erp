"""AI review of project budget, timeline, compliance, and delivery readiness."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.inventory.utils import get_openai_api_key

CACHE_HOURS = 24
CACHE_PREFIX = 'project_ai_eval:'


def _quantize(value) -> float:
    try:
        return float(Decimal(str(value or '0')).quantize(Decimal('0.01')))
    except Exception:
        return 0.0


def build_project_snapshot(project, *, recorded_expenses=None, budget_pct_used=None) -> dict:
    customer = project.customer
    manager = project.manager
    tasks = list(project.tasks.filter(is_active=True).values_list('status', flat=True))
    task_counts = {}
    for status in tasks:
        task_counts[status] = task_counts.get(status, 0) + 1

    checklist_total = project.checklist_items.filter(is_active=True).count()
    checklist_flagged_red = project.checklist_items.filter(is_active=True, is_flagged_red=True).count()
    checklist_ok = checklist_total - checklist_flagged_red

    return {
        'project_code': project.project_code,
        'name': (project.name or '')[:200],
        'status': project.status,
        'category': project.category,
        'sub_category': project.sub_category,
        'billing_type': project.billing_type,
        'customer': {
            'name': customer.name if customer else '',
            'company': customer.company if customer else '',
        },
        'manager': (
            f'{manager.get_full_name() or manager.username}' if manager else ''
        ),
        'start_date': str(project.start_date) if project.start_date else '',
        'end_date': str(project.end_date) if project.end_date else '',
        'budget': _quantize(project.budget),
        'estimated_cost': _quantize(project.estimated_cost),
        'contract_value': _quantize(project.contract_value),
        'recorded_expenses': _quantize(recorded_expenses),
        'budget_pct_used': float(budget_pct_used) if budget_pct_used is not None else None,
        'member_count': project.members.count(),
        'technician_count': project.technicians.count(),
        'conversion_approval_status': project.conversion_approval_status,
        'edit_approval_status': project.edit_approval_status,
        'task_counts': task_counts,
        'checklist_ok': checklist_ok,
        'checklist_flagged_red': checklist_flagged_red,
        'checklist_total': checklist_total,
        'description': (project.description or '')[:2000],
        'updated_at': project.updated_at.isoformat() if project.updated_at else '',
    }


def _cache_key(project, snapshot: dict) -> str:
    raw = (
        f"{project.pk}|{snapshot.get('updated_at')}|{snapshot.get('status')}"
        f"|{snapshot.get('recorded_expenses')}|{snapshot.get('budget_pct_used')}"
    )
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
    return f'{CACHE_PREFIX}{project.pk}:{digest}'


def _normalize_flags(raw_flags: list) -> list[dict]:
    allowed_categories = {'budget', 'timeline', 'compliance', 'team', 'general'}
    allowed_severity = {'green', 'red', 'amber'}
    out = []
    for row in raw_flags or []:
        if not isinstance(row, dict):
            continue
        severity = str(row.get('severity', 'amber')).lower()
        if severity not in allowed_severity:
            severity = 'amber'
        category = str(row.get('category', 'general')).lower()
        if category not in allowed_categories:
            category = 'general'
        title = str(row.get('title', '')).strip()[:200]
        detail = str(row.get('detail', '')).strip()[:500]
        if not title:
            continue
        out.append({
            'severity': severity,
            'category': category,
            'title': title,
            'detail': detail,
        })
    return out[:12]


def _heuristic_evaluation(snapshot: dict) -> dict:
    flags: list[dict] = []
    today = date.today()

    if not snapshot.get('customer', {}).get('name'):
        flags.append({
            'severity': 'amber',
            'category': 'compliance',
            'title': 'No customer linked',
            'detail': 'Project has no customer — link a customer for billing and reporting.',
        })
    else:
        flags.append({
            'severity': 'green',
            'category': 'compliance',
            'title': 'Customer assigned',
            'detail': f"Customer: {snapshot['customer']['name']}.",
        })

    if snapshot.get('status') == 'draft' and snapshot.get('conversion_approval_status') == 'pending':
        flags.append({
            'severity': 'amber',
            'category': 'compliance',
            'title': 'Conversion approval pending',
            'detail': 'Project is still in draft awaiting conversion approval from quotation.',
        })

    budget = snapshot.get('budget', 0)
    recorded = snapshot.get('recorded_expenses', 0)
    if budget > 0 and recorded > budget:
        flags.append({
            'severity': 'red',
            'category': 'budget',
            'title': 'Over proposed budget',
            'detail': f'Actual spend AED {recorded:,.2f} exceeds budget AED {budget:,.2f}.',
        })
    elif budget > 0:
        flags.append({
            'severity': 'green',
            'category': 'budget',
            'title': 'Within proposed budget',
            'detail': f'Spend AED {recorded:,.2f} of budget AED {budget:,.2f}.',
        })

    end_date_raw = snapshot.get('end_date') or ''
    if end_date_raw:
        try:
            end_date = date.fromisoformat(end_date_raw)
            if end_date < today and snapshot.get('status') not in ('completed', 'cancelled'):
                flags.append({
                    'severity': 'red',
                    'category': 'timeline',
                    'title': 'Past end date',
                    'detail': f'End date {end_date_raw} has passed but project is still {snapshot.get("status")}.',
                })
            elif end_date <= today + timedelta(days=14):
                flags.append({
                    'severity': 'amber',
                    'category': 'timeline',
                    'title': 'End date approaching',
                    'detail': f'End date is {end_date_raw} — confirm delivery schedule.',
                })
        except ValueError:
            pass

    if not snapshot.get('manager'):
        flags.append({
            'severity': 'amber',
            'category': 'team',
            'title': 'No project manager',
            'detail': 'Assign a manager for accountability and approvals.',
        })

    checklist_total = snapshot.get('checklist_total', 0)
    checklist_flagged_red = snapshot.get('checklist_flagged_red', 0)
    if checklist_flagged_red > 0:
        flags.append({
            'severity': 'red',
            'category': 'compliance',
            'title': f'{checklist_flagged_red} checklist item(s) flagged red',
            'detail': f'{checklist_flagged_red} of {checklist_total} site checklist row(s) are marked as issues.',
        })
    elif checklist_total > 0:
        flags.append({
            'severity': 'green',
            'category': 'compliance',
            'title': 'Checklist clear',
            'detail': f'All {checklist_total} checklist item(s) are green (no issues flagged).',
        })

    red_count = sum(1 for f in flags if f['severity'] == 'red')
    green_count = sum(1 for f in flags if f['severity'] == 'green')
    summary = (
        f'Rule-based check: {green_count} green flag(s), {red_count} red flag(s). '
        'Configure OpenAI in Settings for deeper AI review.'
    )
    return {
        'flags': flags,
        'summary': summary,
        'source': 'heuristic',
        'openai_used': False,
        'generated_at': timezone.now().isoformat(),
    }


def _parse_json_content(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def _fetch_evaluation_from_openai(snapshot: dict) -> dict:
    api_key = get_openai_api_key()
    if not api_key:
        result = _heuristic_evaluation(snapshot)
        result['warnings'] = ['OpenAI not configured — showing rule-based checks only.']
        return result

    import urllib.error
    import urllib.request

    from apps.core.ai_knowledge import get_ai_knowledge_prompt_block
    from apps.core.models import AiModuleKnowledge

    knowledge = get_ai_knowledge_prompt_block(AiModuleKnowledge.MODULE_PROJECT)
    system = (
        'You are a UAE fire & safety ERP project reviewer. '
        'Review project budget vs spend, timeline, team assignment, checklist/compliance, '
        'and conversion/completion approval state. '
        'Return ONLY valid JSON with this shape: '
        '{"flags":[{"severity":"green|red|amber","category":"budget|timeline|compliance|team|general",'
        '"title":"short title","detail":"one or two sentences"}],'
        '"summary":"2-3 sentence overall assessment"} '
        'Use green for OK/pass, red for must-fix issues, amber for warnings.'
        f'{knowledge}'
    )
    user_payload = json.dumps(snapshot, default=str)[:14000]
    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'Project snapshot:\n{user_payload}'},
        ],
        'temperature': 0.2,
    }).encode('utf-8')

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
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        content = payload['choices'][0]['message']['content']
        data = _parse_json_content(content)
        flags = _normalize_flags(data.get('flags'))
        if not flags:
            raise ValueError('empty flags')
        return {
            'flags': flags,
            'summary': str(data.get('summary', '')).strip()[:800],
            'source': 'openai',
            'openai_used': True,
            'generated_at': timezone.now().isoformat(),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
        result = _heuristic_evaluation(snapshot)
        result['warnings'] = ['AI request failed — showing rule-based checks only.']
        return result


def evaluate_project(project, *, force_refresh: bool = False, recorded_expenses=None, budget_pct_used=None) -> dict:
    snapshot = build_project_snapshot(
        project,
        recorded_expenses=recorded_expenses,
        budget_pct_used=budget_pct_used,
    )
    key = _cache_key(project, snapshot)
    if not force_refresh:
        cached = cache.get(key)
        if cached:
            cached['from_cache'] = True
            return cached

    result = _fetch_evaluation_from_openai(snapshot)
    result['from_cache'] = False
    result['project_code'] = snapshot.get('project_code', '')
    cache.set(key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def get_cached_project_evaluation(project, *, recorded_expenses=None, budget_pct_used=None) -> dict | None:
    snapshot = build_project_snapshot(
        project,
        recorded_expenses=recorded_expenses,
        budget_pct_used=budget_pct_used,
    )
    key = _cache_key(project, snapshot)
    cached = cache.get(key)
    if cached:
        cached['from_cache'] = True
    return cached
