"""Public estimate quotation link — view tracking and stats."""
from __future__ import annotations

import uuid

from django.http import HttpResponse

from apps.core.utils import get_client_ip
from apps.sales.models import Estimate, EstimatePublicView

DEVICE_COOKIE_NAME = 'gearup_quote_dev'
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 730  # ~2 years


def _normalize_ip(ip: str | None) -> str:
    return (ip or '').strip()


def is_creator_ip(estimate: Estimate, request) -> bool:
    creator = _normalize_ip(estimate.creator_ip)
    if not creator:
        return False
    return _normalize_ip(get_client_ip(request)) == creator


def get_or_create_device_id(request) -> tuple[str, bool]:
    """
    Return (device_id, is_new_cookie).
    Uses a persistent cookie to distinguish devices/browsers.
    """
    existing = (request.COOKIES.get(DEVICE_COOKIE_NAME) or '').strip()
    if existing and len(existing) <= 64:
        return existing, False
    return str(uuid.uuid4()), True


def attach_device_cookie(response: HttpResponse, device_id: str) -> HttpResponse:
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        device_id,
        max_age=DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        samesite='Lax',
    )
    return response


def record_public_view(request, estimate: Estimate, *, device_id: str | None = None) -> tuple[str, bool]:
    """
    Log a public quotation page view.
    Returns (device_id, excluded_from_stats).
    """
    if not device_id:
        device_id, _ = get_or_create_device_id(request)
    excluded = is_creator_ip(estimate, request)
    EstimatePublicView.objects.create(
        estimate=estimate,
        device_id=device_id,
        ip_address=_normalize_ip(get_client_ip(request)) or None,
        user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:500],
        excluded=excluded,
    )
    return device_id, excluded


def public_view_stats(estimate: Estimate) -> dict:
    qs = EstimatePublicView.objects.filter(estimate=estimate, excluded=False)
    return {
        'view_count': qs.count(),
        'device_count': qs.values('device_id').distinct().count(),
        'last_viewed_at': qs.order_by('-viewed_at').values_list('viewed_at', flat=True).first(),
    }
