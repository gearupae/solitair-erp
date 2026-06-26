"""AI comparison of vendor quotation attachments on purchase requests (file content only)."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from apps.inventory.utils import get_openai_api_key
from apps.purchase.models import PurchaseRequest, PurchaseRequestAttachment
from apps.purchase.services.file_extract import extract_file_text_from_path
from apps.purchase.services.purchase_price_history import build_pr_purchase_price_history

logger = logging.getLogger(__name__)

MAX_EXTRACT_CHARS = 7_500
MAX_QUOTES_JSON_CHARS = 18_000
MAX_HISTORY_JSON_CHARS = 6_000
CACHE_HOURS = 24
CACHE_PREFIX = 'pr_vendor_quote_ai:'
RUNNING_PREFIX = 'pr_vendor_quote_ai:running:'
PHASE_PREFIX = 'pr_vendor_quote_ai:phase:'


class OpenAINotConfigured(Exception):
    pass


class NoExtractableQuoteText(Exception):
    pass


def _vendor_quote_model() -> str:
    from apps.core.openai_gateway import resolve_openai_model

    override = getattr(settings, 'OPENAI_VENDOR_QUOTE_MODEL', '') or ''
    return resolve_openai_model(override)


def _attachment_file_label(att: PurchaseRequestAttachment) -> str:
    name = (att.filename or '').strip()
    if not name and att.file:
        name = Path(att.file.name).name
    return name or f'Attachment #{att.pk}'


def _read_attachment_text(att: PurchaseRequestAttachment) -> str:
    cached = (getattr(att, 'extracted_text', None) or '').strip()
    if cached and not cached.startswith('['):
        return cached
    if not att.file:
        return ''
    filename = att.filename or att.file.name
    return extract_file_text_from_path(att.file.path, filename)


def cache_attachment_extracted_text(att: PurchaseRequestAttachment) -> str:
    """Extract and persist text on the attachment row (call after upload)."""
    text = _read_attachment_text(att)
    if not text:
        return ''
    store = text[:MAX_EXTRACT_CHARS * 2]
    if store != (att.extracted_text or ''):
        PurchaseRequestAttachment.objects.filter(pk=att.pk).update(extracted_text=store)
        att.extracted_text = store
    return store


def extract_attachment_text(att: PurchaseRequestAttachment) -> str:
    text = _read_attachment_text(att)
    if text and not text.startswith('[') and not (att.extracted_text or '').strip():
        cache_attachment_extracted_text(att)
    return text


def _extract_attachments_parallel(attachments: list[PurchaseRequestAttachment]) -> list[dict]:
    extracted: list[dict | None] = [None] * len(attachments)

    def _one(idx: int, att: PurchaseRequestAttachment) -> tuple[int, dict]:
        text = extract_attachment_text(att)
        note = ''
        if not text:
            note = 'No text extracted from file.'
        elif text.startswith('[') and text.endswith(']'):
            note = text
            text = ''
        return idx, {
            'attachment_id': att.pk,
            'text': text[:MAX_EXTRACT_CHARS],
            'note': note,
        }

    workers = min(4, max(1, len(attachments)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, i, att) for i, att in enumerate(attachments)]
        for fut in as_completed(futures):
            idx, row = fut.result()
            extracted[idx] = row

    return [row for row in extracted if row is not None]


def _analysis_cache_key(pr: PurchaseRequest, attachments: list[PurchaseRequestAttachment]) -> str:
    parts = [str(pr.pk), str(pr.updated_at or '')]
    for att in attachments:
        parts.extend([str(att.pk), str(att.uploaded_at or ''), att.filename or ''])
    raw = '|'.join(parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _django_cache_key(pr: PurchaseRequest, attachments: list[PurchaseRequestAttachment]) -> str:
    return f'{CACHE_PREFIX}{_analysis_cache_key(pr, attachments)}'


def _running_cache_key(pr_pk: int, analysis_key: str) -> str:
    return f'{RUNNING_PREFIX}{pr_pk}:{analysis_key}'


def _phase_cache_key(pr_pk: int) -> str:
    return f'{PHASE_PREFIX}{pr_pk}'


def _set_phase(pr_pk: int, message: str) -> None:
    cache.set(_phase_cache_key(pr_pk), message, timeout=600)


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
    data['model'] = _vendor_quote_model()
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
    store = {k: v for k, v in result.items() if k not in ('ok', 'from_cache', 'status', 'message')}
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
    cache.delete(_phase_cache_key(pr.pk))


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
        }
        for item in pr.items.all()
    ]

    quotes_payload = []
    for att, ext in zip(attachments, extracted):
        quotes_payload.append({
            'attachment_id': att.pk,
            'filename': _attachment_file_label(att),
            'text': (ext.get('text') or '')[:MAX_EXTRACT_CHARS],
            'note': ext.get('note') or '',
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
        'pr_line_items': pr_items,
        'historical_purchase_prices': json.loads(history_json) if history_json else [],
        'vendor_quote_files': json.loads(quotes_json) if quotes_json else [],
        'module_knowledge': knowledge[:2000] if knowledge else '',
    }

    system = (
        'Procurement quote analyst. Extract numbers ONLY from vendor_quote_files text. '
        'Return JSON with keys: recommended_vendor, recommended_reason, lowest_total_vendor, '
        'lowest_total_amount, currency, vendor_totals[], item_comparisons[], '
        'price_history_comparisons[], compliance_review{overall_risk,issues[],favorable_terms[]}, '
        'summary, recommendations[], warnings[]. Use AED unless documents say otherwise. '
        'Mark is_lowest on cheapest vendor prices. Keep compliance issues concise.'
    )
    _set_phase(pr.pk, 'Analyzing quotes with AI…')
    data = call_openai_json(
        system=system,
        user_payload=user_payload,
        temperature=0.1,
        feature='vendor_quote_ai',
        model=_vendor_quote_model(),
        reasoning_effort='none',
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


def get_vendor_quote_analysis_status(pr: PurchaseRequest) -> dict:
    attachments = list(pr.attachments.order_by('id'))
    if not attachments:
        return {'ok': False, 'status': 'idle', 'error': 'No quote files attached.'}

    persisted = _load_persisted_analysis(pr, attachments)
    if persisted:
        return {**persisted, 'status': 'complete'}

    analysis_key = _analysis_cache_key(pr, attachments)
    if cache.get(_running_cache_key(pr.pk, analysis_key)):
        return {
            'ok': True,
            'status': 'running',
            'message': cache.get(_phase_cache_key(pr.pk)) or 'Analysis in progress…',
        }

    return {'ok': True, 'status': 'idle'}


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

    _set_phase(pr.pk, 'Reading attached quote files…')
    extracted = _extract_attachments_parallel(attachments)
    readable_count = sum(1 for e in extracted if e.get('text'))

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

    price_history = build_pr_purchase_price_history(pr, limit_per_line=4)

    try:
        result = _fetch_analysis_from_openai(pr, attachments, extracted, price_history)
        result['ok'] = True
        _persist_analysis(pr, attachments, result)
        cache.set(
            django_key,
            {k: v for k, v in result.items() if k not in ('ok', 'from_cache', 'status', 'message')},
            timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()),
        )
        result['from_cache'] = False
        cache.delete(_phase_cache_key(pr.pk))
        return result
    except OpenAINotConfigured as exc:
        return {'ok': False, 'error': str(exc)}
    except Exception as exc:
        logger.exception('vendor quote AI failed for PR %s', pr.pk)
        return {
            'ok': False,
            'error': f'AI analysis failed: {exc}',
        }


def _run_analysis_worker(pr_pk: int, force: bool) -> None:
    close_old_connections()
    try:
        pr = PurchaseRequest.objects.get(pk=pr_pk, is_active=True)
        analyze_vendor_quotes(pr, force=force)
    except Exception:
        logger.exception('Background vendor quote analysis failed for PR %s', pr_pk)
    finally:
        try:
            pr = PurchaseRequest.objects.get(pk=pr_pk, is_active=True)
            attachments = list(pr.attachments.order_by('id'))
            analysis_key = _analysis_cache_key(pr, attachments)
            cache.delete(_running_cache_key(pr.pk, analysis_key))
        except Exception:
            pass
        close_old_connections()


def start_vendor_quote_analysis_async(pr: PurchaseRequest, *, force: bool = False) -> dict:
    """Start analysis in a background thread; return immediately."""
    attachments = list(pr.attachments.order_by('id'))
    if not attachments:
        return {
            'ok': False,
            'status': 'error',
            'error': 'Upload at least one vendor quote file (PDF or Excel) before running analysis.',
        }

    if not get_openai_api_key():
        return {
            'ok': False,
            'status': 'error',
            'error': 'OpenAI is not configured. Set OPENAI_API_KEY in your .env file to analyze quote files.',
        }

    if not force:
        persisted = _load_persisted_analysis(pr, attachments)
        if persisted:
            return {**persisted, 'status': 'complete'}

    analysis_key = _analysis_cache_key(pr, attachments)
    running_key = _running_cache_key(pr.pk, analysis_key)
    if cache.get(running_key):
        return {
            'ok': True,
            'status': 'running',
            'message': cache.get(_phase_cache_key(pr.pk)) or 'Analysis already in progress…',
        }

    cache.set(running_key, True, timeout=600)
    _set_phase(pr.pk, 'Starting quote analysis…')
    thread = threading.Thread(
        target=_run_analysis_worker,
        args=(pr.pk, force),
        daemon=True,
        name=f'pr-vendor-quote-ai-{pr.pk}',
    )
    thread.start()
    return {
        'ok': True,
        'status': 'running',
        'message': 'Reading attached quote files…',
    }
