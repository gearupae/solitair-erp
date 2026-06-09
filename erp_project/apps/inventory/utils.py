"""Inventory utility helpers."""
from __future__ import annotations

from django.conf import settings


def get_openai_api_key() -> str:
    """
    Return OpenAI API key: environment (.env) first, then encrypted DB value.
    """
    env_key = (getattr(settings, 'OPENAI_API_KEY', None) or '').strip()
    if env_key:
        return env_key
    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    stored = (cs.openai_api_key or '').strip()
    if not stored:
        return ''
    decrypted = cs.get_openai_api_key_decrypted().strip()
    if decrypted:
        return decrypted
    # Plain-text fallback (legacy / mis-saved keys)
    if stored.startswith('sk-'):
        return stored
    return ''


def openai_key_status() -> str:
    """Human-readable key source for settings UI."""
    env_key = (getattr(settings, 'OPENAI_API_KEY', None) or '').strip()
    if env_key:
        return 'env'
    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    stored = (cs.openai_api_key or '').strip()
    if get_openai_api_key():
        return 'database'
    if stored:
        return 'invalid'
    return 'none'


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ''
    if len(value) <= visible:
        return '*' * len(value)
    return ('*' * (len(value) - visible)) + value[-visible:]
