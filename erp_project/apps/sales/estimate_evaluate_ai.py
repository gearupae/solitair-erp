"""AI review of estimate terms, pricing, and VAT (quotation quality flags)."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.inventory.utils import get_openai_api_key

CACHE_HOURS = 24
CACHE_PREFIX = 'estimate_ai_eval:'


def _quantize(value) -> float:
    try:
        return float(Decimal(str(value or '0')).quantize(Decimal('0.01')))
    except Exception:
        return 0.0


def build_estimate_snapshot(estimate) -> dict:
    """Compact quotation payload for AI / heuristic review."""
    items = []
    for item in estimate.items.select_related('tax_code', 'inventory_item').order_by('sort_order', 'id'):
        items.append({
            'description': (item.description or '')[:200],
            'group': (item.group_name or '')[:100],
            'quantity': _quantize(item.quantity),
            'unit_price': _quantize(item.unit_price),
            'rate': _quantize(item.rate),
            'profit_type': item.profit_type,
            'profit_value': _quantize(item.profit_value),
            'line_total': _quantize(item.total),
            'vat_amount': _quantize(item.vat_amount),
            'vat_rate': _quantize(item.vat_rate),
            'tax_code': item.tax_code.code if item.tax_code_id else '',
            'tax_code_name': item.tax_code.name if item.tax_code_id else '',
            'is_vat_inclusive': bool(item.is_vat_inclusive),
            'item_code': item.inventory_item.item_code if item.inventory_item_id else '',
        })

    customer = estimate.customer
    return {
        'estimate_number': estimate.display_estimate_number,
        'status': estimate.status,
        'date': str(estimate.date) if estimate.date else '',
        'valid_until': str(estimate.valid_until) if estimate.valid_until else '',
        'customer': {
            'name': customer.name if customer else '',
            'company': customer.company if customer else '',
            'trn': getattr(customer, 'trn', '') or '',
        },
        'discount_type': estimate.discount_type,
        'discount_value': _quantize(estimate.discount_value),
        'discount_applied': _quantize(estimate.discount_applied),
        'subtotal': _quantize(estimate.subtotal),
        'vat_amount': _quantize(estimate.vat_amount),
        'total_amount': _quantize(estimate.total_amount),
        'retention_percent': _quantize(estimate.retention_percent) if estimate.retention_percent else None,
        'terms_and_conditions': (estimate.terms_and_conditions or '')[:4000],
        'client_note': (estimate.client_note or '')[:1500],
        'notes': (estimate.notes or '')[:1000],
        'line_count': len(items),
        'items': items[:80],
        'updated_at': estimate.updated_at.isoformat() if estimate.updated_at else '',
    }


def _cache_key(estimate, snapshot: dict) -> str:
    raw = f"{estimate.pk}|{snapshot.get('updated_at')}|{snapshot.get('total_amount')}|{snapshot.get('line_count')}"
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
    return f'{CACHE_PREFIX}{estimate.pk}:{digest}'


def _normalize_flags(raw_flags: list) -> list[dict]:
    allowed_categories = {'terms', 'pricing', 'vat', 'general'}
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

    terms = (snapshot.get('terms_and_conditions') or '').strip()
    if not terms:
        flags.append({
            'severity': 'red',
            'category': 'terms',
            'title': 'Terms & conditions missing',
            'detail': 'No terms and conditions text on this quotation. Add payment terms, validity, and scope exclusions before sending.',
        })
    elif len(terms) < 80:
        flags.append({
            'severity': 'amber',
            'category': 'terms',
            'title': 'Terms & conditions very short',
            'detail': 'Terms text is brief — confirm payment terms, warranty, and liability are covered.',
        })
    else:
        flags.append({
            'severity': 'green',
            'category': 'terms',
            'title': 'Terms & conditions present',
            'detail': 'Quotation includes terms and conditions text.',
        })

    if not snapshot.get('valid_until'):
        flags.append({
            'severity': 'amber',
            'category': 'terms',
            'title': 'Valid until date not set',
            'detail': 'Add a valid-until date so pricing expiry is clear to the customer.',
        })

    items = snapshot.get('items') or []
    if not items:
        flags.append({
            'severity': 'red',
            'category': 'pricing',
            'title': 'No line items',
            'detail': 'This quotation has no line items — totals cannot be validated.',
        })
    else:
        zero_rate = [i for i in items if (i.get('rate') or 0) <= 0]
        if zero_rate:
            flags.append({
                'severity': 'red',
                'category': 'pricing',
                'title': f'{len(zero_rate)} line(s) with zero rate',
                'detail': 'Some lines have zero selling rate — review before customer issue.',
            })
        high_profit = [
            i for i in items
            if i.get('profit_type') == 'percent' and (i.get('profit_value') or 0) >= 50
        ]
        if high_profit:
            flags.append({
                'severity': 'amber',
                'category': 'pricing',
                'title': 'High profit markup on line(s)',
                'detail': 'One or more lines use ≥50% profit markup — double-check competitiveness.',
            })
        if snapshot.get('subtotal', 0) > 0:
            flags.append({
                'severity': 'green',
                'category': 'pricing',
                'title': 'Priced line items present',
                'detail': f'{len(items)} line(s); subtotal AED {snapshot.get("subtotal", 0):,.2f}.',
            })

    lines_with_tax = [i for i in items if i.get('tax_code')]
    lines_without_tax = [i for i in items if not i.get('tax_code')]
    mixed_vat = bool(lines_with_tax and lines_without_tax)
    if mixed_vat:
        flags.append({
            'severity': 'amber',
            'category': 'vat',
            'title': 'Mixed tax codes on lines',
            'detail': f'{len(lines_with_tax)} taxed and {len(lines_without_tax)} out-of-scope lines — confirm this is intentional.',
        })

    vat_on_header = snapshot.get('vat_amount', 0)
    vat_on_lines = sum((i.get('vat_amount') or 0) for i in items)
    if vat_on_header > 0 and vat_on_lines <= 0:
        flags.append({
            'severity': 'red',
            'category': 'vat',
            'title': 'VAT total without line tax codes',
            'detail': 'Header shows VAT but no lines have tax codes — recalculate or assign tax codes.',
        })
    elif vat_on_header <= 0 and any((i.get('vat_rate') or 0) > 0 for i in items):
        flags.append({
            'severity': 'red',
            'category': 'vat',
            'title': 'Line VAT rates but zero header VAT',
            'detail': 'Lines have VAT rates but quotation VAT total is zero — run recalculate on the estimate.',
        })
    elif vat_on_header > 0:
        flags.append({
            'severity': 'green',
            'category': 'vat',
            'title': 'VAT calculated',
            'detail': f'Output VAT AED {vat_on_header:,.2f} on subtotal AED {snapshot.get("subtotal", 0):,.2f}.',
        })
    else:
        flags.append({
            'severity': 'green',
            'category': 'vat',
            'title': 'Zero-rated / out of scope',
            'detail': 'No output VAT on this quotation (zero-rated or out of scope).',
        })

    if snapshot.get('discount_applied', 0) > snapshot.get('subtotal', 0):
        flags.append({
            'severity': 'red',
            'category': 'pricing',
            'title': 'Discount exceeds subtotal',
            'detail': 'Applied discount is larger than the line subtotal — fix discount settings.',
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

    knowledge = get_ai_knowledge_prompt_block(AiModuleKnowledge.MODULE_ESTIMATE)
    system = (
        'You are a UAE fire & safety ERP quotation reviewer. '
        'Review terms & conditions, pricing logic, and VAT/tax compliance for a sales estimate. '
        'Return ONLY valid JSON with this shape: '
        '{"flags":[{"severity":"green|red|amber","category":"terms|pricing|vat|general",'
        '"title":"short title","detail":"one or two sentences"}],'
        '"summary":"2-3 sentence overall assessment"} '
        'Use green for OK/pass, red for must-fix issues, amber for warnings. '
        'Focus on: missing/weak T&C, validity, TRN, mixed VAT, zero rates, discount errors, '
        'unusual margins, VAT mismatch between lines and totals.'
        f'{knowledge}'
    )
    user_payload = json.dumps(snapshot, default=str)[:14000]
    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'Quotation snapshot:\n{user_payload}'},
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


def evaluate_estimate(estimate, *, force_refresh: bool = False) -> dict:
    """Run AI + heuristic quotation review; cache per estimate revision."""
    snapshot = build_estimate_snapshot(estimate)
    key = _cache_key(estimate, snapshot)
    if not force_refresh:
        cached = cache.get(key)
        if cached:
            cached['from_cache'] = True
            return cached

    result = _fetch_evaluation_from_openai(snapshot)
    result['from_cache'] = False
    result['estimate_number'] = snapshot.get('estimate_number', '')
    cache.set(key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def get_cached_estimate_evaluation(estimate) -> dict | None:
    snapshot = build_estimate_snapshot(estimate)
    key = _cache_key(estimate, snapshot)
    cached = cache.get(key)
    if cached:
        cached['from_cache'] = True
    return cached
