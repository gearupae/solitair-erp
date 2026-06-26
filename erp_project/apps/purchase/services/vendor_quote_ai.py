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

MAX_EXTRACT_CHARS = 10_000
MAX_QUOTES_JSON_CHARS = 22_000
MAX_HISTORY_JSON_CHARS = 8_000
CACHE_HOURS = 24
CACHE_PREFIX = 'pr_vendor_quote_ai:'


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


def _django_cache_key(pr: PurchaseRequest, attachments: list[PurchaseRequestAttachment]) -> str:
    return f'{CACHE_PREFIX}{_analysis_cache_key(pr, attachments)}'


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


def _load_persisted_analysis(
    pr: PurchaseRequest,
    attachments: list[PurchaseRequestAttachment],
) -> dict | None:
    if not attachments or not pr.vendor_quote_analysis or not pr.vendor_quote_analysis_key:
        return None
    key = _analysis_cache_key(pr, attachments)
    if pr.vendor_quote_analysis_key != key:
        return None
    result = dict(pr.vendor_quote_analysis)
    result['from_cache'] = True
    result['ok'] = True
    if pr.vendor_quote_analysis_at and not result.get('generated_at'):
        result['generated_at'] = pr.vendor_quote_analysis_at.isoformat()
    return result


def _persist_analysis(
    pr: PurchaseRequest,
    attachments: list[PurchaseRequestAttachment],
    result: dict,
) -> None:
    key = _analysis_cache_key(pr, attachments)
    store = {k: v for k, v in result.items() if k not in ('ok', 'from_cache')}
    now = timezone.now()
    PurchaseRequest.objects.filter(pk=pr.pk).update(
        vendor_quote_analysis=store,
        vendor_quote_analysis_at=now,
        vendor_quote_analysis_key=key,
    )
    pr.vendor_quote_analysis = store
    pr.vendor_quote_analysis_at = now
    pr.vendor_quote_analysis_key = key


def invalidate_pr_quote_analysis(pr: PurchaseRequest) -> None:
    """Clear stored analysis when vendor quote files change."""
    if not pr.vendor_quote_analysis and not pr.vendor_quote_analysis_key:
        return
    PurchaseRequest.objects.filter(pk=pr.pk).update(
        vendor_quote_analysis=None,
        vendor_quote_analysis_at=None,
        vendor_quote_analysis_key='',
    )
    pr.vendor_quote_analysis = None
    pr.vendor_quote_analysis_at = None
    pr.vendor_quote_analysis_key = ''


def _fetch_analysis_from_openai(
    pr: PurchaseRequest,
    attachments: list[PurchaseRequestAttachment],
    extracted: list[dict],
    price_history: list[dict],
) -> dict:
    from apps.core.openai_gateway import call_openai_json
    from apps.inventory.utils import is_ai_available

    if not is_ai_available():
        raise OpenAINotConfigured(
            'Configure OpenAI API key and AI credits — set OPENAI_API_KEY in .env or recharge in Settings → Company.'
        )

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

    history_json = json.dumps(price_history, ensure_ascii=False)
    if len(history_json) > MAX_HISTORY_JSON_CHARS:
        history_json = history_json[:MAX_HISTORY_JSON_CHARS]

    quotes_json = json.dumps(quotes_payload, ensure_ascii=False)
    if len(quotes_json) > MAX_QUOTES_JSON_CHARS:
        quotes_json = quotes_json[:MAX_QUOTES_JSON_CHARS]

    user_payload = {
        'pr_number': pr.pr_number,
        'company': company,
        'currency_default': 'AED',
        'pr_line_items': pr_items,
        'historical_purchase_prices': json.loads(history_json) if history_json else [],
        'vendor_quote_files': json.loads(quotes_json) if quotes_json else [],
        'module_knowledge': knowledge,
        'tasks': [
            'From each file, identify vendor name, line items, unit/line prices, and grand total.',
            'State lowest overall quote (lowest_total_vendor / lowest_total_amount).',
            'Match line items across ALL quotes; for each product show every vendor price; mark is_lowest on cheapest.',
            'price_history_comparisons: compare quoted prices vs historical averages from past_purchases.',
            'compliance_review: flag unfavorable payment terms, delivery, warranty, penalties, liability.',
            'Recommend single vendor (recommended_vendor + recommended_reason).',
            'Executive summary + 2–4 recommendations + warnings for unreadable/missing data.',
        ],
        'response_schema': {
            'recommended_vendor': '',
            'recommended_reason': '',
            'lowest_total_vendor': '',
            'lowest_total_amount': None,
            'currency': 'AED',
            'vendor_totals': [{'vendor': '', 'total': None, 'attachment_id': None, 'source': 'file', 'is_lowest': False}],
            'item_comparisons': [{
                'item_description': '',
                'quantity': None,
                'unit': '',
                'vendor_prices': [{'vendor': '', 'unit_price': None, 'line_total': None, 'is_lowest': False}],
                'lowest_vendor': '',
            }],
            'price_history_comparisons': [{
                'item_description': '',
                'quoted_vendors': [{'vendor': '', 'unit_price': None}],
                'historical_avg': None,
                'historical_low': None,
                'historical_high': None,
                'trend': 'higher|lower|inline|unknown',
                'comment': '',
            }],
            'compliance_review': {
                'overall_risk': 'low|medium|high',
                'issues': [{'vendor': '', 'severity': '', 'topic': '', 'detail': ''}],
                'favorable_terms': [''],
            },
            'summary': '',
            'recommendations': [],
            'warnings': [],
        },
    }

    system = (
        'Procurement quote analyst. Extract data ONLY from provided vendor_quote_files text. '
        'Reply with JSON matching response_schema keys. Use AED unless documents specify otherwise.'
    )
    data = call_openai_json(
        system=system,
        user_payload=user_payload,
        temperature=0.2,
        feature='vendor_quote_ai',
    )
    if not isinstance(data, dict):
        raise ValueError('AI returned non-object JSON')
    return _normalize_ai_response(data, pr_items, price_history)


def get_cached_pr_quote_analysis(pr: PurchaseRequest) -> dict | None:
    attachments = list(pr.attachments.order_by('id'))
    if not attachments:
        return None

    persisted = _load_persisted_analysis(pr, attachments)
    if persisted:
        return persisted

    cached = cache.get(_django_cache_key(pr, attachments))
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
        persisted = _load_persisted_analysis(pr, attachments)
        if persisted:
            return persisted

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

    price_history = build_pr_purchase_price_history(pr, limit_per_line=5)

    try:
        result = _fetch_analysis_from_openai(pr, attachments, extracted, price_history)
        result['ok'] = True
        _persist_analysis(pr, attachments, result)
        cache.set(
            django_key,
            {k: v for k, v in result.items() if k not in ('ok', 'from_cache')},
            timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()),
        )
        result['from_cache'] = False
        return result
    except OpenAINotConfigured as exc:
        return {'ok': False, 'error': str(exc)}
    except Exception as exc:
        return {
            'ok': False,
            'error': f'AI analysis failed: {exc}',
        }
