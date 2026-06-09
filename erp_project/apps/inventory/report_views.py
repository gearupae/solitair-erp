"""
Views for dedicated inventory reports (reorder, slow/dead, FIFO, gap, AI forecast).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.core.utils import PermissionChecker

from .reports.demand_supply_gap import build_demand_supply_gap_report
from .reports.export_helpers import export_table_pdf, export_table_xlsx
from .reports.fifo_valuation import build_fifo_valuation_report
from .reports.reorder import build_reorder_report
from .reports.slow_dead_stock import build_slow_dead_stock_report
from .services.ai_action_summary import get_action_summary
from .services.ai_forecast import (
    ForecastRateLimited,
    OpenAINotConfigured,
    build_ai_forecast_report,
    refresh_item_forecast,
)

PAGE_SIZE = 50


def _has_perm(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'inventory', 'view')


def _export_response(payload, fmt, generated_by, slug):
    if fmt == 'xlsx':
        data = export_table_xlsx(payload, generated_by)
        resp = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{slug}.xlsx"'
        return resp
    data = export_table_pdf(payload, generated_by)
    resp = HttpResponse(data, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{slug}.pdf"'
    return resp


def _render_report(request, template, payload, extra_context=None):
    if not _has_perm(request.user):
        return HttpResponseForbidden('Permission denied.')

    fmt = request.GET.get('export')
    if fmt in ('pdf', 'xlsx'):
        slug = template.replace('.html', '').split('/')[-1]
        return _export_response(
            payload,
            fmt,
            request.user.get_full_name() or request.user.username,
            slug,
        )

    rows = payload.get('rows', [])
    paginator = Paginator(rows, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    ctx = {
        'title': payload.get('title'),
        'payload': payload,
        'page_obj': page_obj,
        'rows': page_obj.object_list,
        'summary': payload.get('summary', {}),
        'columns': payload.get('columns', []),
    }
    if extra_context:
        ctx.update(extra_context)
    return render(request, template, ctx)


@login_required
def reorder_report(request):
    wh = request.GET.get('warehouse') or None
    cat = request.GET.get('category') or None
    below = request.GET.get('below_min') == '1'
    try:
        wh_id = int(wh) if wh else None
    except (TypeError, ValueError):
        wh_id = None
    try:
        cat_id = int(cat) if cat else None
    except (TypeError, ValueError):
        cat_id = None

    payload = build_reorder_report(
        warehouse_id=wh_id,
        category_id=cat_id,
        below_min_only=below,
    )
    return _render_report(
        request,
        'inventory/reports/reorder_report.html',
        payload,
        {
            'filter_warehouse': wh_id,
            'filter_category': cat_id,
            'filter_below_min': below,
            'filters': payload['filters'],
        },
    )


@login_required
def slow_dead_stock_report(request):
    wh = request.GET.get('warehouse') or None
    cat = request.GET.get('category') or None
    slow_th = int(request.GET.get('slow_threshold') or 60)
    dead_th = int(request.GET.get('dead_threshold') or 180)
    try:
        wh_id = int(wh) if wh else None
    except (TypeError, ValueError):
        wh_id = None
    try:
        cat_id = int(cat) if cat else None
    except (TypeError, ValueError):
        cat_id = None

    payload = build_slow_dead_stock_report(
        warehouse_id=wh_id,
        category_id=cat_id,
        slow_threshold=slow_th,
        dead_threshold=dead_th,
    )
    return _render_report(
        request,
        'inventory/reports/slow_dead_stock_report.html',
        payload,
        {
            'filter_warehouse': wh_id,
            'filter_category': cat_id,
            'filter_slow_threshold': slow_th,
            'filter_dead_threshold': dead_th,
            'filters': payload['filters'],
        },
    )


@login_required
def fifo_valuation_report(request):
    wh = request.GET.get('warehouse') or None
    cat = request.GET.get('category') or None
    try:
        wh_id = int(wh) if wh else None
    except (TypeError, ValueError):
        wh_id = None
    try:
        cat_id = int(cat) if cat else None
    except (TypeError, ValueError):
        cat_id = None

    payload = build_fifo_valuation_report(warehouse_id=wh_id, category_id=cat_id)
    return _render_report(
        request,
        'inventory/reports/fifo_valuation_report.html',
        payload,
        {
            'filter_warehouse': wh_id,
            'filter_category': cat_id,
            'filters': payload['filters'],
        },
    )


@login_required
def demand_supply_gap_report(request):
    period = int(request.GET.get('period') or 30)
    if period not in (30, 60, 90):
        period = 30
    wh = request.GET.get('warehouse') or None
    cat = request.GET.get('category') or None
    try:
        wh_id = int(wh) if wh else None
    except (TypeError, ValueError):
        wh_id = None
    try:
        cat_id = int(cat) if cat else None
    except (TypeError, ValueError):
        cat_id = None

    payload = build_demand_supply_gap_report(
        period_days=period,
        warehouse_id=wh_id,
        category_id=cat_id,
    )
    return _render_report(
        request,
        'inventory/reports/demand_supply_gap_report.html',
        payload,
        {
            'filter_period': period,
            'filter_warehouse': wh_id,
            'filter_category': cat_id,
            'filters': payload['filters'],
        },
    )


@login_required
def ai_forecast_report(request):
    wh = request.GET.get('warehouse') or None
    cat = request.GET.get('category') or None
    status_f = request.GET.get('status') or 'All'
    risk_f = request.GET.get('stockout_risk') or 'All'
    search = (request.GET.get('search') or '').strip()
    high_risk = request.GET.get('high_risk') == '1'
    try:
        wh_id = int(wh) if wh else None
    except (TypeError, ValueError):
        wh_id = None
    try:
        cat_id = int(cat) if cat else None
    except (TypeError, ValueError):
        cat_id = None

    payload = build_ai_forecast_report(
        warehouse_id=wh_id,
        category_id=cat_id,
        status_filter=status_f,
        stockout_risk_filter=risk_f if risk_f != 'All' else None,
        search=search or None,
        high_risk_only=high_risk,
    )
    action_summary = get_action_summary(payload, force=False)

    qs_parts = []
    if wh_id:
        qs_parts.append(f'warehouse={wh_id}')
    if cat_id:
        qs_parts.append(f'category={cat_id}')
    if status_f and status_f != 'All':
        qs_parts.append(f'status={status_f}')
    if risk_f and risk_f != 'All':
        qs_parts.append(f'stockout_risk={risk_f}')
    if search:
        qs_parts.append(f'search={search}')
    if high_risk:
        qs_parts.append('high_risk=1')
    filter_qs = '&'.join(qs_parts)

    return _render_report(
        request,
        'inventory/reports/ai_forecast_report.html',
        payload,
        {
            'openai_configured': payload.get('openai_configured', False),
            'filter_warehouse': wh_id,
            'filter_category': cat_id,
            'filter_status': status_f,
            'filter_stockout_risk': risk_f,
            'filter_search': search,
            'filter_high_risk': high_risk,
            'filters': payload['filters'],
            'filter_qs': filter_qs,
            'action_summary': action_summary,
        },
    )


@login_required
@require_POST
def ai_forecast_action_summary_refresh(request):
    if not _has_perm(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    wh = request.POST.get('warehouse') or None
    cat = request.POST.get('category') or None
    status_f = request.POST.get('status') or 'All'
    risk_f = request.POST.get('stockout_risk') or 'All'
    search = (request.POST.get('search') or '').strip()
    high_risk = request.POST.get('high_risk') == '1'
    try:
        wh_id = int(wh) if wh else None
    except (TypeError, ValueError):
        wh_id = None
    try:
        cat_id = int(cat) if cat else None
    except (TypeError, ValueError):
        cat_id = None

    payload = build_ai_forecast_report(
        warehouse_id=wh_id,
        category_id=cat_id,
        status_filter=status_f,
        stockout_risk_filter=risk_f if risk_f != 'All' else None,
        search=search or None,
        high_risk_only=high_risk,
    )
    summary = get_action_summary(payload, force=True)
    return JsonResponse({'ok': True, **summary})


@login_required
@require_POST
def ai_forecast_refresh(request):
    if not _has_perm(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.inventory.models import Item

    item_id = request.POST.get('item_id')
    refresh_all = request.POST.get('refresh_all') == '1'

    if refresh_all:
        items = Item.objects.filter(is_active=True, item_type='product', status='active')[:20]
        ok = err = 0
        for item in items:
            try:
                refresh_item_forecast(item)
                ok += 1
            except (ForecastRateLimited, OpenAINotConfigured):
                err += 1
            except Exception:
                err += 1
        return JsonResponse({'ok': True, 'refreshed': ok, 'skipped': err})

    if not item_id:
        return JsonResponse({'ok': False, 'error': 'item_id required'}, status=400)

    item = Item.objects.filter(pk=item_id).first()
    if not item:
        return JsonResponse({'ok': False, 'error': 'Item not found'}, status=404)

    try:
        fc = refresh_item_forecast(item)
    except OpenAINotConfigured as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except ForecastRateLimited as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=429)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    return JsonResponse(
        {
            'ok': True,
            'forecast_30': float(fc.forecast_30),
            'forecast_60': float(fc.forecast_60),
            'forecast_90': float(fc.forecast_90),
            'confidence': fc.confidence,
        }
    )
