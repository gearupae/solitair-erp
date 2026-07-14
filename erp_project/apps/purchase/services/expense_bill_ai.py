"""AI extraction of vendor bill details from receipt / invoice files."""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.files.uploadedfile import UploadedFile

from apps.inventory.utils import get_openai_api_key
from apps.purchase.services.file_extract import extract_file_text_from_path

MAX_EXTRACT_CHARS = 12_000
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.xlsx', '.xls'}

CATEGORY_MAP = {
    'travel': 'travel',
    'meals': 'meals',
    'meal': 'meals',
    'food': 'meals',
    'accommodation': 'accommodation',
    'hotel': 'accommodation',
    'transport': 'transport',
    'taxi': 'transport',
    'fuel': 'transport',
    'office': 'office',
    'communication': 'communication',
    'phone': 'communication',
}


def _parse_json_content(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def _parse_bill_date(raw) -> date | None:
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()[:10]
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _map_category(hint: str) -> str:
    key = (hint or '').strip().lower()
    for fragment, cat in CATEGORY_MAP.items():
        if fragment in key:
            return cat
    return 'other'


def _heuristic_extract(filename: str, text: str) -> dict:
    stem = Path(filename).stem.replace('_', ' ').replace('-', ' ').strip()
    return {
        'vendor_name': stem[:200] or 'Unknown vendor',
        'total_amount': None,
        'bill_date': None,
        'currency': 'AED',
        'category_hint': 'other',
        'description': stem[:500] or filename,
        'confidence': 'low',
        'warnings': ['AI not configured — enter amounts manually after submission.'],
    }


def extract_bill_from_uploaded_file(uploaded: UploadedFile) -> dict:
    """
    Extract vendor name, total, and date from one bill file.
    Returns dict suitable for creating an ExpenseClaimItem.
    """
    filename = getattr(uploaded, 'name', '') or 'bill'
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {
            'ok': False,
            'error': f'Unsupported file type: {filename}. Use PDF, image, or Excel.',
            'filename': filename,
        }

    text = ''
    if ext in {'.pdf', '.xlsx', '.xls'}:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
            for chunk in uploaded.chunks():
                tmp.write(chunk)
            tmp.flush()
            text = extract_file_text_from_path(tmp.name, filename)

    from apps.core.openai_gateway import call_openai_raw, get_default_ai_model
    from apps.inventory.utils import get_openai_api_key, is_ai_available

    if not is_ai_available():
        data = _heuristic_extract(filename, text)
        data['ok'] = True
        data['filename'] = filename
        return data

    import base64

    user_parts = [
        {
            'type': 'text',
            'text': (
                f'Extract expense bill / receipt details from file "{filename}". '
                'Return ONLY valid JSON: '
                '{"vendor_name": "<merchant/vendor>", "total_amount": <number|null>, '
                '"bill_date": "YYYY-MM-DD|null", "currency": "AED", '
                '"category_hint": "travel|meals|accommodation|transport|office|communication|other", '
                '"description": "<short line for expense claim>", "confidence": "high|medium|low"}'
            ),
        },
    ]

    if text and not text.startswith('['):
        user_parts.append({
            'type': 'text',
            'text': f'Extracted document text:\n{text[:MAX_EXTRACT_CHARS]}',
        })
    elif ext in {'.jpg', '.jpeg', '.png', '.webp'}:
        uploaded.seek(0)
        raw = uploaded.read()
        mime = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
        }.get(ext, 'image/jpeg')
        b64 = base64.standard_b64encode(raw).decode('ascii')
        user_parts.append({
            'type': 'image_url',
            'image_url': {'url': f'data:{mime};base64,{b64}'},
        })
    elif text:
        user_parts.append({'type': 'text', 'text': text[:MAX_EXTRACT_CHARS]})

    body = {
        'model': get_default_ai_model(),
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You extract structured data from expense receipts and tax invoices. '
                    'Reply with JSON only. Amounts are numbers without currency symbols. '
                    'Use AED unless another currency is explicit.'
                ),
            },
            {'role': 'user', 'content': user_parts},
        ],
        'temperature': 0.1,
    }

    try:
        payload = call_openai_raw(body, feature='expense_bill_ai')
        content = payload['choices'][0]['message']['content']
        data = _parse_json_content(content)
    except Exception as exc:
        data = _heuristic_extract(filename, text)
        data['warnings'] = [f'AI extraction failed ({exc}). Review amounts manually.']

    amount = data.get('total_amount')
    if amount is not None:
        try:
            amount = float(Decimal(str(amount)).quantize(Decimal('0.01')))
        except (InvalidOperation, TypeError, ValueError):
            amount = None

    bill_date = _parse_bill_date(data.get('bill_date'))

    return {
        'ok': True,
        'filename': filename,
        'vendor_name': (data.get('vendor_name') or '').strip()[:200] or 'Unknown vendor',
        'total_amount': amount,
        'bill_date': bill_date.isoformat() if bill_date else None,
        'currency': (data.get('currency') or 'AED').strip()[:10],
        'category': _map_category(data.get('category_hint') or ''),
        'description': (data.get('description') or data.get('vendor_name') or filename).strip()[:500],
        'confidence': (data.get('confidence') or 'medium')[:20],
        'warnings': data.get('warnings') or [],
    }


def build_item_description(extracted: dict) -> str:
    vendor = extracted.get('vendor_name') or 'Vendor'
    desc = extracted.get('description') or vendor
    if vendor.lower() not in desc.lower():
        return f'{vendor} — {desc}'[:500]
    return desc[:500]
