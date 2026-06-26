"""Safe read-only text-to-SQL for CEO Ask the Business."""
from __future__ import annotations

import logging
import re

from django.db import connection

logger = logging.getLogger(__name__)

MAX_ROWS = 50
FORBIDDEN = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|GRANT|REVOKE)\b',
    re.IGNORECASE,
)

SCHEMA_HINT = """
SQLite ERP tables (read-only SELECT only):
- sales_invoice: id, invoice_number, invoice_date, due_date, status, total_amount, paid_amount, customer_id, is_active
- sales_estimate: id, estimate_number, date, status, total_amount, customer_id, valid_until, is_active
- crm_customer: id, name, customer_type, status, lead_kanban_stage_id, is_active, created_at
- finance_bankaccount: id, name, current_balance, currency, is_active
- finance_payment: id, payment_date, payment_type, party_type, amount, status, is_active
- purchase_vendorbill: id, bill_number, bill_date, due_date, status, total_amount, paid_amount, vendor_id, is_active
- purchase_vendor: id, name, is_active
- projects_project: id, project_code, name, status, budget, contract_value, total_revenue, total_expenses, is_active
- hr_employee: id, employee_code, first_name, last_name, status, visa_expiry, is_active
- contracts_contract: id, contract_number, name, start_date, end_date, contract_value, status, is_active
Join customers: sales_invoice.customer_id = crm_customer.id
Use is_active = 1 for active records. Amounts in AED unless stated.
"""


def _validate_sql(sql: str) -> str | None:
    cleaned = (sql or '').strip().rstrip(';')
    if not cleaned:
        return None
    if FORBIDDEN.search(cleaned):
        return None
    upper = cleaned.upper()
    if not upper.startswith('SELECT'):
        return None
    if ';' in cleaned:
        return None
    return cleaned


def _generate_sql(question: str) -> str | None:
    from django.conf import settings
    from apps.core.openai_gateway import call_openai_json, resolve_openai_model

    model = resolve_openai_model(getattr(settings, 'OPENAI_CEO_MODEL', '') or 'gpt-5.4-mini')

    system = f"""You convert CEO business questions into ONE SQLite SELECT query.
{SCHEMA_HINT}
Rules: SELECT only. No semicolons. Limit {MAX_ROWS} rows. Use readable column aliases.
Respond JSON: {{"sql": "SELECT ..."}}"""

    try:
        data = call_openai_json(
            system=system,
            user_payload={'question': question},
            temperature=0,
            feature='ceo_text_to_sql',
            model=model,
            reasoning_effort='none',
        )
        if isinstance(data, dict):
            return _validate_sql(data.get('sql', ''))
    except Exception as exc:
        logger.warning('text-to-sql generation failed: %s', exc)
    return None


def run_ceo_query(question: str) -> dict:
    sql = _generate_sql(question)
    if not sql:
        return {'ok': False, 'error': 'Could not build a safe query for that question. Try rephrasing.'}

    if 'LIMIT' not in sql.upper():
        sql = f'{sql} LIMIT {MAX_ROWS}'

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchmany(MAX_ROWS)
    except Exception as exc:
        logger.warning('CEO SQL execution failed: %s — %s', sql, exc)
        return {'ok': False, 'error': f'Query failed: {exc}'}

    rows = []
    for row in raw_rows:
        rows.append([str(v) if v is not None else '' for v in row])

    return {
        'ok': True,
        'sql': sql,
        'columns': columns,
        'rows': rows,
        'row_count': len(rows),
    }
