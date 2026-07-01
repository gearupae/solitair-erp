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
from .forms import DrawingUploadForm
from .models import BOMItem, Drawing, ProductionOrder
from .utils import get_default_mes_company

logger = logging.getLogger(__name__)


def _serialize_drawing(drawing: Drawing) -> dict:
    filename = drawing.file.name.rsplit('/', 1)[-1] if drawing.file else ''
    return {
        'id': drawing.pk,
        'title': drawing.display_title,
        'version': drawing.version,
        'is_released': drawing.is_released,
        'url': drawing.file.url if drawing.file else '',
        'filename': filename,
        'created_at': drawing.created_at.isoformat() if drawing.created_at else '',
    }


def _get_bom_item(company, po_pk: int, bom_pk: int) -> BOMItem:
    return BOMItem.objects.get(
        pk=bom_pk,
        production_order_id=po_pk,
        production_order__company=company,
        is_active=True,
    )


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


@login_required
@require_http_methods(['GET', 'POST'])
def bom_drawings_api(request, po_pk: int, bom_pk: int):
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    try:
        bom_item = _get_bom_item(company, po_pk, bom_pk)
    except BOMItem.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'BOM line not found.'}, status=404)

    if request.method == 'GET':
        drawings = Drawing.objects.filter(
            company=company,
            bom_item=bom_item,
            is_active=True,
        ).order_by('-created_at')
        return JsonResponse({
            'success': True,
            'bom_item_id': bom_item.pk,
            'part_name': bom_item.part_name,
            'drawings': [_serialize_drawing(d) for d in drawings if d.file],
        })

    if bom_item.production_order.status in (
        ProductionOrder.STATUS_FINISHED,
        ProductionOrder.STATUS_CANCELLED,
    ):
        return JsonResponse(
            {'success': False, 'message': 'Cannot upload drawings on a finished or cancelled order.'},
            status=400,
        )

    form = DrawingUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse(
            {'success': False, 'message': '; '.join(
                f'{field}: {errs[0]}' for field, errs in form.errors.items()
            )},
            status=400,
        )

    drawing = Drawing.objects.create(
        company=company,
        bom_item=bom_item,
        file=form.cleaned_data['file'],
        title=(form.cleaned_data.get('title') or '').strip(),
        version=form.cleaned_data['version'],
        is_released=False,
        created_by=request.user,
        updated_by=request.user,
    )
    return JsonResponse({
        'success': True,
        'message': 'Drawing uploaded.',
        'drawing': _serialize_drawing(drawing),
    })


@login_required
@require_http_methods(['POST'])
def drawing_release_api(request, pk: int):
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    try:
        drawing = Drawing.objects.select_related('bom_item__production_order').get(
            pk=pk,
            company=company,
            is_active=True,
            bom_item__isnull=False,
        )
    except Drawing.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Drawing not found.'}, status=404)

    po = drawing.bom_item.production_order
    if po.status in (ProductionOrder.STATUS_FINISHED, ProductionOrder.STATUS_CANCELLED):
        return JsonResponse(
            {'success': False, 'message': 'Cannot change release on a finished or cancelled order.'},
            status=400,
        )

    data = _parse_json_body(request)
    if 'is_released' in data:
        drawing.is_released = bool(data['is_released'])
    else:
        drawing.is_released = not drawing.is_released
    drawing.updated_by = request.user
    drawing.save(update_fields=['is_released', 'updated_by', 'updated_at'])

    state = 'released' if drawing.is_released else 'unreleased'
    return JsonResponse({
        'success': True,
        'message': f'Drawing {state}.',
        'drawing': _serialize_drawing(drawing),
    })


@login_required
@require_http_methods(['POST'])
def drawing_delete_api(request, pk: int):
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    try:
        drawing = Drawing.objects.select_related('bom_item__production_order').get(
            pk=pk,
            company=company,
            is_active=True,
        )
    except Drawing.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Drawing not found.'}, status=404)

    po = drawing.bom_item.production_order if drawing.bom_item_id else None
    if po and po.status in (ProductionOrder.STATUS_FINISHED, ProductionOrder.STATUS_CANCELLED):
        return JsonResponse(
            {'success': False, 'message': 'Cannot delete drawings on a finished or cancelled order.'},
            status=400,
        )

    drawing.is_active = False
    drawing.updated_by = request.user
    drawing.save(update_fields=['is_active', 'updated_by', 'updated_at'])
    return JsonResponse({'success': True, 'message': 'Drawing removed.'})


@login_required
@require_http_methods(['POST'])
def actual_count_capture_api(request):
    """Analyze a camera frame with OpenAI vision and increment daily counts."""
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    body = _parse_json_body(request)
    image = (body.get('image') or body.get('image_base64') or '').strip()
    if not image:
        return JsonResponse({'success': False, 'message': 'Camera image is required.'}, status=400)

    from apps.core.openai_gateway import AiQuotaExceeded
    from .services.actual_count import get_daily_log_rows, process_capture

    try:
        result = process_capture(company=company, user=request.user, image_base64=image)
    except AiQuotaExceeded as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=402)
    except ValueError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    except RuntimeError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=503)
    except Exception as exc:
        logger.exception('Actual count capture failed')
        return JsonResponse({'success': False, 'message': str(exc) or 'Capture failed.'}, status=500)

    payload = {'success': True, **result}
    if result.get('added_counts'):
        payload['daily_logs'] = get_daily_log_rows(company, days=30)
    return JsonResponse(payload)


@login_required
@require_http_methods(['POST'])
def actual_count_reset_api(request):
    """Reset delta baseline when monitoring restarts."""
    company = _mes_api_guard(request)
    if isinstance(company, JsonResponse):
        return company

    from .services.actual_count import reset_capture_baseline

    reset_capture_baseline(company)
    return JsonResponse({'success': True, 'message': 'Baseline reset.'})
