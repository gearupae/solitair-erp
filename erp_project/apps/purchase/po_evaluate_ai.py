"""AI review of purchase order terms, retention, vendor, line items, and VAT."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.inventory.utils import get_openai_api_key

CACHE_HOURS = 24
CACHE_PREFIX = 'po_ai_eval:'


def _quantize(value) -> float:
    try:
        return float(Decimal(str(value or '0')).quantize(Decimal('0.01')))
    except Exception:
        return 0.0


def build_po_snapshot(po) -> dict:
    """Compact PO payload for AI / heuristic review."""
    vendor = po.vendor
    items = []
    for item in po.items.select_related('tax_code', 'inventory_item').order_by('id'):
        inv = item.inventory_item
        items.append({
            'description': (item.description or '')[:200],
            'item_code': inv.item_code if inv else '',
            'item_name': (inv.name if inv else '')[:120],
            'quantity': _quantize(item.quantity),
            'unit_price': _quantize(item.unit_price),
            'line_total': _quantize(item.total),
            'vat_amount': _quantize(item.vat_amount),
            'vat_rate': _quantize(item.vat_rate),
            'tax_code': item.tax_code.code if item.tax_code_id else '',
            'is_vat_inclusive': bool(item.is_vat_inclusive),
        })

    retention_pct = _quantize(po.retention_percent) if po.retention_percent else None
    retention_amount = None
    if retention_pct and po.total_amount:
        retention_amount = _quantize(
            Decimal(str(po.total_amount)) * Decimal(str(retention_pct)) / Decimal('100')
        )

    return {
        'po_number': po.po_number,
        'status': po.status,
        'order_date': str(po.order_date) if po.order_date else '',
        'expected_delivery_date': str(po.expected_delivery_date) if po.expected_delivery_date else '',
        'vendor': {
            'name': vendor.name if vendor else '',
            'vendor_number': vendor.vendor_number if vendor else '',
            'email': (vendor.email or '') if vendor else '',
            'phone': (vendor.phone or '') if vendor else '',
            'trn': (vendor.trn or '') if vendor else '',
            'payment_terms': (vendor.payment_terms or '') if vendor else '',
            'status': vendor.status if vendor else '',
        },
        'project': po.project.name if po.project_id else '',
        'retention_percent': retention_pct,
        'retention_amount_estimate': retention_amount,
        'terms_and_conditions': (po.terms_and_conditions or '')[:4000],
        'notes': (po.notes or '')[:1000],
        'subtotal': _quantize(po.subtotal),
        'vat_amount': _quantize(po.vat_amount),
        'total_amount': _quantize(po.total_amount),
        'line_count': len(items),
        'items': items[:80],
        'updated_at': po.updated_at.isoformat() if po.updated_at else '',
    }


def _cache_key(po, snapshot: dict) -> str:
    raw = (
        f"{po.pk}|{snapshot.get('updated_at')}|{snapshot.get('total_amount')}"
        f"|{snapshot.get('line_count')}|{snapshot.get('retention_percent')}"
    )
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
    return f'{CACHE_PREFIX}{po.pk}:{digest}'


def _normalize_flags(raw_flags: list) -> list[dict]:
    allowed_categories = {'terms', 'retention', 'vendor', 'items', 'vat', 'general'}
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
            'detail': 'No PO terms text — add payment, delivery, and warranty terms before sending to the vendor.',
        })
    elif len(terms) < 80:
        flags.append({
            'severity': 'amber',
            'category': 'terms',
            'title': 'Terms & conditions very short',
            'detail': 'PO terms are brief — confirm delivery, payment, and liability clauses are covered.',
        })
    else:
        flags.append({
            'severity': 'green',
            'category': 'terms',
            'title': 'Terms & conditions present',
            'detail': 'Purchase order includes terms and conditions text.',
        })

    vendor = snapshot.get('vendor') or {}
    vendor_name = (vendor.get('name') or '').strip()
    if not vendor_name:
        flags.append({
            'severity': 'red',
            'category': 'vendor',
            'title': 'Vendor not set',
            'detail': 'No supplier is linked to this purchase order.',
        })
    else:
        flags.append({
            'severity': 'green',
            'category': 'vendor',
            'title': f'Supplier: {vendor_name[:80]}',
            'detail': (
                f"Vendor #{vendor.get('vendor_number') or '—'}; "
                f"payment terms: {vendor.get('payment_terms') or 'not set'}."
            ),
        })
        if (vendor.get('status') or '') == 'inactive':
            flags.append({
                'severity': 'red',
                'category': 'vendor',
                'title': 'Vendor is inactive',
                'detail': 'Supplier status is inactive — confirm before issuing or paying this PO.',
            })
        if not (vendor.get('trn') or '').strip():
            flags.append({
                'severity': 'amber',
                'category': 'vendor',
                'title': 'Vendor TRN missing',
                'detail': 'Supplier has no TRN on file — required for UAE VAT-compliant purchases.',
            })
        if not (vendor.get('email') or '').strip():
            flags.append({
                'severity': 'amber',
                'category': 'vendor',
                'title': 'Vendor email missing',
                'detail': 'No supplier email — you cannot email this PO until an address is added on the vendor record.',
            })

    retention_pct = snapshot.get('retention_percent')
    project = (snapshot.get('project') or '').strip()
    if retention_pct:
        if retention_pct not in (5.0, 10.0) and retention_pct not in (5, 10):
            flags.append({
                'severity': 'amber',
                'category': 'retention',
                'title': 'Unusual retention percentage',
                'detail': f'Retention is {retention_pct}% — expected 5% or 10% for project vendor retention.',
            })
        elif not project:
            flags.append({
                'severity': 'red',
                'category': 'retention',
                'title': 'Retention without project',
                'detail': 'Retention % is set but no project is linked — link a project or clear retention.',
            })
        else:
            amt = snapshot.get('retention_amount_estimate')
            amt_txt = f' (~AED {amt:,.2f})' if amt else ''
            flags.append({
                'severity': 'green',
                'category': 'retention',
                'title': f'Retention {retention_pct:g}%{amt_txt}',
                'detail': f'Project “{project}” — retention withheld from vendor bill AP.',
            })
    elif project:
        flags.append({
            'severity': 'amber',
            'category': 'retention',
            'title': 'Project linked, no retention',
            'detail': f'PO is linked to project “{project}” but retention is not set (5% or 10% if applicable).',
        })

    items = snapshot.get('items') or []
    if not items:
        flags.append({
            'severity': 'red',
            'category': 'items',
            'title': 'No line items',
            'detail': 'This PO has no products or services — add lines before sending to the vendor.',
        })
    else:
        zero_price = [i for i in items if (i.get('unit_price') or 0) <= 0]
        if zero_price:
            flags.append({
                'severity': 'red',
                'category': 'items',
                'title': f'{len(zero_price)} line(s) with zero unit price',
                'detail': 'Some lines have zero purchase price — review before vendor issue.',
            })
        short_desc = [i for i in items if len((i.get('description') or '').strip()) < 3]
        if short_desc:
            flags.append({
                'severity': 'amber',
                'category': 'items',
                'title': 'Vague product descriptions',
                'detail': f'{len(short_desc)} line(s) have very short descriptions — use clear product names for the vendor.',
            })
        names = [(i.get('description') or '').strip().lower() for i in items]
        if len(names) != len(set(names)):
            flags.append({
                'severity': 'amber',
                'category': 'items',
                'title': 'Duplicate line descriptions',
                'detail': 'Multiple lines share the same description — confirm quantities and items are correct.',
            })
        flags.append({
            'severity': 'green',
            'category': 'items',
            'title': f'{len(items)} product line(s)',
            'detail': f'PO subtotal AED {snapshot.get("subtotal", 0):,.2f} across {len(items)} line(s).',
        })

    lines_with_tax = [i for i in items if i.get('tax_code')]
    lines_without_tax = [i for i in items if not i.get('tax_code')]
    if lines_with_tax and lines_without_tax:
        flags.append({
            'severity': 'amber',
            'category': 'vat',
            'title': 'Mixed tax codes on lines',
            'detail': f'{len(lines_with_tax)} taxed and {len(lines_without_tax)} out-of-scope lines — confirm intent.',
        })
    vat_header = snapshot.get('vat_amount', 0)
    vat_lines = sum((i.get('vat_amount') or 0) for i in items)
    if vat_header > 0 and vat_lines <= 0:
        flags.append({
            'severity': 'red',
            'category': 'vat',
            'title': 'VAT total without line tax codes',
            'detail': 'Header shows VAT but no lines have tax codes — assign tax codes or recalculate.',
        })
    elif vat_header > 0:
        flags.append({
            'severity': 'green',
            'category': 'vat',
            'title': 'Input VAT calculated',
            'detail': f'Input VAT AED {vat_header:,.2f} on subtotal AED {snapshot.get("subtotal", 0):,.2f}.',
        })
    elif any((i.get('vat_rate') or 0) > 0 for i in items):
        flags.append({
            'severity': 'red',
            'category': 'vat',
            'title': 'Line VAT rates but zero header VAT',
            'detail': 'Lines show VAT rates but PO VAT total is zero — recalculate totals.',
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

    system = (
        'You are a UAE procurement reviewer for a fire & safety ERP. '
        'Review purchase order terms & conditions, vendor retention (5%/10% on projects), '
        'supplier details, product line descriptions, and VAT/tax compliance. '
        'Return ONLY valid JSON with this shape: '
        '{"flags":[{"severity":"green|red|amber","category":"terms|retention|vendor|items|vat|general",'
        '"title":"short title","detail":"one or two sentences"}],'
        '"summary":"2-3 sentence overall assessment"} '
        'Use green for OK/pass, red for must-fix issues, amber for warnings.'
    )
    user_payload = json.dumps(snapshot, default=str)[:14000]
    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'Purchase order snapshot:\n{user_payload}'},
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


def evaluate_purchase_order(po, *, force_refresh: bool = False) -> dict:
    """Run AI + heuristic PO review; cache per PO revision."""
    snapshot = build_po_snapshot(po)
    key = _cache_key(po, snapshot)
    if not force_refresh:
        cached = cache.get(key)
        if cached:
            cached['from_cache'] = True
            return cached

    result = _fetch_evaluation_from_openai(snapshot)
    result['from_cache'] = False
    result['po_number'] = snapshot.get('po_number', '')
    cache.set(key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def get_cached_po_evaluation(po) -> dict | None:
    snapshot = build_po_snapshot(po)
    key = _cache_key(po, snapshot)
    cached = cache.get(key)
    if cached:
        cached['from_cache'] = True
    return cached
