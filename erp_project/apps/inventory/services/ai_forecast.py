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
from apps.inventory.utils import get_openai_api_key

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
    api_key = get_openai_api_key()
    if not api_key:
        raise OpenAINotConfigured('Configure OpenAI API key in Settings → Company')

    import urllib.request

    prompt = (
        f'Given monthly consumption data for item "{item.name}" (ID {item.pk}): '
        f'{json.dumps(monthly_data)}. '
        'Forecast next 30/60/90 day demand in units. '
        'Return ONLY valid JSON: '
        '{"item_id": <int>, "forecast_30": <number>, "forecast_60": <number>, '
        '"forecast_90": <number>, "confidence": "low|medium|high", "reasoning": "<short>"}'
    )
    body = json.dumps(
        {
            'model': 'gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': 'You are an inventory forecasting assistant. Reply with JSON only.'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.2,
        }
    ).encode('utf-8')

    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    content = payload['choices'][0]['message']['content']
    content = content.strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


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

    fc = InventoryForecast.objects.create(
        item=item,
        forecast_date=date.today(),
        forecast_30=Decimal(str(result.get('forecast_30', 0))),
        forecast_60=Decimal(str(result.get('forecast_60', 0))),
        forecast_90=Decimal(str(result.get('forecast_90', 0))),
        avg_monthly_consumption=avg_monthly,
        confidence=str(result.get('confidence', 'medium'))[:20],
        reasoning=str(result.get('reasoning', ''))[:2000],
        raw_response=json.dumps(result)[:8000],
        refreshed_at=timezone.now(),
    )
    return fc


def _unit_cost(item: Item) -> Decimal:
    if item.purchase_price and item.purchase_price > 0:
        return item.purchase_price.quantize(Decimal('0.01'))
    return Decimal('0')


def _stockout_risk(days_left: int | None, lead_time: int) -> tuple[str, str]:
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

    key_configured = bool(get_openai_api_key())
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

    raw_rows = []
    velocities = []

    for item in items.order_by('name'):
        fc = forecast_map.get(item.pk)
        adc = fc.avg_monthly_consumption if fc else Decimal('0')
        if adc > 0:
            velocities.append(float(adc))

        current_stock = stock_map.get(item.pk, Decimal('0'))
        safety = Decimal(str(item.safety_stock_qty or 0))
        lead = int(item.lead_time_days or 7)
        f30 = fc.forecast_30 if fc else Decimal('0')
        f60 = fc.forecast_60 if fc else Decimal('0')
        f90 = fc.forecast_90 if fc else Decimal('0')

        daily = (adc / Decimal('30')) if adc > 0 else Decimal('0')
        if daily > 0:
            days_left = int((current_stock / daily).quantize(Decimal('1')))
        else:
            days_left = None

        last_mv = last_move.get(item.pk)
        days_since = (today - last_mv).days if last_mv else None

        risk, risk_badge = _stockout_risk(days_left, lead)
        suggested = max(Decimal('0'), (f30 + safety - current_stock)).quantize(Decimal('0.01'))
        uc = _unit_cost(item)

        reorder_date = ''
        if fc and f30 > 0 and daily > 0:
            days_cover = int(current_stock / daily)
            reorder_date = (today + timedelta(days=max(0, days_cover - lead))).isoformat()

        trend_key, trend_icon, trend_label = _movement_trend(item.pk)

        raw_rows.append(
            {
                'item_id': item.pk,
                'item_name': item.name,
                'sku': item.item_code,
                'category_id': item.category_id,
                'avg_monthly_consumption': float(adc),
                'forecast_30': float(f30) if fc else None,
                'forecast_60': float(f60) if fc else None,
                'forecast_90': float(f90) if fc else None,
                'confidence': fc.confidence if fc else '',
                'current_stock': float(current_stock),
                'days_left': days_left,
                'days_left_display': days_left if days_left is not None else '—',
                'days_left_class': _days_left_color(days_left, lead),
                'lead_time_days': lead,
                'safety_stock': float(safety),
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
        {'key': 'avg_monthly_consumption', 'label': 'Avg Monthly', 'format': 'number'},
        {'key': 'forecast_30', 'label': 'F30D', 'format': 'number'},
        {'key': 'forecast_60', 'label': 'F60D', 'format': 'number'},
        {'key': 'forecast_90', 'label': 'F90D', 'format': 'number'},
        {'key': 'confidence', 'label': 'Confidence'},
        {'key': 'current_stock', 'label': 'Current Stock', 'format': 'number', 'align': 'right'},
        {'key': 'days_left_display', 'label': 'Days Left'},
        {'key': 'stockout_risk', 'label': 'Stockout Risk'},
        {'key': 'suggested_order_qty', 'label': 'Suggested Order Qty', 'format': 'number', 'align': 'right'},
        {'key': 'status', 'label': 'Status'},
        {'key': 'trend_label', 'label': 'Trend'},
        {'key': 'recommended_reorder_date', 'label': 'Reorder Date'},
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
