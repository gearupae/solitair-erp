"""Vendor quote AI: GPT mini reads files → compares quotes (no OCR)."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from apps.purchase.models import PurchaseRequestAttachment
from apps.purchase.services.quote_schemas import (
    PROMPT_CACHE_KEY_COMPARE,
    PROMPT_CACHE_KEY_EXTRACT,
    QUOTE_COMPARE_INSTRUCTIONS,
    QUOTE_COMPARISON_SCHEMA,
    QUOTE_EXTRACT_INSTRUCTIONS,
    QUOTE_EXTRACTION_SCHEMA,
)

logger = logging.getLogger(__name__)

MAX_TEXT_FOR_EXTRACT = 6_000


def _quote_model() -> str:
    from apps.core.openai_gateway import get_default_ai_model

    return get_default_ai_model()


def _extract_model() -> str:
    return _quote_model()


def _reason_model() -> str:
    return _quote_model()


def extract_structured_quote(
    *,
    text: str,
    filename: str,
    attachment_id: int,
    images_base64: list[str] | None = None,
) -> dict:
    """Read one quote file with GPT mini (text and/or page images)."""
    from apps.core.openai_gateway import call_openai_json, call_openai_json_with_images

    snippet = (text or '')[:MAX_TEXT_FOR_EXTRACT]
    payload = {
        'attachment_id': attachment_id,
        'filename': filename,
        'quote_text': snippet,
        'has_page_images': bool(images_base64),
    }
    user_text = json.dumps(payload, default=str, ensure_ascii=False)
    model = _extract_model()
    images = images_base64 or []

    if images:
        data = call_openai_json_with_images(
            system=QUOTE_EXTRACT_INSTRUCTIONS,
            user_text=user_text,
            images_base64=images,
            temperature=0,
            feature='vendor_quote_extract',
            model=model,
            reasoning_effort='low',
            json_schema=QUOTE_EXTRACTION_SCHEMA,
            json_schema_name='vendor_quote_extraction',
            prompt_cache_key=PROMPT_CACHE_KEY_EXTRACT,
            json_schema_strict=False,
        )
    else:
        data = call_openai_json(
            system=QUOTE_EXTRACT_INSTRUCTIONS,
            user_payload=payload,
            temperature=0,
            feature='vendor_quote_extract',
            model=model,
            reasoning_effort='low',
            json_schema=QUOTE_EXTRACTION_SCHEMA,
            json_schema_name='vendor_quote_extraction',
            prompt_cache_key=PROMPT_CACHE_KEY_EXTRACT,
            json_schema_strict=False,
        )
    if not isinstance(data, dict):
        raise ValueError('Quote extraction returned non-object JSON')
    data['attachment_id'] = attachment_id
    data['source_filename'] = filename
    return data


def compare_structured_quotes(
    *,
    pr_number: str,
    company: dict,
    pr_line_items: list,
    price_history: list,
    structured_quotes: list[dict],
    module_knowledge: str = '',
) -> dict:
    """GPT mini compares structured quote data."""
    from apps.core.openai_gateway import call_openai_json

    payload = {
        'pr_number': pr_number,
        'company': company,
        'pr_line_items': pr_line_items,
        'historical_purchase_prices': price_history,
        'vendor_quotes_structured': structured_quotes,
        'module_knowledge': (module_knowledge or '')[:1500],
    }
    data = call_openai_json(
        system=QUOTE_COMPARE_INSTRUCTIONS,
        user_payload=payload,
        temperature=0.1,
        feature='vendor_quote_compare',
        model=_reason_model(),
        reasoning_effort='low',
        json_schema=QUOTE_COMPARISON_SCHEMA,
        json_schema_name='vendor_quote_comparison',
        prompt_cache_key=PROMPT_CACHE_KEY_COMPARE,
        json_schema_strict=False,
    )
    if not isinstance(data, dict):
        raise ValueError('Quote comparison returned non-object JSON')
    data['pipeline'] = {
        'model': _quote_model(),
        'quote_count': len(structured_quotes),
    }
    return data


def _structured_cache_valid(att: PurchaseRequestAttachment, content_key: str) -> dict | None:
    raw = getattr(att, 'structured_quote_json', None)
    if not raw or not isinstance(raw, dict):
        return None
    if raw.get('_source_content_key') != content_key:
        return None
    return {k: v for k, v in raw.items() if not k.startswith('_')}


def _persist_structured(att: PurchaseRequestAttachment, content_key: str, structured: dict) -> None:
    store = dict(structured)
    store['_source_content_key'] = content_key
    PurchaseRequestAttachment.objects.filter(pk=att.pk).update(structured_quote_json=store)
    att.structured_quote_json = store


def _content_cache_key(row: dict) -> str:
    text = (row.get('text') or '')[:MAX_TEXT_FOR_EXTRACT]
    img_count = len(row.get('images') or [])
    return f'{text}|img:{img_count}'


def extract_quotes_parallel(
    attachments: list[PurchaseRequestAttachment],
    file_rows: list[dict],
    *,
    set_phase=None,
    pr_pk: int | None = None,
) -> list[dict]:
    """GPT mini reads each quote file in parallel."""
    att_by_id = {att.pk: att for att in attachments}
    out: list[dict] = []

    def _one(row: dict) -> dict:
        att = att_by_id.get(row['attachment_id'])
        if not att:
            raise ValueError(f"Attachment {row['attachment_id']} not found")
        content_key = _content_cache_key(row)
        cached = _structured_cache_valid(att, content_key)
        if cached:
            return cached
        structured = extract_structured_quote(
            text=row.get('text') or '',
            filename=row.get('filename') or _attachment_label(att),
            attachment_id=att.pk,
            images_base64=row.get('images') or None,
        )
        _persist_structured(att, content_key, structured)
        return structured

    rows = []
    for row in file_rows:
        if not row.get('has_content'):
            continue
        att = att_by_id.get(row['attachment_id'])
        if not att:
            continue
        rows.append({**row, 'filename': row.get('filename') or _attachment_label(att)})

    if not rows:
        raise ValueError('No quote files could be prepared for AI analysis.')

    workers = min(4, max(1, len(rows)))
    if set_phase and pr_pk is not None:
        set_phase(pr_pk, f'Running analysis — Gearup AI reading {len(rows)} quote file(s)…')

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, row) for row in rows]
        for fut in as_completed(futures):
            out.append(fut.result())

    return out


def _attachment_label(att: PurchaseRequestAttachment) -> str:
    from pathlib import Path

    name = (att.filename or '').strip()
    if not name and att.file:
        name = Path(att.file.name).name
    return name or f'Attachment #{att.pk}'
