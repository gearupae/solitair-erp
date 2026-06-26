"""Anomaly detection on recent finance transactions."""
from __future__ import annotations

from statistics import mean, stdev

from .ai_client import OpenAINotConfigured, call_openai_json, get_cached, set_cached
from .utils import recent_transactions_for_anomaly

SYSTEM = """You are a finance anomaly detector for a UAE ERP.
Flag unusual transactions: spikes, duplicates, round-number outliers, vendor concentration.
Respond ONLY in JSON:
{"anomalies":[{"severity":"high|medium|low","category":"spike|duplicate|unusual_amount|vendor|general",
"reference":"...","party":"...","amount":number,"date":"YYYY-MM-DD","reason":"one sentence"}],
 "summary":"one line"}
Max 15 anomalies. No markdown."""


def build_anomaly_detection_context(*, force_refresh: bool = False) -> dict:
    transactions = recent_transactions_for_anomaly(90)
    cache_payload = {'report': 'anomaly', 'count': len(transactions)}

    if not force_refresh:
        cached = get_cached('anomaly', cache_payload)
        if cached:
            return _assemble(transactions, cached)

    if len(transactions) < 5:
        return _empty()

    try:
        ai = call_openai_json(
            system=SYSTEM,
            user_payload={'transactions': transactions[:120]},
        )
        anomalies = ai.get('anomalies') or []
        summary = str(ai.get('summary', '')).strip()
        source = 'openai'
    except (OpenAINotConfigured, Exception):
        anomalies = _heuristic(transactions)
        summary = f'Rule-based scan found {len(anomalies)} potential anomaly(ies) in recent transactions.'
        source = 'heuristic'

    result = {'anomalies': anomalies, 'summary': summary, 'source': source}
    set_cached('anomaly', cache_payload, result)
    return _assemble(transactions, result)


def _heuristic(transactions: list) -> list:
    amounts = [t['amount'] for t in transactions if t.get('amount')]
    if len(amounts) < 3:
        return []
    avg = mean(amounts)
    try:
        sd = stdev(amounts)
    except Exception:
        sd = avg * 0.5
    threshold = avg + max(sd * 2, avg * 0.5)
    flags = []
    seen = {}
    for t in transactions:
        ref = t.get('reference', '')
        key = (ref, t.get('party'), t.get('amount'))
        if key in seen and ref:
            flags.append({
                'severity': 'medium',
                'category': 'duplicate',
                'reference': ref,
                'party': t.get('party', ''),
                'amount': t['amount'],
                'date': t.get('date', ''),
                'reason': 'Similar reference, party, and amount seen more than once recently.',
            })
        seen[key] = True
        if t['amount'] >= threshold and t['amount'] >= 5000:
            flags.append({
                'severity': 'high' if t['amount'] >= threshold * 1.5 else 'medium',
                'category': 'spike',
                'reference': ref,
                'party': t.get('party', ''),
                'amount': t['amount'],
                'date': t.get('date', ''),
                'reason': f'Amount AED {t["amount"]:,.2f} is well above recent average AED {avg:,.2f}.',
            })
    return flags[:15]


def _empty():
    from apps.inventory.utils import get_openai_api_key, is_ai_available
    return {
        'table_rows': [],
        'summary': 'Not enough recent transaction data for anomaly detection.',
        'has_data': False,
        'from_cache': False,
        'openai_configured': is_ai_available(),
        'disclaimer': 'AI-generated estimate — not financial advice.',
        'transaction_count': 0,
    }


def _assemble(transactions, result):
    from apps.inventory.utils import get_openai_api_key, is_ai_available

    rows = []
    for a in result.get('anomalies') or []:
        sev = str(a.get('severity', 'medium')).lower()
        if sev not in ('high', 'medium', 'low'):
            sev = 'medium'
        rows.append({
            'severity': sev,
            'category': a.get('category', 'general'),
            'reference': a.get('reference', ''),
            'party': a.get('party', ''),
            'amount': a.get('amount', ''),
            'date': a.get('date', ''),
            'reason': a.get('reason', ''),
        })

    return {
        'table_rows': rows,
        'summary': result.get('summary', ''),
        'has_data': bool(transactions),
        'from_cache': result.get('from_cache', False),
        'openai_configured': is_ai_available(),
        'disclaimer': 'AI-generated estimate — not financial advice.',
        'transaction_count': len(transactions),
    }
