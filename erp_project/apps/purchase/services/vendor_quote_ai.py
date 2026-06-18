"""AI comparison of vendor quotation attachments on purchase requests."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from django.utils import timezone

from apps.inventory.utils import get_openai_api_key
from apps.purchase.models import PurchaseRequest, PurchaseRequestAttachment
from apps.purchase.services.file_extract import extract_file_text_from_path

MAX_EXTRACT_CHARS = 14_000
MAX_PAGES = 25
MAX_EXCEL_ROWS = 600


class OpenAINotConfigured(Exception):
    pass


def _attachment_label(att: PurchaseRequestAttachment) -> str:
    name = (att.filename or '').strip()
    if not name and att.file:
        name = Path(att.file.name).name
    vendor = (att.vendor or '').strip()
    if vendor:
        return f'{vendor} ({name})'
    return name or f'Attachment #{att.pk}'


def extract_attachment_text(att: PurchaseRequestAttachment) -> str:
    """Extract plain text from PDF or Excel vendor quote files."""
    if not att.file:
        return ''

    filename = att.filename or att.file.name
    return extract_file_text_from_path(att.file.path, filename)


def _analysis_cache_key(pr: PurchaseRequest, attachments: list[PurchaseRequestAttachment]) -> str:
    parts = [str(pr.pk), str(pr.updated_at or ''), str(pr.total_amount or '')]
    for att in attachments:
        parts.extend([
            str(att.pk),
            str(att.uploaded_at or ''),
            att.vendor or '',
            str(att.total_price or ''),
            att.filename or '',
        ])
    raw = '|'.join(parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _heuristic_analysis(pr: PurchaseRequest, attachments: list[PurchaseRequestAttachment]) -> dict:
    """Compare manually entered vendor totals when AI is unavailable."""
    vendor_totals = []
    for att in attachments:
        vendor = (att.vendor or '').strip() or _attachment_label(att)
        total = float(att.total_price) if att.total_price is not None else None
        vendor_totals.append({
            'vendor': vendor,
            'total': total,
            'attachment_id': att.pk,
            'source': 'manual',
        })

    with_totals = [v for v in vendor_totals if v['total'] is not None]
    lowest = min(with_totals, key=lambda v: v['total']) if with_totals else None

    pr_items = [
        {
            'description': item.description,
            'quantity': float(item.quantity),
            'unit': item.get_unit_display(),
            'estimated_price': float(item.estimated_price),
        }
        for item in pr.items.all()
    ]

    bullets = []
    if lowest:
        bullets.append(
            f'Lowest entered total: {lowest["vendor"]} at AED {lowest["total"]:,.2f}.'
        )
    else:
        bullets.append('Enter vendor names and totals in the table above, then re-run analysis.')

    if len(with_totals) >= 2:
        spread = max(v['total'] for v in with_totals) - min(v['total'] for v in with_totals)
        bullets.append(f'Spread between quoted totals: AED {spread:,.2f}.')

    return {
        'recommended_vendor': lowest['vendor'] if lowest else '',
        'recommended_reason': bullets[0] if bullets else '',
        'lowest_total_vendor': lowest['vendor'] if lowest else '',
        'lowest_total_amount': lowest['total'] if lowest else None,
        'currency': 'AED',
        'vendor_totals': vendor_totals,
        'item_comparisons': [],
        'summary': ' '.join(bullets),
        'recommendations': bullets,
        'warnings': ['OpenAI not configured — comparing manually entered totals only.'],
        'pr_line_items': pr_items,
        'from_cache': False,
        'generated_at': timezone.now().isoformat(),
    }


def _parse_json_content(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def _fetch_analysis_from_openai(
    pr: PurchaseRequest,
    attachments: list[PurchaseRequestAttachment],
    extracted: list[dict],
) -> dict:
    api_key = get_openai_api_key()
    if not api_key:
        raise OpenAINotConfigured('Configure OpenAI API key in Settings → Company')

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
            'label': _attachment_label(att),
            'vendor_name_entered': att.vendor or '',
            'total_price_entered': float(att.total_price) if att.total_price is not None else None,
            'filename': att.filename or '',
            'extracted_text': (ext.get('text') or '')[:MAX_EXTRACT_CHARS],
            'extraction_note': ext.get('note') or '',
        })

    prompt = (
        f'You are a procurement analyst comparing vendor quotations for purchase request '
        f'{pr.pr_number} (currency AED unless quotes state otherwise).\n\n'
        f'PR line items requested:\n{json.dumps(pr_items, ensure_ascii=False)}\n\n'
        f'Vendor quote files (extracted text + any manually entered vendor/total):\n'
        f'{json.dumps(quotes_payload, ensure_ascii=False)[:28000]}\n\n'
        'Tasks:\n'
        '1. Identify each vendor quote and its grand total.\n'
        '2. State which vendor has the lowest overall total.\n'
        '3. Match line items across ALL quotes (even if descriptions differ slightly). '
        'For EVERY item found in any quote, list each vendor\'s unit price and line total. '
        'Mark is_lowest=true on the cheapest price for that item.\n'
        '4. If different vendors win on different line items, note that a single-vendor '
        'choice may not be cheapest — mention split sourcing only if materially cheaper.\n'
        '5. Recommend which single vendor quote to accept (recommended_vendor) with a '
        'one-sentence recommended_reason (lowest total, best coverage, or best value).\n'
        '6. Note gaps (items only in some quotes, unreadable files, missing totals).\n'
        '7. Give a short executive summary and 2–4 practical recommendations.\n\n'
        'Return ONLY valid JSON with this shape:\n'
        '{"recommended_vendor": "<name>", "recommended_reason": "<one sentence>", '
        '"lowest_total_vendor": "<name>", "lowest_total_amount": <number|null>, '
        '"currency": "AED", '
        '"vendor_totals": [{"vendor": "<name>", "total": <number|null>, '
        '"attachment_id": <int|null>, "source": "file|manual|both", "is_lowest": <bool>}], '
        '"item_comparisons": [{"item_description": "<str>", "quantity": <number|null>, '
        '"unit": "<str>", "vendor_prices": [{"vendor": "<name>", "unit_price": <number|null>, '
        '"line_total": <number|null>, "is_lowest": <bool>}], "lowest_vendor": "<name>"}], '
        '"summary": "<2-4 sentences>", "recommendations": ["..."], "warnings": ["..."]}'
    )

    body = json.dumps(
        {
            'model': 'gpt-4o-mini',
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'Procurement quote comparison assistant. Reply with JSON only. '
                        'Use AED unless another currency is explicit in the documents.'
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    content = payload['choices'][0]['message']['content']
    data = _parse_json_content(content)

    data.setdefault('currency', 'AED')
    data.setdefault('recommended_vendor', data.get('lowest_total_vendor') or '')
    data.setdefault('recommended_reason', '')
    data.setdefault('vendor_totals', [])
    data.setdefault('item_comparisons', [])
    data.setdefault('summary', '')
    data.setdefault('recommendations', [])
    data.setdefault('warnings', [])
    data['pr_line_items'] = pr_items
    data['from_cache'] = False
    data['generated_at'] = timezone.now().isoformat()
    return data


# Simple process-level cache keyed by attachment fingerprint (avoids DB migration).
_analysis_cache: dict[str, dict] = {}


def analyze_vendor_quotes(pr: PurchaseRequest, *, force: bool = False) -> dict:
    """Extract quote file contents and return AI comparison (with heuristic fallback)."""
    attachments = list(
        pr.attachments.select_related('uploaded_by').order_by('id')
    )
    if not attachments:
        return {
            'ok': False,
            'error': 'Upload at least one vendor quote file before running analysis.',
        }

    cache_key = _analysis_cache_key(pr, attachments)
    if not force and cache_key in _analysis_cache:
        cached = dict(_analysis_cache[cache_key])
        cached['from_cache'] = True
        cached['ok'] = True
        return cached

    extracted = []
    for att in attachments:
        text = extract_attachment_text(att)
        note = ''
        if not text:
            note = 'No text extracted from file.'
        elif text.startswith('[') and text.endswith(']'):
            note = text
            text = ''
        extracted.append({'attachment_id': att.pk, 'text': text[:MAX_EXTRACT_CHARS], 'note': note})

    try:
        result = _fetch_analysis_from_openai(pr, attachments, extracted)
        result['ok'] = True
        _analysis_cache[cache_key] = result
        return result
    except OpenAINotConfigured:
        result = _heuristic_analysis(pr, attachments)
        result['ok'] = True
        _analysis_cache[cache_key] = result
        return result
    except Exception as exc:
        result = _heuristic_analysis(pr, attachments)
        result['warnings'] = list(result.get('warnings') or []) + [
            f'AI analysis failed ({exc}). Showing manual total comparison only.',
        ]
        result['ok'] = True
        _analysis_cache[cache_key] = result
        return result
