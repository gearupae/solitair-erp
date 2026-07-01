"""Oracle Fusion REST mock endpoints (JSON only — swap base URL for real Oracle)."""

from __future__ import annotations

import json
import uuid

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .data import SAMPLE_ITEMS, SAMPLE_PRODUCTION_ORDERS


def _require_json_post(request):
    if request.content_type and 'application/json' not in request.content_type:
        return JsonResponse(
            {'detail': 'Content-Type must be application/json'},
            status=415,
        )
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON body'}, status=400)


@require_GET
def production_orders_list(request):
    """GET /oracle-mock/production-orders/ — list work orders."""
    return JsonResponse(SAMPLE_PRODUCTION_ORDERS)


@require_GET
def items_list(request):
    """GET /oracle-mock/items/ — item master."""
    return JsonResponse(SAMPLE_ITEMS)


@csrf_exempt
@require_http_methods(['POST'])
def material_consumption_post(request):
    """POST /oracle-mock/material-consumption/ — accept consumption transaction."""
    body = _require_json_post(request)
    if isinstance(body, JsonResponse):
        return body
    txn_id = body.get('TransactionId') or f'MC-{uuid.uuid4().hex[:12].upper()}'
    return JsonResponse(
        {
            'TransactionId': txn_id,
            'Status': 'SUCCESS',
            'Message': 'Material consumption posted to Oracle WIP',
            'Echo': body,
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(['POST'])
def wip_valuation_post(request):
    """POST /oracle-mock/wip-valuation/ — accept WIP value update."""
    body = _require_json_post(request)
    if isinstance(body, JsonResponse):
        return body
    txn_id = body.get('TransactionId') or f'WIP-{uuid.uuid4().hex[:12].upper()}'
    return JsonResponse(
        {
            'TransactionId': txn_id,
            'Status': 'SUCCESS',
            'Message': 'WIP valuation updated in Oracle',
            'Echo': body,
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(['POST'])
def dispatch_confirm_post(request):
    """POST /oracle-mock/dispatch-confirm/ — accept dispatch confirmation."""
    body = _require_json_post(request)
    if isinstance(body, JsonResponse):
        return body
    txn_id = body.get('TransactionId') or f'DSP-{uuid.uuid4().hex[:12].upper()}'
    return JsonResponse(
        {
            'TransactionId': txn_id,
            'Status': 'SUCCESS',
            'Message': 'Dispatch confirmed in Oracle',
            'Echo': body,
        },
        status=201,
    )
