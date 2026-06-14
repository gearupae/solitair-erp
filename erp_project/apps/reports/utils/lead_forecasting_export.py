"""Export helpers for Lead Forecasting report."""
from __future__ import annotations

from apps.inventory.reports.export_helpers import export_table_pdf, export_table_xlsx


def build_export_payload(context: dict) -> dict:
    sp_columns = [
        {'key': 'label', 'label': 'Salesperson'},
        {'key': 'active_leads', 'label': 'Active Leads'},
        {'key': 'predicted_conversions', 'label': 'Predicted Conversions'},
        {'key': 'conversion_rate_display', 'label': 'Conversion Rate (12 mo)'},
        {'key': 'avg_deal_display', 'label': 'Avg Deal Size'},
        {'key': 'trend_display', 'label': 'Trend'},
        {'key': 'best_source', 'label': 'Best Source'},
        {'key': 'ai_verdict', 'label': 'AI Verdict'},
    ]
    lead_columns = [
        {'key': 'lead_name', 'label': 'Lead'},
        {'key': 'salesperson', 'label': 'Salesperson'},
        {'key': 'stage_label', 'label': 'Stage'},
        {'key': 'days_in_stage', 'label': 'Days in Stage'},
        {'key': 'win_probability', 'label': 'Win Probability %'},
        {'key': 'predicted_outcome', 'label': 'Predicted Outcome'},
        {'key': 'predicted_close_date', 'label': 'Predicted Close Date'},
        {'key': 'top_factor', 'label': 'Top Factor'},
        {'key': 'ai_action', 'label': 'AI Action'},
    ]

    return {
        'title': 'Lead Forecasting Report',
        'subtitle': (
            f"{context.get('start_date')} – {context.get('end_date')} "
            f"({context.get('lead_count', 0)} leads)"
        ),
        'columns': lead_columns,
        'rows': [
            {col['key']: r.get(col['key'], '') for col in lead_columns}
            for r in (context.get('lead_rows') or [])
        ],
        'executive_brief': context.get('executive_brief') or '',
        'summary': context.get('summary') or {},
        'sp_rows': context.get('sp_rows') or [],
        'sp_columns': sp_columns,
        'next_month': context.get('next_month') or {},
        'anomalies': context.get('anomalies') or [],
    }


def export_lead_forecast_xlsx(context: dict, generated_by: str) -> bytes:
    payload = build_export_payload(context)
    return export_table_xlsx(payload, generated_by)


def export_lead_forecast_pdf(context: dict, generated_by: str) -> bytes:
    payload = build_export_payload(context)
    return export_table_pdf(payload, generated_by)
