"""MES floor tablet JSON API."""

from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from apps.core.utils import PermissionChecker

from .services.gearup_agent import (
    run_cost_estimate,
    run_delay_classification,
    run_delay_prediction,
    run_draft_template,
    run_nl_query,
)
from .services.scan import ScanError, build_scan_response, complete_checklist_item, process_scan
from .services.station_queue import get_station_queue
from .utils import get_default_mes_company

logger = logging.getLogger(__name__)


def _mes_api_guard(request):
    """Return company or a JsonResponse error."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'settings', 'view')
    ):
        return JsonResponse({'success': False, 'message': 'Permission denied.'}, status=403)
    company = get_default_mes_company()
    if not company:
        return JsonResponse(
            {'success': False, 'message': 'No active company configured for Manufacturing.'},
            status=400,
        )
    return company


def _parse_json_body(request) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return {}


@login_required
@require_http_methods(['POST'])
def scan_api(request):
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    data = _parse_json_body(request)
    barcode = data.get('barcode') or request.POST.get('barcode', '')
    work_center_id = data.get('work_center_id') or request.POST.get('work_center_id')
    scan_type = (data.get('scan_type') or request.POST.get('scan_type', 'in')).lower()
    operator = request.user

    if work_center_id in (None, ''):
        return JsonResponse(
            {'success': False, 'message': 'work_center_id is required.', 'code': 'missing_work_center'},
            status=400,
        )

    try:
        work_center_id = int(work_center_id)
    except (TypeError, ValueError):
        return JsonResponse(
            {'success': False, 'message': 'work_center_id must be an integer.', 'code': 'invalid_work_center'},
            status=400,
        )

    try:
        result = process_scan(
            company=company,
            barcode=barcode,
            work_center_id=work_center_id,
            scan_type=scan_type,
            operator=operator,
        )
    except ScanError as exc:
        return JsonResponse(
            {'success': False, 'message': exc.message, 'code': exc.code},
            status=400,
        )

    return JsonResponse(build_scan_response(result))


@login_required
@require_http_methods(['POST'])
def checklist_complete_api(request):
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    data = _parse_json_body(request)
    part_id = data.get('part_id') or request.POST.get('part_id')
    checklist_item_id = data.get('checklist_item_id') or request.POST.get('checklist_item_id')
    work_center_id = data.get('work_center_id') or request.POST.get('work_center_id')

    for field, label in (
        (part_id, 'part_id'),
        (checklist_item_id, 'checklist_item_id'),
        (work_center_id, 'work_center_id'),
    ):
        if field in (None, ''):
            return JsonResponse(
                {'success': False, 'message': f'{label} is required.', 'code': 'missing_field'},
                status=400,
            )

    try:
        payload = complete_checklist_item(
            company=company,
            part_id=int(part_id),
            checklist_item_id=int(checklist_item_id),
            work_center_id=int(work_center_id),
            operator=request.user,
        )
    except ScanError as exc:
        return JsonResponse(
            {'success': False, 'message': exc.message, 'code': exc.code},
            status=400,
        )

    return JsonResponse(payload)


@login_required
@require_http_methods(['GET'])
def station_queue_api(request):
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    raw_wc = request.GET.get('work_center_id')
    if raw_wc in (None, ''):
        return JsonResponse(
            {'success': False, 'message': 'work_center_id is required.', 'code': 'missing_work_center'},
            status=400,
        )
    try:
        work_center_id = int(raw_wc)
    except (TypeError, ValueError):
        return JsonResponse(
            {'success': False, 'message': 'work_center_id must be an integer.', 'code': 'invalid_work_center'},
            status=400,
        )

    try:
        payload = get_station_queue(company, work_center_id)
    except ValueError as exc:
        return JsonResponse(
            {'success': False, 'message': str(exc), 'code': 'unknown_work_center'},
            status=404,
        )

    return JsonResponse({'success': True, **payload})


@login_required
@require_http_methods(['POST'])
def gearup_agent_api(request):
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    data = _parse_json_body(request)
    action = (data.get('action') or '').strip().lower()
    text = (data.get('text') or data.get('query') or data.get('description') or '').strip()

    handlers = {
        'delay_prediction': lambda: run_delay_prediction(company),
        'classify_delays': lambda: run_delay_classification(company),
        'ask': lambda: run_nl_query(company, text),
        'draft_template': lambda: run_draft_template(company, text),
        'estimate_cost': lambda: run_cost_estimate(company, text),
    }

    if action not in handlers:
        return JsonResponse(
            {
                'ok': False,
                'message': 'Unknown action. Use: delay_prediction, classify_delays, ask, draft_template, estimate_cost.',
            },
            status=400,
        )

    try:
        result = handlers[action]()
    except Exception as exc:
        logger.exception('Gearup Agent error')
        return JsonResponse({'ok': False, 'message': str(exc)}, status=500)

    status = 200 if result.get('ok', True) else 400
    return JsonResponse(result, status=status)
