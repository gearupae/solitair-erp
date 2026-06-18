"""Revenue forecast from sales invoices."""
from __future__ import annotations

from .ai_client import (
    OpenAINotConfigured,
    call_openai_json,
    get_cached,
    linear_forecast,
    normalize_forecast_rows,
    set_cached,
)
from .utils import invoice_revenue_monthly, next_month_keys, today

SYSTEM = """You are a financial forecasting assistant. Forecast monthly revenue from historical invoice data.
Respond ONLY in JSON:
{"forecast":[{"month":"YYYY-MM","value":number,"confidence":"high|medium|low"}],
 "summary":"one line","growth_trend_pct":number,"alerts":[]}
No markdown."""


def build_revenue_forecast_context(*, forecast_months: int = 6, force_refresh: bool = False) -> dict:
    forecast_months = 6 if forecast_months not in (3, 6) else forecast_months
    historical = invoice_revenue_monthly(12)
    cache_payload = {'report': 'revenue', 'months': forecast_months, 'hist': historical[-4:]}

    if not force_refresh:
        cached = get_cached('revenue', cache_payload)
        if cached:
            return _assemble(historical, cached, forecast_months)

    values = [h['value'] for h in historical if h['value'] > 0]
    if len(values) < 2:
        return _empty(historical, forecast_months)

    try:
        ai = call_openai_json(
            system=SYSTEM,
            user_payload={'historical': historical, 'forecast_months': forecast_months},
        )
        forecast = normalize_forecast_rows(ai.get('forecast', []))
        summary = str(ai.get('summary', '')).strip()
        growth = ai.get('growth_trend_pct')
        alerts = list(ai.get('alerts') or [])
        source = 'openai'
    except (OpenAINotConfigured, Exception):
        ref = today()
        y, m = ref.year, ref.month + 1
        if m > 12:
            y, m = y + 1, 1
        forecast = linear_forecast(values, forecast_months, y, m)
        summary = 'Rule-based revenue forecast from recent invoice totals.'
        growth = _growth_pct(values)
        alerts = []
        source = 'heuristic'

    result = {'forecast': forecast, 'summary': summary, 'growth_trend_pct': growth, 'alerts': alerts, 'source': source}
    set_cached('revenue', cache_payload, result)
    return _assemble(historical, result, forecast_months)


def _growth_pct(values: list[float]) -> float:
    if len(values) < 2 or values[0] == 0:
        return 0.0
    return round((values[-1] - values[0]) / values[0] * 100, 1)


def _empty(historical, forecast_months):
    from apps.inventory.utils import get_openai_api_key
    return {
        'historical': historical,
        'forecast_rows': [],
        'table_rows': [],
        'chart': {'labels': [], 'actual': [], 'forecast': []},
        'summary': '',
        'growth_trend_pct': 0,
        'alerts': [],
        'forecast_months': forecast_months,
        'has_data': False,
        'from_cache': False,
        'openai_configured': bool(get_openai_api_key()),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }


def _assemble(historical, result, forecast_months):
    from apps.inventory.utils import get_openai_api_key

    forecast = result.get('forecast') or []
    table_rows = []
    for h in historical:
        table_rows.append({
            'month': h['month'],
            'actual': h['value'],
            'forecast': None,
            'confidence': '',
            'is_forecast': False,
        })
    for f in forecast:
        table_rows.append({
            'month': f['month'],
            'actual': None,
            'forecast': f['value'],
            'confidence': f.get('confidence', 'medium'),
            'is_forecast': True,
        })

    labels = [r['month'] for r in table_rows]
    return {
        'historical': historical,
        'forecast_rows': forecast,
        'table_rows': table_rows,
        'chart': {
            'labels': labels,
            'actual': [r['actual'] for r in table_rows],
            'forecast': [r['forecast'] if r['is_forecast'] else r['actual'] for r in table_rows],
        },
        'summary': result.get('summary', ''),
        'growth_trend_pct': result.get('growth_trend_pct', 0),
        'alerts': result.get('alerts', []),
        'forecast_months': forecast_months,
        'has_data': True,
        'from_cache': result.get('from_cache', False),
        'openai_configured': bool(get_openai_api_key()),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }
