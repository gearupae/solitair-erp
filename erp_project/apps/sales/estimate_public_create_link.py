"""Hourly rotating public link for submitting estimates without login."""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone


def _now():
    return timezone.now()


def get_current_active_link():
    """Return the non-expired link, if any (does not create a new one)."""
    from .models import EstimatePublicCreateLink

    return (
        EstimatePublicCreateLink.objects.filter(expires_at__gt=_now())
        .order_by('-id')
        .first()
    )


def ensure_active_public_create_link():
    """Return the active link, creating a new one when the previous hour expired."""
    from .models import EstimatePublicCreateLink

    link = get_current_active_link()
    if link:
        return link
    now = _now()
    return EstimatePublicCreateLink.objects.create(
        token=uuid.uuid4(),
        expires_at=now + timedelta(hours=1),
    )


def validate_public_create_token(token) -> bool:
    """True only for the current active hourly token."""
    if not token:
        return False
    active = get_current_active_link()
    if not active:
        return False
    try:
        return active.token == uuid.UUID(str(token))
    except (ValueError, TypeError, AttributeError):
        return False


def public_estimate_create_url(request) -> str:
    link = ensure_active_public_create_link()
    path = reverse('sales:public_estimate_create', kwargs={'token': link.token})
    return request.build_absolute_uri(path)


def public_create_link_context(request) -> dict:
    link = ensure_active_public_create_link()
    return {
        'public_estimate_create_url': public_estimate_create_url(request),
        'public_estimate_create_expires': link.expires_at,
    }
