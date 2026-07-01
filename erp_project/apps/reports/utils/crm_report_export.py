"""Export helpers for CRM reports (Lead, DVR, Salesman performance)."""
from __future__ import annotations

import csv
from io import StringIO

from apps.inventory.reports.export_helpers import export_table_xlsx


def export_table_csv(report_payload: dict) -> bytes:
    buf = StringIO()
    writer = csv.writer(buf)
    cols = report_payload.get('columns', [])
    writer.writerow([c['label'] for c in cols])
    for row in report_payload.get('rows', []):
        writer.writerow([row.get(c['key'], '') for c in cols])
    return buf.getvalue().encode('utf-8-sig')


def _lead_report_columns() -> list[dict]:
    return [
        {'key': 'customer_number', 'label': 'Lead #'},
        {'key': 'name', 'label': 'Name'},
        {'key': 'company', 'label': 'Company'},
        {'key': 'phone', 'label': 'Phone'},
        {'key': 'email', 'label': 'Email'},
        {'key': 'salesperson_name', 'label': 'Salesperson'},
        {'key': 'source_label', 'label': 'Source'},
        {'key': 'created_at', 'label': 'Created'},
        {'key': 'status', 'label': 'Status'},
        {'key': 'stage_name', 'label': 'Stage'},
        {'key': 'latest_estimate_value', 'label': 'Estimate (AED)'},
    ]


def build_lead_report_export(context: dict) -> dict:
    rows = []
    for row in context.get('lead_details') or []:
        rows.append({
            'customer_number': row.get('customer_number', ''),
            'name': row.get('name', ''),
            'company': row.get('company', ''),
            'phone': row.get('phone', ''),
            'email': row.get('email', ''),
            'salesperson_name': row.get('salesperson_name', ''),
            'source_label': row.get('source_label', ''),
            'created_at': row['created_at'].strftime('%Y-%m-%d') if row.get('created_at') else '',
            'status': row.get('status', ''),
            'stage_name': row.get('stage_name', ''),
            'latest_estimate_value': float(row.get('latest_estimate_value') or 0),
        })
    return {
        'title': 'Lead Report',
        'columns': _lead_report_columns(),
        'rows': rows,
    }


def build_dvr_export(context: dict) -> dict:
    return {
        'title': 'Daily Visit Record',
        'columns': [
            {'key': 'visit_date', 'label': 'Date'},
            {'key': 'lead_label', 'label': 'Lead'},
            {'key': 'lead_number', 'label': 'Lead #'},
            {'key': 'salesman_name', 'label': 'Salesman'},
            {'key': 'location', 'label': 'Location'},
            {'key': 'outcome', 'label': 'Outcome'},
            {'key': 'notes', 'label': 'Notes'},
        ],
        'rows': [
            {
                **row,
                'visit_date': row['visit_date'].strftime('%Y-%m-%d') if row.get('visit_date') else '',
            }
            for row in (context.get('visit_rows') or [])
        ],
    }


def build_salesman_performance_export(context: dict) -> dict:
    return {
        'title': 'Salesman Lead Performance',
        'columns': [
            {'key': 'salesperson_name', 'label': 'Salesperson'},
            {'key': 'leads_created', 'label': 'Leads Created'},
            {'key': 'open_leads', 'label': 'Open Leads'},
            {'key': 'won', 'label': 'Won'},
            {'key': 'lost', 'label': 'Lost'},
            {'key': 'pipeline_value', 'label': 'Pipeline Value (AED)'},
            {'key': 'conversion_rate', 'label': 'Conversion Rate %'},
        ],
        'rows': [
            {
                **row,
                'pipeline_value': float(row.get('pipeline_value') or 0),
            }
            for row in (context.get('performance_rows') or [])
        ],
    }


def export_report_xlsx(context: dict, *, report_kind: str, generated_by: str) -> bytes:
    builders = {
        'lead': build_lead_report_export,
        'dvr': build_dvr_export,
        'salesman': build_salesman_performance_export,
    }
    payload = builders[report_kind](context)
    return export_table_xlsx(payload, generated_by)


def export_report_csv(context: dict, *, report_kind: str) -> bytes:
    builders = {
        'lead': build_lead_report_export,
        'dvr': build_dvr_export,
        'salesman': build_salesman_performance_export,
    }
    payload = builders[report_kind](context)
    return export_table_csv(payload)
