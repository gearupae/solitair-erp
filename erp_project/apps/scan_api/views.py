"""
JSON API for native scan clients (e.g. Flutter). Uses Django session auth — same
username/password as the web ERP. CSRF is not required on these routes (mobile clients).
"""
import json

from django.contrib.auth import authenticate, login, logout
from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.stock_take.models import StockTakeSession
from apps.stock_take.views import (
    _can_inventory_edit,
    _can_inventory_view,
    _record_scan_payload,
)


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return None


def _require_auth(request):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Not authenticated.'}, status=401)
    return None


@csrf_exempt
@require_POST
def api_login(request):
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username:
        return JsonResponse({'ok': False, 'error': 'Username is required.'}, status=400)
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return JsonResponse({'ok': False, 'error': 'Invalid username or password.'}, status=401)
    login(request, user)
    return JsonResponse(
        {
            'ok': True,
            'user': {
                'id': user.pk,
                'username': user.get_username(),
            },
        }
    )


@csrf_exempt
@require_POST
def api_logout(request):
    if request.user.is_authenticated:
        logout(request)
    return JsonResponse({'ok': True})


@csrf_exempt
@require_GET
def api_me(request):
    err = _require_auth(request)
    if err:
        return err
    u = request.user
    return JsonResponse(
        {
            'ok': True,
            'user': {'id': u.pk, 'username': u.get_username()},
            'can_inventory_scan': _can_inventory_edit(u),
        }
    )


@csrf_exempt
@require_GET
def api_stock_take_sessions(request):
    err = _require_auth(request)
    if err:
        return err
    if not _can_inventory_view(request.user):
        return JsonResponse({'ok': False, 'error': 'Inventory access required.'}, status=403)
    qs = (
        StockTakeSession.objects.filter(status=StockTakeSession.STATUS_IN_PROGRESS)
        .annotate(line_count=Count('lines'))
        .order_by('-created_at')[:200]
    )
    sessions = [
        {
            'id': s.pk,
            'client_name': s.client_name,
            'location': s.location,
            'session_date': str(s.session_date),
            'status': s.status,
            'line_count': s.line_count,
        }
        for s in qs
    ]
    return JsonResponse({'ok': True, 'sessions': sessions})


@csrf_exempt
@require_GET
def api_stock_take_session_detail(request, pk):
    err = _require_auth(request)
    if err:
        return err
    if not _can_inventory_view(request.user):
        return JsonResponse({'ok': False, 'error': 'Inventory access required.'}, status=403)
    try:
        s = StockTakeSession.objects.get(pk=pk)
    except StockTakeSession.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Session not found.'}, status=404)
    lines = [
        {
            'sku': row['sku'],
            'scan_code': row['scan_code'] or '',
            'item_name': row['item_name'],
            'expected_qty': str(row['expected_qty']),
            'actual_qty': str(row['actual_qty']),
        }
        for row in s.lines.all().values('sku', 'scan_code', 'item_name', 'expected_qty', 'actual_qty')
    ]
    return JsonResponse(
        {
            'ok': True,
            'session': {
                'id': s.pk,
                'client_name': s.client_name,
                'location': s.location,
                'session_date': str(s.session_date),
                'status': s.status,
                'unknown_scan_count': s.unknown_scans.count(),
            },
            'lines': lines,
            'can_scan': _can_inventory_edit(request.user),
        }
    )


@csrf_exempt
@require_POST
def api_stock_take_scan(request, pk):
    err = _require_auth(request)
    if err:
        return err
    if not _can_inventory_edit(request.user):
        return JsonResponse({'ok': False, 'error': 'Inventory edit permission required to scan.'}, status=403)
    session = StockTakeSession.objects.filter(
        pk=pk, status=StockTakeSession.STATUS_IN_PROGRESS
    ).first()
    if not session:
        return JsonResponse(
            {'ok': False, 'error': 'Session not found or not in progress.'},
            status=404,
        )
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)
    payload, status = _record_scan_payload(session, data)
    return JsonResponse(payload, status=status)
