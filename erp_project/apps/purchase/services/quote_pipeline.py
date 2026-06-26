"""Two-stage vendor quote AI: cheap extract → reasoning compare (no raw PDF to LLM)."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

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


def _extract_model() -> str:
    from apps.core.openai_gateway import resolve_openai_model

    override = getattr(settings, 'OPENAI_VENDOR_QUOTE_EXTRACT_MODEL', '') or 'gpt-4o-mini'
    return resolve_openai_model(override)


def _reason_model() -> str:
    from apps.core.openai_gateway import resolve_openai_model

    override = (
        getattr(settings, 'OPENAI_VENDOR_QUOTE_REASON_MODEL', '')
        or getattr(settings, 'OPENAI_VENDOR_QUOTE_MODEL', '')
        or ''
    )
    return resolve_openai_model(override or 'gpt-5.5')


def extract_structured_quote(
    *,
    text: str,
    filename: str,
    attachment_id: int,
) -> dict:
    """Stage 1: cheap model → fixed schema from plain text only."""
    from apps.core.openai_gateway import call_openai_json

    snippet = (text or '')[:MAX_TEXT_FOR_EXTRACT]
    payload = {
        'attachment_id': attachment_id,
        'filename': filename,
        'quote_text': snippet,
    }
    data = call_openai_json(
        system=QUOTE_EXTRACT_INSTRUCTIONS,
        user_payload=payload,
        temperature=0,
        feature='vendor_quote_extract',
        model=_extract_model(),
        reasoning_effort='none',
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
    """Stage 2: reasoning model compares small JSON blobs only."""
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
        'extract_model': _extract_model(),
        'reason_model': _reason_model(),
        'quote_count': len(structured_quotes),
    }
    return data


def _structured_cache_valid(att: PurchaseRequestAttachment, text: str) -> dict | None:
    raw = getattr(att, 'structured_quote_json', None)
    if not raw or not isinstance(raw, dict):
        return None
    text_hash = str(hash(text[:MAX_TEXT_FOR_EXTRACT]))
    if raw.get('_source_text_hash') != text_hash:
        return None
    return {k: v for k, v in raw.items() if not k.startswith('_')}


def _persist_structured(att: PurchaseRequestAttachment, text: str, structured: dict) -> None:
    store = dict(structured)
    store['_source_text_hash'] = str(hash(text[:MAX_TEXT_FOR_EXTRACT]))
    PurchaseRequestAttachment.objects.filter(pk=att.pk).update(structured_quote_json=store)
    att.structured_quote_json = store


def extract_quotes_parallel(
    attachments: list[PurchaseRequestAttachment],
    extracted_rows: list[dict],
    *,
    set_phase=None,
    pr_pk: int | None = None,
) -> list[dict]:
    """Run stage-1 extraction in parallel; use DB cache when text unchanged."""
    att_by_id = {att.pk: att for att in attachments}
    out: list[dict] = []

    def _one(row: dict) -> dict:
        att = att_by_id.get(row['attachment_id'])
        if not att:
            raise ValueError(f"Attachment {row['attachment_id']} not found")
        text = row.get('text') or ''
        cached = _structured_cache_valid(att, text)
        if cached:
            return cached
        structured = extract_structured_quote(
            text=text,
            filename=row.get('filename') or _attachment_label(att),
            attachment_id=att.pk,
        )
        _persist_structured(att, text, structured)
        return structured

    rows = []
    for row in extracted_rows:
        if not row.get('text'):
            continue
        att = att_by_id.get(row['attachment_id'])
        if not att:
            continue
        rows.append({**row, 'filename': row.get('filename') or _attachment_label(att)})

    if not rows:
        raise ValueError('No readable quote text to extract.')

    workers = min(4, max(1, len(rows)))
    if set_phase and pr_pk is not None:
        set_phase(pr_pk, f'Extracting quote data ({len(rows)} file(s), fast model)…')

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
