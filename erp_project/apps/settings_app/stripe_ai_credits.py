"""Stripe checkout and webhook handling for AI credit purchases."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.openai_gateway import tokens_for_amount
from apps.settings_app.models import AiCreditPurchase, CompanySettings


class StripeNotConfigured(Exception):
    pass


def _stripe():
    import stripe

    secret = (getattr(settings, 'STRIPE_SECRET_KEY', None) or '').strip()
    if not secret:
        raise StripeNotConfigured('Stripe secret key is not configured.')
    stripe.api_key = secret
    return stripe


def stripe_configured() -> bool:
    return bool(
        (getattr(settings, 'STRIPE_SECRET_KEY', None) or '').strip()
        and (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', None) or '').strip()
    )


def create_ai_checkout_session(*, amount: Decimal, currency: str, user, success_url: str, cancel_url: str) -> dict:
    stripe = _stripe()
    product_id = (getattr(settings, 'STRIPE_AI_PRODUCT_ID', None) or '').strip()
    if not product_id:
        raise StripeNotConfigured('Stripe AI product ID is not configured.')

    cur = (currency or 'AED').lower()
    amount_cents = int((amount * 100).quantize(Decimal('1')))
    tokens = tokens_for_amount(amount, currency.upper())

    purchase = AiCreditPurchase.objects.create(
        amount=amount,
        currency=currency.upper(),
        tokens_granted=tokens,
        status=AiCreditPurchase.STATUS_PENDING,
        created_by=user,
    )

    session = stripe.checkout.Session.create(
        mode='payment',
        line_items=[
            {
                'price_data': {
                    'currency': cur,
                    'product': product_id,
                    'unit_amount': amount_cents,
                },
                'quantity': 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            'purchase_id': str(purchase.pk),
            'tokens_granted': str(tokens),
            'user_id': str(user.pk if user else ''),
        },
    )
    purchase.stripe_checkout_session_id = session.id
    purchase.save(update_fields=['stripe_checkout_session_id'])
    return {'session_id': session.id, 'url': session.url, 'purchase_id': purchase.pk}


@transaction.atomic
def complete_ai_purchase(*, session_id: str = '', payment_intent_id: str = '', purchase_id: int | None = None) -> AiCreditPurchase | None:
    purchase = None
    if session_id:
        purchase = (
            AiCreditPurchase.objects.select_for_update()
            .filter(stripe_checkout_session_id=session_id)
            .first()
        )
    elif payment_intent_id:
        purchase = (
            AiCreditPurchase.objects.select_for_update()
            .filter(stripe_payment_intent_id=payment_intent_id)
            .first()
        )
    elif purchase_id:
        purchase = (
            AiCreditPurchase.objects.select_for_update()
            .filter(pk=purchase_id)
            .first()
        )
    if not purchase:
        return None
    if purchase.status == AiCreditPurchase.STATUS_COMPLETED:
        return purchase

    purchase.status = AiCreditPurchase.STATUS_COMPLETED
    purchase.completed_at = timezone.now()
    if payment_intent_id and not purchase.stripe_payment_intent_id:
        purchase.stripe_payment_intent_id = payment_intent_id
    purchase.save(
        update_fields=['status', 'completed_at', 'stripe_payment_intent_id'],
    )

    CompanySettings.objects.filter(pk=1).update(
        ai_token_limit=F('ai_token_limit') + purchase.tokens_granted,
    )
    return purchase


def create_ai_payment_intent(*, amount: Decimal, currency: str, user) -> dict:
    stripe = _stripe()
    cur = (currency or 'AED').lower()
    amount_cents = int((amount * 100).quantize(Decimal('1')))
    tokens = tokens_for_amount(amount, currency.upper())

    purchase = AiCreditPurchase.objects.create(
        amount=amount,
        currency=currency.upper(),
        tokens_granted=tokens,
        status=AiCreditPurchase.STATUS_PENDING,
        created_by=user,
    )

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency=cur,
        automatic_payment_methods={'enabled': True},
        metadata={
            'purchase_id': str(purchase.pk),
            'tokens_granted': str(tokens),
            'user_id': str(user.pk if user else ''),
        },
    )
    purchase.stripe_payment_intent_id = intent.id
    purchase.save(update_fields=['stripe_payment_intent_id'])
    return {
        'client_secret': intent.client_secret,
        'purchase_id': purchase.pk,
        'payment_intent_id': intent.id,
    }


def verify_and_complete_payment_intent(payment_intent_id: str) -> AiCreditPurchase | None:
    stripe = _stripe()
    intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    if intent.status != 'succeeded':
        return None
    return complete_ai_purchase(payment_intent_id=payment_intent_id)


def verify_and_complete_checkout_session(session_id: str) -> AiCreditPurchase | None:
    stripe = _stripe()
    session = stripe.checkout.Session.retrieve(session_id)
    if session.payment_status != 'paid':
        return None
    return complete_ai_purchase(
        session_id=session.id,
        payment_intent_id=str(session.payment_intent or ''),
    )


def handle_stripe_webhook(payload: bytes, sig_header: str):
    stripe = _stripe()
    webhook_secret = (getattr(settings, 'STRIPE_WEBHOOK_SECRET', None) or '').strip()
    if webhook_secret:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    else:
        import json

        event = stripe.Event.construct_from(json.loads(payload.decode('utf-8')), stripe.api_key)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        if session.get('payment_status') == 'paid':
            complete_ai_purchase(
                session_id=session['id'],
                payment_intent_id=str(session.get('payment_intent') or ''),
            )
    elif event['type'] == 'payment_intent.succeeded':
        intent = event['data']['object']
        complete_ai_purchase(payment_intent_id=intent['id'])
    return event


def parse_recharge_amount(raw: str) -> Decimal:
    try:
        amount = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('Enter a valid recharge amount.') from exc
    if amount <= 0:
        raise ValueError('Recharge amount must be greater than zero.')
    minimum = Decimal(str(getattr(settings, 'AI_RECHARGE_MIN_AMOUNT', '5')))
    if amount < minimum:
        raise ValueError(f'Minimum recharge is {minimum}.')
    return amount.quantize(Decimal('0.01'))
