"""Stripe AI credit views."""
from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.utils import PermissionChecker
from apps.settings_app.stripe_ai_credits import (
    StripeNotConfigured,
    create_ai_checkout_session,
    create_ai_payment_intent,
    handle_stripe_webhook,
    parse_recharge_amount,
    verify_and_complete_checkout_session,
    verify_and_complete_payment_intent,
)


def _can_manage_settings(user) -> bool:
    return user.is_superuser or PermissionChecker.has_permission(user, 'settings', 'edit')


@login_required
@require_POST
def stripe_ai_checkout(request):
    if not _can_manage_settings(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    try:
        amount = parse_recharge_amount(request.POST.get('amount'))
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    currency = (cs.currency or 'AED').upper()
    base = request.build_absolute_uri(reverse('settings:company'))
    success_url = f'{base}?stripe=success&session_id={{CHECKOUT_SESSION_ID}}'
    cancel_url = f'{base}?stripe=cancel'

    try:
        result = create_ai_checkout_session(
            amount=amount,
            currency=currency,
            user=request.user,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except StripeNotConfigured as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=503)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Could not start checkout: {exc}'}, status=500)

    return JsonResponse({'ok': True, 'checkout_url': result['url']})


@login_required
@require_POST
def stripe_ai_payment_intent(request):
    """Create a PaymentIntent for inline card payment (Stripe Payment Element)."""
    if not _can_manage_settings(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    try:
        amount = parse_recharge_amount(request.POST.get('amount'))
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    currency = (cs.currency or 'AED').upper()

    try:
        result = create_ai_payment_intent(
            amount=amount,
            currency=currency,
            user=request.user,
        )
    except StripeNotConfigured as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=503)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Could not prepare payment: {exc}'}, status=500)

    return JsonResponse({
        'ok': True,
        'client_secret': result['client_secret'],
        'purchase_id': result['purchase_id'],
    })


@login_required
@require_POST
def stripe_ai_confirm_payment(request):
    """Verify PaymentIntent succeeded and grant AI tokens."""
    if not _can_manage_settings(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    payment_intent_id = (request.POST.get('payment_intent_id') or '').strip()
    if not payment_intent_id:
        return JsonResponse({'ok': False, 'error': 'Missing payment reference.'}, status=400)

    try:
        purchase = verify_and_complete_payment_intent(payment_intent_id)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Could not verify payment: {exc}'}, status=500)

    if not purchase:
        return JsonResponse({'ok': False, 'error': 'Payment not completed yet.'}, status=402)

    return JsonResponse({
        'ok': True,
        'tokens_granted': purchase.tokens_granted,
        'amount': str(purchase.amount),
        'currency': purchase.currency,
    })


@login_required
def stripe_ai_success(request):
    session_id = (request.GET.get('session_id') or '').strip()
    if session_id and _can_manage_settings(request.user):
        try:
            purchase = verify_and_complete_checkout_session(session_id)
            if purchase:
                messages.success(
                    request,
                    f'AI credits added: {purchase.tokens_granted:,} tokens '
                    f'({purchase.amount} {purchase.currency}).',
                )
            else:
                messages.warning(request, 'Payment is still processing or could not be verified.')
        except Exception as exc:
            messages.error(request, f'Could not verify payment: {exc}')
    return redirect('settings:company')


@csrf_exempt
@require_POST
def stripe_webhook(request):
    try:
        handle_stripe_webhook(request.body, request.META.get('HTTP_STRIPE_SIGNATURE', ''))
    except Exception:
        return HttpResponse(status=400)
    return HttpResponse(status=200)
