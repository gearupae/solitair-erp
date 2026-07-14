"""Central OpenAI API gateway with company-wide token quota enforcement."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F

OPENAI_MODEL = getattr(settings, 'OPENAI_MODEL', 'gpt-5.4-mini')
OPENAI_CHAT_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses'
OPENAI_REQUEST_TIMEOUT = 180


class OpenAINotConfigured(Exception):
    pass


class AiQuotaExceeded(Exception):
    """Raised when the company AI token allowance is exhausted."""


def get_default_ai_model() -> str:
    """Standard ERP AI model (gpt-5.4-mini unless OPENAI_MODEL is overridden)."""
    return resolve_openai_model('')


def resolve_openai_model(override: str = '') -> str:
    model = (override or '').strip() or OPENAI_MODEL
    return model or 'gpt-5.4-mini'


def resolve_reasoning_effort(override: str = '') -> str:
    effort = (override or '').strip() or getattr(settings, 'OPENAI_REASONING_EFFORT', 'none')
    return effort or 'none'


def parse_openai_json(content: str) -> dict | list:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def get_wallet() -> dict:
    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    limit = int(cs.ai_token_limit or 0)
    used = int(cs.ai_tokens_used or 0)
    remaining = max(0, limit - used)
    pct = round((used / limit) * 100, 1) if limit > 0 else 0.0
    return {
        'token_limit': limit,
        'tokens_used': used,
        'tokens_remaining': remaining,
        'usage_percent': pct,
        'has_quota': remaining > 0,
    }


def has_ai_quota(min_tokens: int = 1) -> bool:
    wallet = get_wallet()
    return wallet['tokens_remaining'] >= min_tokens


def ensure_ai_available(min_tokens: int = 1) -> None:
    from apps.inventory.utils import get_openai_api_key

    if not get_openai_api_key():
        raise OpenAINotConfigured('Configure OpenAI API key — set OPENAI_API_KEY in .env')
    if not has_ai_quota(min_tokens):
        raise AiQuotaExceeded(
            'AI token limit reached. Recharge AI credits in Settings → Company to continue.'
        )


@transaction.atomic
def consume_ai_tokens(
    total_tokens: int,
    *,
    feature: str = '',
    model: str = OPENAI_MODEL,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    from apps.settings_app.models import AiTokenUsageLog, CompanySettings

    total = max(0, int(total_tokens or 0))
    if total <= 0:
        return

    cs = CompanySettings.objects.select_for_update().get(pk=1)
    used = int(cs.ai_tokens_used or 0)
    limit = int(cs.ai_token_limit or 0)
    if used + total > limit:
        raise AiQuotaExceeded(
            'AI token limit reached during this request. Recharge AI credits in Settings → Company.'
        )

    CompanySettings.objects.filter(pk=1).update(ai_tokens_used=F('ai_tokens_used') + total)
    AiTokenUsageLog.objects.create(
        tokens=total,
        prompt_tokens=max(0, int(prompt_tokens or 0)),
        completion_tokens=max(0, int(completion_tokens or 0)),
        model=(model or OPENAI_MODEL)[:80],
        feature=(feature or 'openai')[:120],
    )


def _openai_request(url: str, body: dict) -> dict:
    from apps.inventory.utils import get_openai_api_key

    ensure_ai_available()
    api_key = get_openai_api_key()
    payload_bytes = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=OPENAI_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode('utf-8', errors='replace')[:500]
        raise RuntimeError(f'OpenAI API error ({exc.code}): {err_body}') from exc


def _record_usage(payload: dict, *, feature: str, model: str) -> None:
    usage = payload.get('usage') or {}
    total = int(usage.get('total_tokens') or 0)
    if total <= 0:
        input_tokens = int(usage.get('input_tokens') or usage.get('prompt_tokens') or 0)
        output_tokens = int(usage.get('output_tokens') or usage.get('completion_tokens') or 0)
        total = input_tokens + output_tokens
    if total <= 0:
        total = 1
    consume_ai_tokens(
        total,
        feature=feature,
        model=model,
        prompt_tokens=int(usage.get('prompt_tokens') or usage.get('input_tokens') or 0),
        completion_tokens=int(usage.get('completion_tokens') or usage.get('output_tokens') or 0),
    )


def _responses_output_text(payload: dict) -> str:
    if payload.get('output_text'):
        return str(payload['output_text'])
    chunks: list[str] = []
    for item in payload.get('output') or []:
        if item.get('type') != 'message':
            continue
        for part in item.get('content') or []:
            if part.get('type') in ('output_text', 'text'):
                chunks.append(part.get('text') or '')
    return ''.join(chunks).strip()


def _uses_responses_api(model: str) -> bool:
    name = (model or '').lower()
    return name.startswith('gpt-5') or name.startswith('o')


def _model_supports_reasoning(model: str) -> bool:
    return _uses_responses_api(model)


def call_openai_raw(body: dict, *, feature: str = 'openai') -> dict:
    """POST to OpenAI chat completions; enforce quota and record usage."""
    model = body.get('model') or OPENAI_MODEL
    payload = _openai_request(OPENAI_CHAT_URL, body)
    _record_usage(payload, feature=feature, model=model)
    return payload


def call_openai_responses_raw(body: dict, *, feature: str = 'openai_responses') -> dict:
    model = body.get('model') or OPENAI_MODEL
    payload = _openai_request(OPENAI_RESPONSES_URL, body)
    _record_usage(payload, feature=feature, model=model)
    return payload


def call_openai_json(
    *,
    system: str,
    user_payload: dict | list,
    temperature: float = 0.2,
    feature: str = 'openai_json',
    model: str = '',
    reasoning_effort: str = '',
    json_schema: dict | None = None,
    json_schema_name: str = 'response',
    json_schema_strict: bool = False,
    prompt_cache_key: str = '',
) -> dict | list:
    model = resolve_openai_model(model)
    effort = resolve_reasoning_effort(reasoning_effort)
    user_text = json.dumps(user_payload, default=str, ensure_ascii=False)

    text_format: dict
    if json_schema:
        text_format = {
            'type': 'json_schema',
            'name': json_schema_name,
            'schema': json_schema,
            'strict': json_schema_strict,
        }
    else:
        text_format = {'type': 'json_object'}

    if _uses_responses_api(model):
        body = {
            'model': model,
            'reasoning': {'effort': effort},
            'instructions': system,
            'input': user_text,
            'text': {'format': text_format},
        }
        if prompt_cache_key:
            body['prompt_cache_key'] = prompt_cache_key
        payload = call_openai_responses_raw(body, feature=feature)
        content = _responses_output_text(payload)
    else:
        body = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_text},
            ],
            'temperature': temperature,
        }
        if json_schema:
            body['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': json_schema_name,
                    'schema': json_schema,
                    'strict': json_schema_strict,
                },
            }
        else:
            body['response_format'] = {'type': 'json_object'}
        if prompt_cache_key:
            body['prompt_cache_key'] = prompt_cache_key
        payload = call_openai_raw(body, feature=feature)
        content = payload['choices'][0]['message']['content']

    return parse_openai_json(content)


def call_openai_json_with_images(
    *,
    system: str,
    user_text: str,
    images_base64: list[str] | None = None,
    temperature: float = 0.2,
    feature: str = 'openai_json_vision',
    model: str = '',
    reasoning_effort: str = '',
    json_schema: dict | None = None,
    json_schema_name: str = 'response',
    json_schema_strict: bool = False,
    prompt_cache_key: str = '',
) -> dict | list:
    """Responses API call with optional inline PNG images (GPT reads PDF scans)."""
    model = resolve_openai_model(model)
    effort = resolve_reasoning_effort(reasoning_effort)

    text_format: dict
    if json_schema:
        text_format = {
            'type': 'json_schema',
            'name': json_schema_name,
            'schema': json_schema,
            'strict': json_schema_strict,
        }
    else:
        text_format = {'type': 'json_object'}

    content: list[dict] = [{'type': 'input_text', 'text': user_text}]
    for b64 in images_base64 or []:
        if not b64:
            continue
        url = b64 if b64.startswith('data:') else f'data:image/png;base64,{b64}'
        content.append({'type': 'input_image', 'image_url': url})

    body = {
        'model': model,
        'instructions': system,
        'input': [{'role': 'user', 'content': content}],
        'text': {'format': text_format},
    }
    if _model_supports_reasoning(model):
        body['reasoning'] = {'effort': effort}
    if prompt_cache_key:
        body['prompt_cache_key'] = prompt_cache_key

    payload = call_openai_responses_raw(body, feature=feature)
    content_out = _responses_output_text(payload)
    return parse_openai_json(content_out)


def tokens_for_amount(amount: Decimal, currency: str = 'AED') -> int:
    """ERP tokens granted on recharge — half of OPENAI_TOKENS_PER_AED_REFERENCE by default."""
    explicit = getattr(settings, 'AI_TOKENS_PER_CURRENCY_UNIT', None)
    if explicit is not None:
        rate = int(explicit)
    else:
        reference = int(getattr(settings, 'OPENAI_TOKENS_PER_AED_REFERENCE', 181529))
        rate = int(reference * 0.5)
    cur = (currency or 'AED').upper()
    multiplier = Decimal('1')
    if cur == 'USD':
        multiplier = Decimal(str(getattr(settings, 'AI_USD_TO_AED', '3.67')))
    elif cur != 'AED':
        multiplier = Decimal('1')
    aed_amount = amount * multiplier if cur == 'USD' else amount
    tokens = int(aed_amount * rate)
    return max(tokens, 0)
