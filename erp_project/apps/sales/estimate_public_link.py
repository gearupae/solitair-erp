"""Public shareable quotation link and view analytics."""
from __future__ import annotations

import hashlib
import uuid

from django.db.models import Max
from django.urls import reverse

from apps.core.utils import get_client_ip

PUBLIC_QUOTATION_STATUSES = frozenset({'quotation_won', 'under_negotiation'})


def estimate_public_link_eligible(estimate) -> bool:
    return (
        estimate.is_active
        and estimate.status in PUBLIC_QUOTATION_STATUSES
    )


def ensure_estimate_public_token(estimate):
    """Assign a share token when the estimate may be shared publicly."""
    if not estimate_public_link_eligible(estimate):
        return None
    if estimate.public_share_token:
        return estimate.public_share_token
    estimate.public_share_token = uuid.uuid4()
    estimate.save(update_fields=['public_share_token'])
    return estimate.public_share_token


def public_quotation_url(request, estimate) -> str:
    token = ensure_estimate_public_token(estimate)
    if not token:
        return ''
    path = reverse('sales:public_quotation', kwargs={'token': token})
    return request.build_absolute_uri(path)


def device_key_from_user_agent(user_agent: str) -> str:
    ua = (user_agent or '').strip() or 'unknown'
    return hashlib.sha256(ua.encode('utf-8')).hexdigest()[:64]


def record_public_quotation_view(request, estimate):
    from .models import EstimatePublicView

    ip = get_client_ip(request) or ''
    creator_ip = (estimate.quotation_creator_ip or '').strip()
    is_counted = not (creator_ip and ip and ip == creator_ip)
    user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:2000]

    return EstimatePublicView.objects.create(
        estimate=estimate,
        ip_address=ip or None,
        user_agent=user_agent,
        device_key=device_key_from_user_agent(user_agent),
        is_counted=is_counted,
    )


def public_quotation_view_stats(estimate) -> dict:
    from .models import EstimatePublicView

    qs = EstimatePublicView.objects.filter(estimate=estimate, is_counted=True)
    return {
        'total_views': qs.count(),
        'unique_devices': qs.values('device_key').distinct().count(),
        'last_viewed_at': qs.aggregate(last=Max('viewed_at'))['last'],
    }


def get_estimate_for_public_token(token):
    from .models import Estimate

    return (
        Estimate.objects.filter(
            public_share_token=token,
            is_active=True,
            status__in=PUBLIC_QUOTATION_STATUSES,
        )
        .select_related('customer', 'assigned_to', 'project')
        .first()
    )
