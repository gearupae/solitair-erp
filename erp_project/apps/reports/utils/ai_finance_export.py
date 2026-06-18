"""Export helpers for AI Finance reports."""
from __future__ import annotations

from apps.inventory.reports.export_helpers import export_table_pdf, export_table_xlsx


def export_ai_finance_xlsx(title: str, columns: list, rows: list, generated_by: str, *, subtitle: str = '', summary: str = '') -> bytes:
    payload = {
        'title': title,
        'subtitle': subtitle,
        'columns': columns,
        'rows': rows,
        'executive_brief': summary,
    }
    return export_table_xlsx(payload, generated_by)


def export_ai_finance_pdf(title: str, columns: list, rows: list, generated_by: str, *, subtitle: str = '', summary: str = '') -> bytes:
    payload = {
        'title': title,
        'subtitle': subtitle,
        'columns': columns,
        'rows': rows,
        'executive_brief': summary,
    }
    return export_table_pdf(payload, generated_by)
