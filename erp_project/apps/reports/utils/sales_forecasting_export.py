"""Export helpers for Sales Forecasting report."""
from __future__ import annotations

from apps.inventory.reports.export_helpers import export_table_pdf, export_table_xlsx


def build_export_payload(context: dict) -> dict:
    columns = [
        {'key': 'estimate_number', 'label': 'Estimate'},
        {'key': 'customer', 'label': 'Customer'},
        {'key': 'salesperson', 'label': 'Salesperson'},
        {'key': 'status_label', 'label': 'Status'},
        {'key': 'total_value_display', 'label': 'Total Value'},
        {'key': 'estimated_margin_display', 'label': 'Est. Margin %'},
        {'key': 'predicted_outcome', 'label': 'Predicted Outcome'},
        {'key': 'predicted_margin_display', 'label': 'Predicted Margin %'},
        {'key': 'risk_flag', 'label': 'Risk'},
        {'key': 'top_insight', 'label': 'Top Insight'},
        {'key': 'ai_action', 'label': 'AI Action'},
    ]
    return {
        'title': 'Sales Forecasting Report',
        'subtitle': (
            f"{context.get('start_date')} – {context.get('end_date')} "
            f"({context.get('estimate_count', 0)} estimates)"
        ),
        'columns': columns,
        'rows': [
            {col['key']: r.get(col['key'], '') for col in columns}
            for r in (context.get('rows') or [])
        ],
        'executive_brief': context.get('executive_brief') or '',
        'summary': context.get('summary') or {},
    }


def export_sales_forecast_xlsx(context: dict, generated_by: str) -> bytes:
    return export_table_xlsx(build_export_payload(context), generated_by)


def export_sales_forecast_pdf(context: dict, generated_by: str) -> bytes:
    return export_table_pdf(build_export_payload(context), generated_by)
