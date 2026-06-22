"""AI comparison of vendor quotation attachments on purchase requests (file content only)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.inventory.utils import get_openai_api_key
from apps.purchase.models import PurchaseRequest, PurchaseRequestAttachment
from apps.purchase.services.file_extract import extract_file_text_from_path
from apps.purchase.services.purchase_price_history import build_pr_purchase_price_history

MAX_EXTRACT_CHARS = 14_000
OPENAI_TIMEOUT = 180


class OpenAINotConfigured(Exception):
    pass


class NoExtractableQuoteText(Exception):
    pass


def _attachment_file_label(att: PurchaseRequestAttachment) -> str:
    name = (att.filename or '').strip()
    if not name and att.file:
        name = Path(att.file.name).name
    return name or f'Attachment #{att.pk}'


def extract_attachment_text(att: PurchaseRequestAttachment) -> str:
    if not att.file:
        return ''
    filename = att.filename or att.file.name
    return extract_file_text_from_path(att.file.path, filename)


def _analysis_cache_key(pr: PurchaseRequest, attachments: list[PurchaseRequestAttachment]) -> str:
    parts = [str(pr.pk), str(pr.updated_at or '')]
    for att in attachments:
        parts.extend([str(att.pk), str(att.uploaded_at or ''), att.filename or ''])
    raw = '|'.join(parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _company_context() -> dict:
    try:
        from apps.settings_app.models import CompanySettings

        cs = CompanySettings.objects.first()
        if cs:
            return {
                'company_name': cs.company_name or 'Our company',
                'country': 'United Arab Emirates',
            }
    except Exception:
        pass
    return {'company_name': 'Our company', 'country': 'United Arab Emirates'}


def _parse_json_content(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def _normalize_ai_response(data: dict, pr_items: list, price_history: list) -> dict:
    data.setdefault('currency', 'AED')
    data.setdefault('recommended_vendor', data.get('lowest_total_vendor') or '')
    data.setdefault('recommended_reason', '')
    data.setdefault('vendor_totals', [])
    data.setdefault('item_comparisons', [])
    data.setdefault('price_history_comparisons', [])
    data.setdefault('compliance_review', {'overall_risk': '', 'issues': [], 'favorable_terms': []})
    data.setdefault('summary', '')
    data.setdefault('recommendations', [])
    data.setdefault('warnings', [])
    data['pr_line_items'] = pr_items
    data['purchase_price_history'] = price_history
    data['from_cache'] = False
    data['generated_at'] = timezone.now().isoformat()
    return data


def _fetch_analysis_from_openai(
    pr: PurchaseRequest,
    attachments: list[PurchaseRequestAttachment],
    extracted: list[dict],
    price_history: list[dict],
) -> dict:
    api_key = get_openai_api_key()
    if not api_key:
        raise OpenAINotConfigured('Configure OpenAI API key — set OPENAI_API_KEY in .env')

    import urllib.request

    pr_items = [
        {
            'description': item.description,
            'quantity': float(item.quantity),
            'unit': item.get_unit_display(),
            'estimated_unit_price': float(item.estimated_price),
            'estimated_line_total': float(item.total),
        }
        for item in pr.items.all()
    ]

    quotes_payload = []
    for att, ext in zip(attachments, extracted):
        quotes_payload.append({
            'attachment_id': att.pk,
            'filename': _attachment_file_label(att),
            'extracted_text': (ext.get('text') or '')[:MAX_EXTRACT_CHARS],
            'extraction_note': ext.get('note') or '',
        })

    company = _company_context()

    from apps.core.ai_knowledge import get_ai_knowledge_prompt_block
    from apps.core.models import AiModuleKnowledge

    knowledge = get_ai_knowledge_prompt_block(AiModuleKnowledge.MODULE_PURCHASE_REQUEST)

    prompt = (
        f'You are a procurement analyst for {company["company_name"]} ({company["country"]}). '
        f'Compare vendor quotations for purchase request {pr.pr_number}. Currency: AED unless stated otherwise.\n\n'
        'IMPORTANT: Use ONLY the extracted text from attached quote files below. '
        'Ignore any manually entered vendor names or totals — they are not provided.\n\n'
        f'PR line items requested:\n{json.dumps(pr_items, ensure_ascii=False)}\n\n'
        f'Historical purchase prices for similar items (from past PO receipts):\n'
        f'{json.dumps(price_history, ensure_ascii=False)[:12000]}\n\n'
        f'Attached vendor quote files (extracted text only):\n'
        f'{json.dumps(quotes_payload, ensure_ascii=False)[:32000]}\n\n'
        'Tasks:\n'
        '1. From each file, identify vendor name, line items, unit/line prices, and grand total.\n'
        '2. State lowest overall quote (lowest_total_vendor / lowest_total_amount).\n'
        '3. Match line items across ALL quotes; for each product show every vendor price; mark is_lowest on cheapest.\n'
        '4. price_history_comparisons: for each matched item, compare quoted prices vs historical_avg/low/high '
        'from past_purchases. Say if quote is higher, lower, or in line with history (trend: higher|lower|inline|unknown).\n'
        '5. compliance_review: read payment terms, delivery, warranty, penalties, liability, exclusions in each quote. '
        'Flag anything unfavorable or risky for the buyer company in issues[] (vendor, severity low|medium|high, topic, detail). '
        'List favorable_terms[] where applicable.\n'
        '6. Recommend single vendor (recommended_vendor + recommended_reason).\n'
        '7. Executive summary + 2–4 recommendations + warnings for unreadable/missing data.\n\n'
        f'{knowledge}\n\n'
        'Return ONLY valid JSON:\n'
        '{"recommended_vendor":"","recommended_reason":"","lowest_total_vendor":"","lowest_total_amount":null,'
        '"currency":"AED",'
        '"vendor_totals":[{"vendor":"","total":null,"attachment_id":null,"source":"file","is_lowest":false}],'
        '"item_comparisons":[{"item_description":"","quantity":null,"unit":"",'
        '"vendor_prices":[{"vendor":"","unit_price":null,"line_total":null,"is_lowest":false}],'
        '"lowest_vendor":""}],'
        '"price_history_comparisons":[{"item_description":"","quoted_vendors":[{"vendor":"","unit_price":null}],'
        '"historical_avg":null,"historical_low":null,"historical_high":null,"trend":"higher|lower|inline|unknown",'
        '"comment":""}],'
        '"compliance_review":{"overall_risk":"low|medium|high","issues":[{"vendor":"","severity":"","topic":"","detail":""}],'
        '"favorable_terms":[""]},'
        '"summary":"","recommendations":[],"warnings":[]}'
    )

    body = json.dumps(
        {
            'model': 'gpt-4o-mini',
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'Procurement quote analyst. Extract data only from provided file text. '
                        'Reply with JSON only. Use AED unless documents specify otherwise.'
                    ),
                },
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.2,
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
    with urllib.request.urlopen(req, timeout=OPENAI_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    content = payload['choices'][0]['message']['content']
    data = _parse_json_content(content)
    return _normalize_ai_response(data, pr_items, price_history)

CACHE_HOURS = 24
CACHE_PREFIX = 'pr_vendor_quote_ai:'


def _django_cache_key(pr: PurchaseRequest, attachments: list[PurchaseRequestAttachment]) -> str:
    return f'{CACHE_PREFIX}{_analysis_cache_key(pr, attachments)}'


def get_cached_pr_quote_analysis(pr: PurchaseRequest) -> dict | None:
    attachments = list(pr.attachments.order_by('id'))
    if not attachments:
        return None
    key = _django_cache_key(pr, attachments)
    cached = cache.get(key)
    if cached:
        cached = dict(cached)
        cached['from_cache'] = True
        cached['ok'] = True
        return cached
    return None


def analyze_vendor_quotes(pr: PurchaseRequest, *, force: bool = False) -> dict:
    """Extract quote files and return AI comparison (OpenAI required)."""
    attachments = list(pr.attachments.select_related('uploaded_by').order_by('id'))
    if not attachments:
        return {
            'ok': False,
            'error': 'Upload at least one vendor quote file (PDF or Excel) before running analysis.',
        }

    if not get_openai_api_key():
        return {
            'ok': False,
            'error': 'OpenAI is not configured. Set OPENAI_API_KEY in your .env file to analyze quote files.',
        }

    django_key = _django_cache_key(pr, attachments)
    if not force:
        cached = cache.get(django_key)
        if cached:
            cached = dict(cached)
            cached['from_cache'] = True
            cached['ok'] = True
            return cached

    extracted = []
    readable_count = 0
    for att in attachments:
        text = extract_attachment_text(att)
        note = ''
        if not text:
            note = 'No text extracted from file.'
        elif text.startswith('[') and text.endswith(']'):
            note = text
            text = ''
        else:
            readable_count += 1
        extracted.append({'attachment_id': att.pk, 'text': text[:MAX_EXTRACT_CHARS], 'note': note})

    if readable_count == 0:
        notes = [e.get('note') for e in extracted if e.get('note')]
        return {
            'ok': False,
            'error': (
                'Could not read text from any attached file. '
                'Use searchable PDF or Excel (.xlsx). '
                + (' '.join(notes[:3]) if notes else '')
            ),
        }

    price_history = build_pr_purchase_price_history(pr)

    try:
        result = _fetch_analysis_from_openai(pr, attachments, extracted, price_history)
        result['ok'] = True
        cache.set(
            django_key,
            result,
            timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()),
        )
        return result
    except OpenAINotConfigured as exc:
        return {'ok': False, 'error': str(exc)}
    except Exception as exc:
        return {
            'ok': False,
            'error': f'AI analysis failed: {exc}',
        }
