"""Expense forecast from vendor bills and expense claims."""
from __future__ import annotations

from .ai_client import OpenAINotConfigured, call_openai_json, get_cached, set_cached
from .utils import expense_by_category_monthly, next_month_keys, today

SYSTEM = """You are a financial forecasting assistant. Forecast monthly expenses by category from historical vendor bills.
Respond ONLY in JSON:
{"forecast_by_category":[{"category":"name","months":[{"month":"YYYY-MM","value":number,"confidence":"high|medium|low"}]}],
 "summary":"one line","alerts":[]}
No markdown."""


def build_expense_forecast_context(*, forecast_months: int = 6, force_refresh: bool = False) -> dict:
    forecast_months = 6 if forecast_months not in (3, 6) else forecast_months
    month_keys, cat_data = expense_by_category_monthly(12)
    cache_payload = {'report': 'expense', 'months': forecast_months, 'cats': list(cat_data.keys())}

    if not force_refresh:
        cached = get_cached('expense', cache_payload)
        if cached:
            return _assemble(month_keys, cat_data, cached, forecast_months)

    total_by_month = {k: sum(cat_data[c].get(k, 0) for c in cat_data) for k in month_keys}
    if sum(total_by_month.values()) <= 0:
        return _empty(month_keys, cat_data, forecast_months)

    historical_payload = [
        {'month': k, 'total': round(total_by_month[k], 2), 'by_category': {c: round(cat_data[c].get(k, 0), 2) for c in cat_data}}
        for k in month_keys
    ]

    try:
        ai = call_openai_json(
            system=SYSTEM,
            user_payload={
                'historical': historical_payload,
                'categories': list(cat_data.keys()),
                'forecast_months': forecast_months,
                'future_months': next_month_keys(forecast_months),
            },
        )
        by_cat = ai.get('forecast_by_category') or []
        summary = str(ai.get('summary', '')).strip()
        alerts = list(ai.get('alerts') or [])
        source = 'openai'
    except (OpenAINotConfigured, Exception):
        by_cat = _heuristic_by_category(cat_data, month_keys, forecast_months)
        summary = 'Rule-based expense forecast from recent vendor bill averages by category.'
        alerts = []
        source = 'heuristic'

    result = {'forecast_by_category': by_cat, 'summary': summary, 'alerts': alerts, 'source': source}
    set_cached('expense', cache_payload, result)
    return _assemble(month_keys, cat_data, result, forecast_months)


def _heuristic_by_category(cat_data, month_keys, forecast_months):
    future = next_month_keys(forecast_months)
    out = []
    for cat, months in cat_data.items():
        vals = [months.get(k, 0) for k in month_keys if months.get(k, 0) > 0]
        avg = sum(vals) / len(vals) if vals else 0
        out.append({
            'category': cat,
            'months': [{'month': fm, 'value': round(avg, 2), 'confidence': 'low'} for fm in future],
        })
    return out


def _empty(month_keys, cat_data, forecast_months):
    from apps.inventory.utils import get_openai_api_key
    return {
        'month_keys': month_keys,
        'categories': list(cat_data.keys()),
        'historical_stacked': {},
        'forecast_by_category': [],
        'table_rows': [],
        'summary': '',
        'alerts': [],
        'forecast_months': forecast_months,
        'has_data': False,
        'from_cache': False,
        'openai_configured': bool(get_openai_api_key()),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }


def _assemble(month_keys, cat_data, result, forecast_months):
    from apps.inventory.utils import get_openai_api_key

    forecast_by_cat = result.get('forecast_by_category') or []
    table_rows = []
    category_list = list(cat_data.keys())
    for fk in next_month_keys(forecast_months):
        row = {'month': fk, 'is_forecast': True, 'cells': []}
        total = 0.0
        for cat in category_list:
            val = 0.0
            for block in forecast_by_cat:
                if block.get('category') == cat:
                    for m in block.get('months') or []:
                        if m.get('month') == fk:
                            val = float(m.get('value', 0) or 0)
            row[cat] = round(val, 2)
            row['cells'].append({'category': cat, 'value': round(val, 2)})
            total += val
        row['total'] = round(total, 2)
        table_rows.append(row)

    hist_stacked = {k: {c: round(cat_data[c].get(k, 0), 2) for c in cat_data} for k in month_keys}

    return {
        'month_keys': month_keys,
        'categories': list(cat_data.keys()),
        'historical_stacked': hist_stacked,
        'forecast_by_category': forecast_by_cat,
        'table_rows': table_rows,
        'chart': {
            'labels': month_keys + [r['month'] for r in table_rows],
            'categories': list(cat_data.keys()),
            'historical': hist_stacked,
            'forecast_rows': table_rows,
        },
        'summary': result.get('summary', ''),
        'alerts': result.get('alerts', []),
        'forecast_months': forecast_months,
        'has_data': True,
        'from_cache': result.get('from_cache', False),
        'openai_configured': bool(get_openai_api_key()),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }
