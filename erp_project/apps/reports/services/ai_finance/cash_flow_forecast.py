"""Cash flow forecast — AI + heuristic."""
from __future__ import annotations

from .ai_client import (
    OpenAINotConfigured,
    call_openai_json,
    get_cached,
    linear_forecast,
    normalize_forecast_rows,
    set_cached,
)
from .utils import next_month_keys, payment_cash_flow_monthly

SYSTEM = """You are a financial forecasting assistant for a UAE ERP.
Given monthly historical cash inflows, outflows, and closing balances, forecast the next N months.
Respond ONLY in JSON:
{"forecast":[{"month":"YYYY-MM","inflow":number,"outflow":number,"closing_balance":number,"confidence":"high|medium|low"}],
 "summary":"one line insight","alerts":["months where cash may go negative"]}
No markdown."""


def build_cash_flow_forecast_context(*, forecast_months: int = 6, force_refresh: bool = False) -> dict:
    forecast_months = 6 if forecast_months not in (3, 6) else forecast_months
    historical = payment_cash_flow_monthly(12)
    cache_payload = {'report': 'cash_flow', 'months': forecast_months, 'hist': historical[-3:]}

    if not force_refresh:
        cached = get_cached('cash_flow', cache_payload)
        if cached:
            return _assemble_context(historical, cached, forecast_months)

    if len([h for h in historical if h['inflow'] or h['outflow']]) < 2:
        return _empty_context(historical, forecast_months)

    future_keys = next_month_keys(forecast_months)
    ai_result = None
    try:
        ai_result = call_openai_json(
            system=SYSTEM,
            user_payload={
                'historical': historical,
                'forecast_months': forecast_months,
                'future_months': future_keys,
            },
        )
    except OpenAINotConfigured:
        ai_result = _heuristic(historical, forecast_months)
    except Exception:
        ai_result = _heuristic(historical, forecast_months)

    result = {
        'summary': str(ai_result.get('summary', '')).strip(),
        'alerts': list(ai_result.get('alerts') or []),
        'forecast': ai_result.get('forecast') or [],
        'openai_used': 'forecast' in ai_result and ai_result != _heuristic(historical, forecast_months),
        'source': 'openai' if isinstance(ai_result.get('forecast'), list) and ai_result.get('summary') else 'heuristic',
    }
    set_cached('cash_flow', cache_payload, result)
    return _assemble_context(historical, result, forecast_months)


def _heuristic(historical: list, forecast_months: int) -> dict:
    nets = [h['net'] for h in historical]
    last_bal = historical[-1]['closing_balance'] if historical else 0.0
    avg_net = sum(nets[-3:]) / max(len(nets[-3:]), 1)
    forecast = []
    bal = last_bal
    alerts = []
    for month in next_month_keys(forecast_months):
        bal += avg_net
        if bal < 0:
            alerts.append(f'Cash may go negative in {month}')
        forecast.append({
            'month': month,
            'inflow': round(max(0, avg_net), 2) if avg_net > 0 else 0,
            'outflow': round(abs(avg_net), 2) if avg_net < 0 else 0,
            'closing_balance': round(bal, 2),
            'confidence': 'low',
        })
    return {
        'forecast': forecast,
        'summary': 'Rule-based cash forecast from recent net cash movement.',
        'alerts': alerts,
    }


def _empty_context(historical, forecast_months):
    return {
        'historical': historical,
        'forecast_rows': [],
        'combined_chart': {'labels': [], 'actual_balance': [], 'forecast_balance': []},
        'table_rows': [],
        'summary': '',
        'alerts': [],
        'forecast_months': forecast_months,
        'has_data': False,
        'from_cache': False,
        'openai_configured': bool(__import__('apps.inventory.utils', fromlist=['get_openai_api_key']).get_openai_api_key()),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }


def _assemble_context(historical, result, forecast_months):
    from apps.inventory.utils import get_openai_api_key, is_ai_available

    forecast = result.get('forecast') or []
    table_rows = []
    for h in historical:
        table_rows.append({
            'month': h['month'],
            'actual_inflow': h['inflow'],
            'actual_outflow': h['outflow'],
            'actual_balance': h['closing_balance'],
            'forecast_balance': None,
            'confidence': '',
            'is_forecast': False,
        })
    for f in forecast:
        table_rows.append({
            'month': f.get('month', ''),
            'actual_inflow': None,
            'actual_outflow': None,
            'actual_balance': None,
            'forecast_balance': f.get('closing_balance', f.get('value')),
            'confidence': f.get('confidence', 'medium'),
            'is_forecast': True,
        })

    labels = [r['month'] for r in table_rows]
    actual_bal = [r['actual_balance'] if not r['is_forecast'] else None for r in table_rows]
    forecast_bal = [r['forecast_balance'] if r['is_forecast'] else r['actual_balance'] for r in table_rows]

    return {
        'historical': historical,
        'forecast_rows': forecast,
        'combined_chart': {
            'labels': labels,
            'actual_balance': actual_bal,
            'forecast_balance': forecast_bal,
        },
        'table_rows': table_rows,
        'summary': result.get('summary', ''),
        'alerts': result.get('alerts', []),
        'forecast_months': forecast_months,
        'has_data': True,
        'from_cache': result.get('from_cache', False),
        'openai_configured': is_ai_available(),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }
