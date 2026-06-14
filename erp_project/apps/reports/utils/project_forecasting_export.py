"""Export helpers for Project Forecasting report."""
from __future__ import annotations

from apps.inventory.reports.export_helpers import export_table_pdf, export_table_xlsx


def build_export_payload(context: dict) -> dict:
    columns = [
        {'key': 'code', 'label': 'Code'},
        {'key': 'project_name', 'label': 'Project'},
        {'key': 'customer', 'label': 'Customer'},
        {'key': 'status_label', 'label': 'Status'},
        {'key': 'risk_level', 'label': 'Risk'},
        {'key': 'completion_forecast', 'label': 'Completion Forecast'},
        {'key': 'cost_forecast_display', 'label': 'Cost Forecast'},
        {'key': 'margin_forecast_display', 'label': 'Margin Forecast'},
        {'key': 'top_risk_reason', 'label': 'Top Risk Reason'},
        {'key': 'ai_action', 'label': 'AI Action'},
    ]
    rows = []
    for r in context.get('rows') or []:
        rows.append({col['key']: r.get(col['key'], '') for col in columns})

    return {
        'title': 'Project Forecasting Report',
        'subtitle': (
            f"{context.get('start_date')} – {context.get('end_date')} "
            f"({context.get('project_count', 0)} projects)"
        ),
        'columns': columns,
        'rows': rows,
        'executive_brief': context.get('executive_brief') or '',
        'summary': context.get('summary') or {},
        'anomalies': context.get('anomalies') or [],
    }


def export_forecast_xlsx(context: dict, generated_by: str) -> bytes:
    payload = build_export_payload(context)
    return export_table_xlsx(payload, generated_by)


def export_forecast_pdf(context: dict, generated_by: str) -> bytes:
    payload = build_export_payload(context)
    return export_table_pdf(payload, generated_by)
