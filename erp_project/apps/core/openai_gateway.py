"""Central OpenAI API gateway with company-wide token quota enforcement."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from decimal import Decimal

from django.db import transaction
from django.db.models import F

OPENAI_MODEL = 'gpt-4o-mini'
OPENAI_CHAT_URL = 'https://api.openai.com/v1/chat/completions'


class OpenAINotConfigured(Exception):
    pass


class AiQuotaExceeded(Exception):
    """Raised when the company AI token allowance is exhausted."""


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


def call_openai_raw(body: dict, *, feature: str = 'openai') -> dict:
    """POST to OpenAI chat completions; enforce quota and record usage."""
    from apps.inventory.utils import get_openai_api_key

    ensure_ai_available()
    api_key = get_openai_api_key()
    payload_bytes = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        OPENAI_CHAT_URL,
        data=payload_bytes,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode('utf-8', errors='replace')[:500]
        raise RuntimeError(f'OpenAI API error ({exc.code}): {err_body}') from exc

    usage = payload.get('usage') or {}
    total = int(usage.get('total_tokens') or 0)
    if total <= 0:
        total = 1
    consume_ai_tokens(
        total,
        feature=feature,
        model=body.get('model') or OPENAI_MODEL,
        prompt_tokens=int(usage.get('prompt_tokens') or 0),
        completion_tokens=int(usage.get('completion_tokens') or 0),
    )
    return payload


def call_openai_json(
    *,
    system: str,
    user_payload: dict | list,
    temperature: float = 0.2,
    feature: str = 'openai_json',
    model: str = OPENAI_MODEL,
) -> dict | list:
    body = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(user_payload, default=str)},
        ],
        'temperature': temperature,
        'response_format': {'type': 'json_object'},
    }
    payload = call_openai_raw(body, feature=feature)
    content = payload['choices'][0]['message']['content']
    return parse_openai_json(content)


def tokens_for_amount(amount: Decimal, currency: str = 'AED') -> int:
    from django.conf import settings

    rate = int(getattr(settings, 'AI_TOKENS_PER_CURRENCY_UNIT', 50000))
    cur = (currency or 'AED').upper()
    multiplier = Decimal('1')
    if cur == 'USD':
        multiplier = Decimal(str(getattr(settings, 'AI_USD_TO_AED', '3.67')))
    elif cur != 'AED':
        multiplier = Decimal('1')
    aed_amount = amount * multiplier if cur == 'USD' else amount
    tokens = int(aed_amount * rate)
    return max(tokens, 0)
