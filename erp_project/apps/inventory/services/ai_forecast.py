"""AI forecasting service using OpenAI."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Max, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.inventory.models import Category, Item, Stock, StockMovement, Warehouse
from apps.inventory.models_reporting import InventoryForecast
from apps.inventory.utils import get_openai_api_key, is_ai_available
from apps.inventory.services.supplier_lead_time import effective_lead_time_days
from apps.inventory.services.inventory_abc import classify_abc_for_items, abc_badge
from apps.inventory.services.carrying_cost import row_carrying_cost
from apps.inventory.services.demand_seasonality import detect_seasonality, apply_seasonal_forecast

REFRESH_COOLDOWN_HOURS = 1
DEAD_DAYS = 180
SLOW_MONTHLY_THRESHOLD = Decimal('2')

# Badge CSS classes (match inventory aging / Tailwind-style tokens)
BADGE = {
    'risk_high': 'fc-badge fc-badge-red',
    'risk_medium': 'fc-badge fc-badge-orange',
    'risk_low': 'fc-badge fc-badge-green',
    'status_fast': 'fc-badge fc-badge-blue',
    'status_slow': 'fc-badge fc-badge-yellow',
    'status_dead': 'fc-badge fc-badge-gray',
    'status_overstock': 'fc-badge fc-badge-purple',
    'status_normal': 'fc-text-normal',
}
DAYS_COLOR = {
    'critical': 'fc-days-critical',
    'warning': 'fc-days-warning',
    'good': 'fc-days-good',
}


class OpenAINotConfigured(Exception):
    pass


class ForecastRateLimited(Exception):
    pass


def _monthly_consumption(item_id: int, months: int = 12) -> list[dict]:
    since = date.today().replace(day=1) - timedelta(days=months * 31)
    qs = (
        StockMovement.objects.filter(
            item_id=item_id,
            movement_type='out',
            movement_date__gte=since,
        )
        .annotate(month=TruncMonth('movement_date'))
        .values('month')
        .annotate(qty=Coalesce(Sum('quantity'), Decimal('0')))
        .order_by('month')
    )
    return [{'month': r['month'].strftime('%Y-%m'), 'qty': float(r['qty'] or 0)} for r in qs]


def _can_refresh(item_id: int) -> bool:
    latest = (
        InventoryForecast.objects.filter(item_id=item_id)
        .order_by('-refreshed_at')
        .first()
    )
    if not latest or not latest.refreshed_at:
        return True
    delta = timezone.now() - latest.refreshed_at
    return delta.total_seconds() >= REFRESH_COOLDOWN_HOURS * 3600


def fetch_forecast_from_openai(item: Item, monthly_data: list[dict]) -> dict:
    from apps.core.ai_knowledge import get_ai_knowledge_prompt_block
    from apps.core.models import AiModuleKnowledge
    from apps.core.openai_gateway import call_openai_raw, parse_openai_json

    knowledge = get_ai_knowledge_prompt_block(AiModuleKnowledge.MODULE_INVENTORY)
    prompt = (
        f'Given monthly consumption data for item "{item.name}" (ID {item.pk}): '
        f'{json.dumps(monthly_data)}. '
        'Forecast next 30/60/90 day demand in units. '
        'Return ONLY valid JSON: '
        '{"item_id": <int>, "forecast_30": <number>, "forecast_60": <number>, '
        '"forecast_90": <number>, "confidence": "low|medium|high", "reasoning": "<short>"}'
        f'{knowledge}'
    )
    body = {
        'model': 'gpt-4o-mini',
        'messages': [
            {
                'role': 'system',
                'content': 'You are an inventory forecasting assistant. Reply with JSON only.',
            },
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.2,
    }
    payload = call_openai_raw(body, feature='inventory_forecast')
    content = payload['choices'][0]['message']['content']
    return parse_openai_json(content)


def refresh_item_forecast(item: Item, *, force: bool = False) -> InventoryForecast:
    if not force and not _can_refresh(item.pk):
        raise ForecastRateLimited(
            f'Rate limit: wait {REFRESH_COOLDOWN_HOURS}h between refreshes for this item.'
        )
    monthly = _monthly_consumption(item.pk)
    avg_monthly = Decimal('0')
    if monthly:
        avg_monthly = (
            sum(Decimal(str(m['qty'])) for m in monthly) / Decimal(len(monthly))
        ).quantize(Decimal('0.01'))

    no_history = not monthly or avg_monthly <= 0
    confidence_override = None
    reasoning_extra = ''

    try:
        result = fetch_forecast_from_openai(item, monthly)
    except OpenAINotConfigured:
        raise
    except Exception as exc:
        adc = avg_monthly / Decimal('30') if avg_monthly else Decimal('0')
        result = {
            'forecast_30': float((adc * 30).quantize(Decimal('0.01'))),
            'forecast_60': float((adc * 60).quantize(Decimal('0.01'))),
            'forecast_90': float((adc * 90).quantize(Decimal('0.01'))),
            'confidence': 'low',
            'reasoning': f'Heuristic fallback (API error: {exc})',
        }

    if no_history:
        cat_avg = _category_avg_monthly(item.category_id)
        if cat_avg > 0:
            daily = cat_avg / Decimal('30')
            result['forecast_30'] = float((daily * 30).quantize(Decimal('0.01')))
            result['forecast_60'] = float((daily * 60).quantize(Decimal('0.01')))
            result['forecast_90'] = float((daily * 90).quantize(Decimal('0.01')))
            avg_monthly = cat_avg
            confidence_override = 'low / no-history'
            reasoning_extra = ' Category-average fallback — no item sales history.'

    conf = confidence_override or str(result.get('confidence', 'medium'))[:20]
    reasoning = str(result.get('reasoning', ''))[:2000] + reasoning_extra

    fc = InventoryForecast.objects.create(
        item=item,
        forecast_date=date.today(),
        forecast_30=Decimal(str(result.get('forecast_30', 0))),
        forecast_60=Decimal(str(result.get('forecast_60', 0))),
        forecast_90=Decimal(str(result.get('forecast_90', 0))),
        avg_monthly_consumption=avg_monthly,
        confidence=conf[:20],
        reasoning=reasoning[:2000],
        raw_response=json.dumps(result)[:8000],
        refreshed_at=timezone.now(),
    )
    return fc


def _unit_cost(item: Item) -> Decimal:
    if item.purchase_price and item.purchase_price > 0:
        return item.purchase_price.quantize(Decimal('0.01'))
    return Decimal('0')


def _category_avg_monthly(category_id: int | None) -> Decimal:
    if not category_id:
        return Decimal('0')
    since = date.today().replace(day=1) - timedelta(days=365)
    item_ids = list(
        Item.objects.filter(
            category_id=category_id,
            is_active=True,
            item_type='product',
            status='active',
        ).values_list('pk', flat=True)[:200]
    )
    if not item_ids:
        return Decimal('0')
    total = (
        StockMovement.objects.filter(
            item_id__in=item_ids,
            movement_type='out',
            movement_date__gte=since,
        ).aggregate(t=Coalesce(Sum('quantity'), Decimal('0')))['t']
        or Decimal('0')
    )
    return (total / Decimal(max(len(item_ids), 1)) / Decimal('12')).quantize(Decimal('0.01'))


def _no_history_fallback(item: Item, category_avgs: dict[int, Decimal]) -> tuple[Decimal, Decimal, Decimal, str]:
    """Estimate F30/F60/F90 from category average when item has no consumption history."""
    cat_avg = category_avgs.get(item.category_id or 0, Decimal('0'))
    if cat_avg <= 0:
        return Decimal('0'), Decimal('0'), Decimal('0'), ''
    lead = int(item.lead_time_days or 7)
    daily = cat_avg / Decimal('30')
    f30 = (daily * Decimal('30')).quantize(Decimal('0.01'))
    f60 = (daily * Decimal('60')).quantize(Decimal('0.01'))
    f90 = (daily * Decimal('90')).quantize(Decimal('0.01'))
    note = f'Category-average fallback (no item history); lead {lead}d'
    return f30, f60, f90, note


def _stockout_risk(
    days_left: int | None,
    lead_time: int,
    *,
    current_stock: Decimal,
    has_demand: bool,
) -> tuple[str, str]:
    if current_stock <= 0 and has_demand:
        return 'High', BADGE['risk_high']
    if current_stock <= 0:
        return 'High', BADGE['risk_high']
    if days_left is None:
        return 'Low', BADGE['risk_low']
    if days_left < lead_time:
        return 'High', BADGE['risk_high']
    if days_left < 30:
        return 'Medium', BADGE['risk_medium']
    return 'Low', BADGE['risk_low']


def _days_left_color(days_left: int | None, lead_time: int) -> str:
    if days_left is None:
        return ''
    if days_left < lead_time:
        return DAYS_COLOR['critical']
    if days_left < 30:
        return DAYS_COLOR['warning']
    return DAYS_COLOR['good']


def _movement_trend(item_id: int) -> tuple[str, str, str]:
    """Return (key, icon, label) for 90d vs prior 90d consumption."""
    today = date.today()
    last_start = today - timedelta(days=90)
    prior_start = today - timedelta(days=180)

    def _sum_out(since, until):
        return (
            StockMovement.objects.filter(
                item_id=item_id,
                movement_type='out',
                movement_date__gte=since,
                movement_date__lt=until,
            ).aggregate(t=Coalesce(Sum('quantity'), Decimal('0')))['t']
            or Decimal('0')
        )

    last_90 = _sum_out(last_start, today + timedelta(days=1))
    prior_90 = _sum_out(prior_start, last_start)
    if prior_90 <= 0 and last_90 <= 0:
        return 'stable', '→', 'Stable'
    if prior_90 <= 0:
        return 'up', '↑', 'Rising'
    change = (last_90 - prior_90) / prior_90
    if change >= Decimal('0.10'):
        return 'up', '↑', 'Rising'
    if change <= Decimal('-0.10'):
        return 'down', '↓', 'Falling'
    return 'stable', '→', 'Stable'


def _status_badge(status: str) -> str:
    return {
        'Fast Mover': BADGE['status_fast'],
        'Slow': BADGE['status_slow'],
        'Dead': BADGE['status_dead'],
        'Overstocked': BADGE['status_overstock'],
        'Normal': BADGE['status_normal'],
    }.get(status, BADGE['status_normal'])


def _classify_status(
    *,
    days_since_movement: int | None,
    avg_monthly: Decimal,
    current_stock: Decimal,
    f90: Decimal,
    safety: Decimal,
    is_fast_mover: bool,
) -> str:
    if days_since_movement is not None and days_since_movement >= DEAD_DAYS:
        return 'Dead'
    if avg_monthly < SLOW_MONTHLY_THRESHOLD:
        return 'Slow'
    target = f90 + safety
    if target > 0 and current_stock > target:
        return 'Overstocked'
    if is_fast_mover:
        return 'Fast Mover'
    return 'Normal'


def build_ai_forecast_report(
    *,
    warehouse_id=None,
    category_id=None,
    status_filter=None,
    stockout_risk_filter=None,
    search=None,
    high_risk_only=False,
    item_id=None,
) -> dict:
    from apps.inventory.reports._common import active_product_items

    key_configured = is_ai_available()
    today = date.today()
    items = active_product_items().select_related('category')
    if category_id:
        items = items.filter(category_id=category_id)
    if item_id:
        items = items.filter(pk=item_id)
    if search:
        from django.db.models import Q

        items = items.filter(Q(name__icontains=search) | Q(item_code__icontains=search))

    item_ids = list(items.values_list('pk', flat=True))
    if not item_ids:
        return _empty_report(key_configured)

    # Bulk aggregates
    stock_qs = Stock.objects.filter(item_id__in=item_ids, quantity__gt=0)
    if warehouse_id:
        stock_qs = stock_qs.filter(warehouse_id=warehouse_id)
    stock_map: dict[int, Decimal] = {}
    for row in stock_qs.values('item_id').annotate(t=Coalesce(Sum('quantity'), Decimal('0'))):
        stock_map[row['item_id']] = (row['t'] or Decimal('0')).quantize(Decimal('0.01'))

    last_move = {
        r['item_id']: r['last_mv']
        for r in StockMovement.objects.filter(item_id__in=item_ids)
        .values('item_id')
        .annotate(last_mv=Max('movement_date'))
    }

    forecast_map = {}
    for fc in InventoryForecast.objects.filter(item_id__in=item_ids).order_by('item_id', '-refreshed_at'):
        if fc.item_id not in forecast_map:
            forecast_map[fc.item_id] = fc

    category_avgs: dict[int, Decimal] = {}
    for cid in items.values_list('category_id', flat=True).distinct():
        if cid:
            category_avgs[cid] = _category_avg_monthly(cid)

    abc_map = classify_abc_for_items(list(items))

    raw_rows = []
    velocities = []

    for item in items.order_by('name'):
        fc = forecast_map.get(item.pk)
        adc = fc.avg_monthly_consumption if fc else Decimal('0')
        if adc > 0:
            velocities.append(float(adc))

        current_stock = stock_map.get(item.pk, Decimal('0'))
        safety = Decimal(str(item.safety_stock_qty or 0))
        lead, lead_source = effective_lead_time_days(item)
        f30 = fc.forecast_30 if fc else Decimal('0')
        f60 = fc.forecast_60 if fc else Decimal('0')
        f90 = fc.forecast_90 if fc else Decimal('0')
        confidence = fc.confidence if fc else ''
        season_note = ''

        adc = fc.avg_monthly_consumption if fc else Decimal('0')
        used_fallback = False
        if (not fc or adc <= 0) and item.category_id:
            f30, f60, f90, fb_note = _no_history_fallback(item, category_avgs)
            if f30 > 0:
                adc = category_avgs.get(item.category_id or 0, Decimal('0'))
                confidence = confidence or 'low / no-history'
                season_note = fb_note
                used_fallback = True

        if fc and adc > 0:
            season = detect_seasonality(item.pk)
            f30, f60, f90, adj_note = apply_seasonal_forecast(f30, f60, f90, season)
            if adj_note:
                season_note = adj_note

        daily = (adc / Decimal('30')) if adc > 0 else Decimal('0')
        if daily > 0:
            days_left = int((current_stock / daily).quantize(Decimal('1')))
        else:
            days_left = 0 if current_stock <= 0 else None

        has_demand = (
            adc > 0
            or f30 > 0
            or used_fallback
            or (fc is not None and (fc.forecast_30 or 0) > 0)
        )

        last_mv = last_move.get(item.pk)
        days_since = (today - last_mv).days if last_mv else None

        risk, risk_badge = _stockout_risk(
            days_left, lead, current_stock=current_stock, has_demand=has_demand,
        )
        abc_class = abc_map.get(item.pk, 'C')
        if abc_class == 'A' and risk == 'Medium':
            risk, risk_badge = 'High', BADGE['risk_high']

        suggested = max(Decimal('0'), (f30 + safety - current_stock)).quantize(Decimal('0.01'))
        uc = _unit_cost(item)

        reorder_date = ''
        if (fc or used_fallback) and f30 > 0 and daily > 0:
            days_cover = int(current_stock / daily)
            reorder_date = (today + timedelta(days=max(0, days_cover - lead))).isoformat()

        trend_key, trend_icon, trend_label = _movement_trend(item.pk)

        dead_val = float((current_stock * uc).quantize(Decimal('0.01'))) if days_since is not None and days_since >= DEAD_DAYS else 0.0
        excess = float(max(Decimal('0'), current_stock - (f90 + safety)).quantize(Decimal('0.01')))
        over_val = float((max(Decimal('0'), current_stock - (f90 + safety)) * uc).quantize(Decimal('0.01')))
        carrying = row_carrying_cost(over_val, dead_val)

        f30_disp = float(f30) if (fc or used_fallback or f30 > 0) else None
        f60_disp = float(f60) if (fc or used_fallback or f60 > 0) else None
        f90_disp = float(f90) if (fc or used_fallback or f90 > 0) else None

        raw_rows.append(
            {
                'item_id': item.pk,
                'item_name': item.name,
                'sku': item.item_code,
                'category_id': item.category_id,
                'abc_class': abc_class,
                'abc_badge': abc_badge(abc_class),
                'avg_monthly_consumption': float(adc),
                'forecast_30': f30_disp,
                'forecast_60': f60_disp,
                'forecast_90': f90_disp,
                'confidence': confidence,
                'seasonality_note': season_note,
                'lead_time_days': lead,
                'lead_time_source': lead_source,
                'current_stock': float(current_stock),
                'days_left': days_left,
                'days_left_display': days_left if days_left is not None else '—',
                'days_left_class': _days_left_color(days_left, lead),
                'safety_stock': float(safety),
                'carrying_display': carrying['carrying_display'],
                'carrying_monthly_aed': carrying['carrying_monthly_aed'],
                'stockout_risk': risk,
                'stockout_risk_badge': risk_badge,
                'suggested_order_qty': float(suggested),
                'suggested_order_bold': suggested > 0,
                'status': 'Normal',  # second pass
                'status_badge': BADGE['status_normal'],
                'trend': trend_key,
                'trend_icon': trend_icon,
                'trend_label': trend_label,
                'trend_class': {
                    'up': 'fc-trend-up',
                    'down': 'fc-trend-down',
                    'stable': 'fc-trend-stable',
                }.get(trend_key, 'fc-trend-stable'),
                'recommended_reorder_date': reorder_date,
                'last_refreshed': fc.refreshed_at.isoformat() if fc and fc.refreshed_at else '',
                'last_movement_date': last_mv.isoformat() if last_mv else '',
                'days_since_movement': days_since,
                'unit_cost': float(uc),
                'dead_value': float((current_stock * uc).quantize(Decimal('0.01')))
                if days_since is not None and days_since >= DEAD_DAYS
                else 0.0,
                'excess_qty': float(
                    max(Decimal('0'), current_stock - (f90 + safety)).quantize(Decimal('0.01'))
                ),
                'overstock_value': float(
                    (
                        max(Decimal('0'), current_stock - (f90 + safety)) * uc
                    ).quantize(Decimal('0.01'))
                ),
            }
        )

    # Fast mover threshold — top 20% by avg monthly consumption
    fast_threshold = None
    if velocities:
        sorted_v = sorted(velocities)
        idx = max(0, int(len(sorted_v) * 0.8) - 1)
        fast_threshold = sorted_v[idx]

    for row in raw_rows:
        days_since = row['days_since_movement']
        adc = Decimal(str(row['avg_monthly_consumption']))
        is_fast = fast_threshold is not None and float(adc) >= fast_threshold and adc > 0
        status = _classify_status(
            days_since_movement=days_since,
            avg_monthly=adc,
            current_stock=Decimal(str(row['current_stock'])),
            f90=Decimal(str(row['forecast_90'] or 0)),
            safety=Decimal(str(row['safety_stock'])),
            is_fast_mover=is_fast,
        )
        row['status'] = status
        row['status_badge'] = _status_badge(status)

    # Apply filters
    rows = raw_rows
    if high_risk_only or stockout_risk_filter == 'High':
        rows = [r for r in rows if r['stockout_risk'] == 'High']
    elif stockout_risk_filter in ('Medium', 'Low'):
        rows = [r for r in rows if r['stockout_risk'] == stockout_risk_filter]

    if status_filter and status_filter != 'All':
        status_map = {
            'Fast Mover': 'Fast Mover',
            'Slow': 'Slow',
            'Dead': 'Dead',
            'Overstocked': 'Overstocked',
            'Normal': 'Normal',
        }
        target = status_map.get(status_filter, status_filter)
        rows = [r for r in rows if r['status'] == target]

    # KPIs from full dataset (before row filters except warehouse/category/search already applied)
    stockout_risk_count = sum(1 for r in raw_rows if r['stockout_risk'] == 'High')
    dead_stock_value = sum(r['dead_value'] for r in raw_rows)
    overstock_value = sum(r['overstock_value'] for r in raw_rows)

    columns = [
        {'key': 'item_name', 'label': 'Item'},
        {'key': 'sku', 'label': 'SKU'},
        {'key': 'abc_class', 'label': 'ABC'},
        {'key': 'avg_monthly_consumption', 'label': 'Avg Monthly', 'format': 'number'},
        {'key': 'forecast_30', 'label': 'F30D', 'format': 'number'},
        {'key': 'forecast_60', 'label': 'F60D', 'format': 'number'},
        {'key': 'forecast_90', 'label': 'F90D', 'format': 'number'},
        {'key': 'confidence', 'label': 'Confidence'},
        {'key': 'current_stock', 'label': 'Current Stock', 'format': 'number', 'align': 'right'},
        {'key': 'days_left_display', 'label': 'Days Left'},
        {'key': 'stockout_risk', 'label': 'Stockout Risk'},
        {'key': 'lead_time_days', 'label': 'Lead (d)'},
        {'key': 'suggested_order_qty', 'label': 'Suggested Order Qty', 'format': 'number', 'align': 'right'},
        {'key': 'carrying_display', 'label': 'Carrying Cost'},
        {'key': 'status', 'label': 'Status'},
        {'key': 'trend_label', 'label': 'Trend'},
        {'key': 'recommended_reorder_date', 'label': 'Reorder Date'},
        {'key': 'seasonality_note', 'label': 'Seasonality'},
    ]

    return {
        'title': 'AI Forecast Report',
        'report_type': 'ai_forecast',
        'columns': columns,
        'rows': rows,
        'all_rows': raw_rows,
        'summary': {
            'items_with_forecast': sum(1 for r in raw_rows if r['forecast_30'] is not None),
            'total_items': len(raw_rows),
            'stockout_risk_count': stockout_risk_count,
            'dead_stock_value': float(Decimal(str(dead_stock_value)).quantize(Decimal('0.01'))),
            'overstock_value': float(Decimal(str(overstock_value)).quantize(Decimal('0.01'))),
        },
        'filters': {
            'categories': Category.objects.filter(is_active=True).order_by('name'),
            'warehouses': Warehouse.objects.filter(status='active', is_active=True).order_by('name'),
            'status_choices': ['All', 'Fast Mover', 'Slow', 'Dead', 'Overstocked', 'Normal'],
            'risk_choices': ['All', 'High', 'Medium', 'Low'],
        },
        'openai_configured': key_configured,
    }


def _empty_report(key_configured: bool) -> dict:
    return {
        'title': 'AI Forecast Report',
        'report_type': 'ai_forecast',
        'columns': [],
        'rows': [],
        'all_rows': [],
        'summary': {
            'items_with_forecast': 0,
            'total_items': 0,
            'stockout_risk_count': 0,
            'dead_stock_value': 0.0,
            'overstock_value': 0.0,
        },
        'filters': {
            'categories': Category.objects.filter(is_active=True).order_by('name'),
            'warehouses': Warehouse.objects.filter(status='active', is_active=True).order_by('name'),
            'status_choices': ['All', 'Fast Mover', 'Slow', 'Dead', 'Overstocked', 'Normal'],
            'risk_choices': ['All', 'High', 'Medium', 'Low'],
        },
        'openai_configured': key_configured,
    }
