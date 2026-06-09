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
    return cs.get_openai_api_key_decrypted()


def openai_key_status() -> str:
    """Human-readable key source for settings UI."""
    env_key = (getattr(settings, 'OPENAI_API_KEY', None) or '').strip()
    if env_key:
        return 'env'
    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    if cs.get_openai_api_key_decrypted():
        return 'database'
    return 'none'


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ''
    if len(value) <= visible:
        return '*' * len(value)
    return ('*' * (len(value) - visible)) + value[-visible:]
