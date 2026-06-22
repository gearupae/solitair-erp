"""Natural-language queries over inventory data (rule-based router)."""
from __future__ import annotations

import re
from decimal import Decimal

from apps.inventory.reports._common import active_product_items
from apps.inventory.services.inventory_compliance_watchdog import load_compliance_report
from apps.inventory.services.warehouse_balancing import build_transfer_suggestions_report
from apps.inventory.services.ai_forecast import build_ai_forecast_report


def answer_inventory_question(question: str, *, warehouse_id=None, category_id=None) -> dict:
    q = (question or '').strip().lower()
    if not q:
        return {'ok': False, 'error': 'Enter a question.'}

    if re.search(r'expir', q) and re.search(r'\d+\s*day', q):
        days = 30
        m = re.search(r'(\d+)\s*day', q)
        if m:
            days = int(m.group(1))
        from datetime import date, timedelta

        today = date.today()
        limit = today + timedelta(days=days)
        rows = []
        for item in active_product_items():
            exp = item.warranty_expiry
            if not exp or exp > limit or exp < today:
                continue
            rows.append(
                {
                    'item': item.name,
                    'sku': item.item_code,
                    'expiry': exp.isoformat(),
                    'days_until': (exp - today).days,
                }
            )
        return {
            'ok': True,
            'answer_type': 'table',
            'title': f'Items expiring within {days} days',
            'rows': rows,
            'summary': f'Found {len(rows)} item(s).',
        }

    if 'dead stock' in q or 'deadstock' in q:
        payload = build_ai_forecast_report(
            warehouse_id=warehouse_id,
            category_id=category_id,
            status_filter='Dead',
        )
        by_cat: dict[str, Decimal] = {}
        for row in payload.get('all_rows', []):
            if row.get('status') != 'Dead':
                continue
            # category name not in row — aggregate value only
            val = Decimal(str(row.get('dead_value') or 0))
            by_cat['All'] = by_cat.get('All', Decimal('0')) + val
        total = sum(by_cat.values())
        return {
            'ok': True,
            'answer_type': 'text',
            'summary': f'Dead stock value (180+ days no movement): AED {total:,.2f} across {payload["summary"]["total_items"]} items in scope.',
            'rows': [{'category': k, 'value_aed': float(v)} for k, v in by_cat.items()],
        }

    if 'short' in q and ('glove' in q or 'warehouse' in q):
        search = 'glove' if 'glove' in q else None
        payload = build_ai_forecast_report(
            warehouse_id=warehouse_id,
            category_id=category_id,
            search=search,
            stockout_risk_filter='High',
        )
        rows = [
            {
                'item': r['item_name'],
                'sku': r['sku'],
                'stock': r['current_stock'],
                'risk': r['stockout_risk'],
            }
            for r in payload.get('rows', [])[:20]
        ]
        return {
            'ok': True,
            'answer_type': 'table',
            'title': 'Short / high stockout risk items',
            'rows': rows,
            'summary': f'{len(rows)} item(s) at high stockout risk.',
        }

    if 'transfer' in q or 'balance' in q:
        payload = build_transfer_suggestions_report(
            warehouse_id=warehouse_id,
            category_id=category_id,
        )
        return {
            'ok': True,
            'answer_type': 'table',
            'title': payload['title'],
            'rows': payload['rows'][:15],
            'summary': f"{payload['summary']['suggestion_count']} transfer suggestion(s).",
        }

    if 'compliance' in q or 'negative stock' in q:
        payload = load_compliance_report()
        return {
            'ok': True,
            'answer_type': 'table',
            'title': 'Open compliance flags',
            'rows': payload.get('rows', [])[:15],
            'summary': payload.get('summary', {}).get('flag_count', 0),
        }

    return {
        'ok': True,
        'answer_type': 'text',
        'summary': (
            'Try: "items expiring in 30 days", "dead stock value by category", '
            '"which warehouse is short on gloves", or "transfer suggestions".'
        ),
        'rows': [],
    }
