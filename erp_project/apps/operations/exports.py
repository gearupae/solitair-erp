"""Export completed operations schedules to Excel / PDF."""
from __future__ import annotations

from django.http import HttpResponse

from apps.inventory.reports.export_helpers import export_table_pdf, export_table_xlsx

from .dashboard import completed_export_payload, completed_schedules_queryset, parse_dashboard_filters


def export_completed_schedules(request, export_fmt: str) -> HttpResponse:
    filters = parse_dashboard_filters(request.GET)
    schedules = list(completed_schedules_queryset(filters))
    title = 'Completed Operations Schedules'
    if filters.get('date_from') and filters.get('date_to'):
        title += f" ({filters['date_from']:%d %b %Y} – {filters['date_to']:%d %b %Y})"

    payload = completed_export_payload(schedules, title=title)
    generated_by = request.user.get_full_name() or request.user.username

    if export_fmt == 'xlsx':
        data = export_table_xlsx(payload, generated_by)
        resp = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = 'attachment; filename="operations_completed.xlsx"'
        return resp

    data = export_table_pdf(payload, generated_by)
    resp = HttpResponse(data, content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="operations_completed.pdf"'
    return resp
