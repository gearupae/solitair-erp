"""Receivables collection forecast."""
from __future__ import annotations

from datetime import timedelta

from .ai_client import OpenAINotConfigured, call_openai_json, get_cached, set_cached
from .utils import customer_avg_days_to_pay, open_invoices_for_collection, today

SYSTEM = """You are a collections analyst. Predict when open invoices will likely be paid.
Respond ONLY in JSON:
{"invoices":[{"invoice_id":int,"predicted_pay_date":"YYYY-MM-DD","probability_pct":0-100,
"risk":"low|medium|high","reason":"one sentence"}],
 "aging_summary":{"current":number,"30_days":number,"60_days":number,"90_plus":number},
 "summary":"one line","alerts":[]}
Use invoice_id from input only. No markdown."""


def build_receivables_forecast_context(*, force_refresh: bool = False) -> dict:
    open_rows = open_invoices_for_collection()
    cache_payload = {'report': 'receivables', 'count': len(open_rows), 'total': sum(r['amount'] for r in open_rows)}

    if not force_refresh:
        cached = get_cached('receivables', cache_payload)
        if cached:
            return _assemble(open_rows, cached)

    if not open_rows:
        return _empty()

    cust_stats = customer_avg_days_to_pay()
    payload = {
        'open_invoices': open_rows[:80],
        'customer_avg_days': {str(k): round(v, 1) for k, v in list(cust_stats.items())[:40]},
    }

    try:
        ai = call_openai_json(system=SYSTEM, user_payload=payload)
        inv_forecasts = {int(x['invoice_id']): x for x in (ai.get('invoices') or []) if x.get('invoice_id')}
        summary = str(ai.get('summary', '')).strip()
        aging = ai.get('aging_summary') or {}
        alerts = list(ai.get('alerts') or [])
        source = 'openai'
    except (OpenAINotConfigured, Exception):
        inv_forecasts = _heuristic(open_rows, cust_stats)
        summary = 'Rule-based collection dates from customer payment history and due dates.'
        aging = _aging_buckets(open_rows)
        alerts = [f'{sum(1 for r in open_rows if r["days_overdue"] > 60)} invoice(s) over 60 days overdue']
        source = 'heuristic'

    result = {
        'invoice_forecasts': inv_forecasts,
        'summary': summary,
        'aging_summary': aging,
        'alerts': alerts,
        'source': source,
    }
    set_cached('receivables', cache_payload, result)
    return _assemble(open_rows, result)


def _heuristic(open_rows, cust_stats):
    out = {}
    for row in open_rows:
        cid = row.get('customer_id')
        extra = int(cust_stats.get(cid, 45))
        due = today()
        try:
            from datetime import date
            due = date.fromisoformat(row['due_date'])
        except ValueError:
            pass
        predicted = due + timedelta(days=max(0, extra - 30))
        overdue = row.get('days_overdue', 0)
        risk = 'high' if overdue > 60 else ('medium' if overdue > 30 else 'low')
        out[row['invoice_id']] = {
            'invoice_id': row['invoice_id'],
            'predicted_pay_date': predicted.isoformat(),
            'probability_pct': max(20, 90 - overdue),
            'risk': risk,
            'reason': f'Based on due date and customer average collection pattern.',
        }
    return out


def _aging_buckets(open_rows):
    buckets = {'current': 0.0, 'days_30': 0.0, 'days_60': 0.0, 'days_90_plus': 0.0}
    for r in open_rows:
        d = r.get('days_overdue', 0)
        amt = r['amount']
        if d <= 0:
            buckets['current'] += amt
        elif d <= 30:
            buckets['days_30'] += amt
        elif d <= 60:
            buckets['days_60'] += amt
        else:
            buckets['days_90_plus'] += amt
    return {k: round(v, 2) for k, v in buckets.items()}


def _normalize_aging(aging: dict) -> dict:
    """Map AI/heuristic aging keys to template-safe names."""
    if not aging:
        return {}
    return {
        'current': aging.get('current', 0),
        'days_30': aging.get('days_30', aging.get('30_days', 0)),
        'days_60': aging.get('days_60', aging.get('60_days', 0)),
        'days_90_plus': aging.get('days_90_plus', aging.get('90_plus', 0)),
    }


def _empty():
    from apps.inventory.utils import get_openai_api_key, is_ai_available
    return {
        'table_rows': [],
        'aging_summary': {},
        'summary': 'No open receivables to forecast.',
        'alerts': [],
        'has_data': False,
        'from_cache': False,
        'openai_configured': is_ai_available(),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }


def _assemble(open_rows, result):
    from apps.inventory.utils import get_openai_api_key, is_ai_available

    forecasts = result.get('invoice_forecasts') or {}
    if isinstance(forecasts, list):
        forecasts = {int(x['invoice_id']): x for x in forecasts if x.get('invoice_id')}

    table_rows = []
    for row in open_rows:
        fc = forecasts.get(row['invoice_id'], {})
        table_rows.append({
            'invoice_number': row['invoice_number'],
            'customer': row['customer'],
            'amount': row['amount'],
            'due_date': row['due_date'],
            'days_overdue': row['days_overdue'],
            'predicted_pay_date': fc.get('predicted_pay_date', '—'),
            'probability_pct': fc.get('probability_pct', '—'),
            'risk': fc.get('risk', 'medium'),
            'reason': fc.get('reason', ''),
        })

    aging = _normalize_aging(result.get('aging_summary') or _aging_buckets(open_rows))

    return {
        'table_rows': table_rows,
        'aging_summary': aging,
        'summary': result.get('summary', ''),
        'alerts': result.get('alerts', []),
        'open_count': len(open_rows),
        'open_total': round(sum(r['amount'] for r in open_rows), 2),
        'has_data': bool(open_rows),
        'from_cache': result.get('from_cache', False),
        'openai_configured': is_ai_available(),
        'disclaimer': 'AI-generated estimate — not financial advice.',
    }
