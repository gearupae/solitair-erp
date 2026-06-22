"""Daily cache helper for AI inventory hub tabs."""
from __future__ import annotations

import hashlib
from datetime import timedelta

from django.utils import timezone

from apps.inventory.models_reporting import InventoryAIHubCache


def _daily_key(tab: str, extra: str = '') -> str:
    day = timezone.now().date().isoformat()
    raw = f'{tab}|{day}|{extra}'
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_or_build_tab_cache(*, tab: str, builder, force: bool = False, ttl_hours: int = 24, extra: str = ''):
    key = _daily_key(tab, extra)
    if not force:
        cached = InventoryAIHubCache.objects.filter(cache_key=key).first()
        if cached and cached.generated_at >= timezone.now() - timedelta(hours=ttl_hours):
            payload = dict(cached.payload)
            payload['from_cache'] = True
            payload['cached_at'] = cached.generated_at.isoformat()
            return payload

    payload = builder()
    payload['from_cache'] = False
    InventoryAIHubCache.objects.update_or_create(
        cache_key=key,
        defaults={
            'tab': tab,
            'payload': payload,
            'generated_at': timezone.now(),
        },
    )
    return payload
