"""Views for AI Finance forecasting reports."""
from __future__ import annotations

import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View

from apps.core.audit import log_audit
from apps.core.utils import PermissionChecker

from .services.ai_finance.anomaly_detection import build_anomaly_detection_context
from .services.ai_finance.cash_flow_forecast import build_cash_flow_forecast_context
from .services.ai_finance.expense_forecast import build_expense_forecast_context
from .services.ai_finance.receivables_forecast import build_receivables_forecast_context
from .services.ai_finance.revenue_forecast import build_revenue_forecast_context
from .utils.ai_finance_export import export_ai_finance_pdf, export_ai_finance_xlsx

AI_FINANCE_REPORTS = {
    'cash-flow': {
        'title': 'Cash Flow Forecast',
        'slug': 'cash-flow',
        'template': 'reports/ai_finance/cash_flow.html',
        'builder': build_cash_flow_forecast_context,
        'needs_months': True,
    },
    'revenue': {
        'title': 'Revenue Forecast',
        'slug': 'revenue',
        'template': 'reports/ai_finance/revenue.html',
        'builder': build_revenue_forecast_context,
        'needs_months': True,
    },
    'expense': {
        'title': 'Expense Forecast',
        'slug': 'expense',
        'template': 'reports/ai_finance/expense.html',
        'builder': build_expense_forecast_context,
        'needs_months': True,
    },
    'receivables': {
        'title': 'Receivables Collection Forecast',
        'slug': 'receivables',
        'template': 'reports/ai_finance/receivables.html',
        'builder': build_receivables_forecast_context,
        'needs_months': False,
    },
    'anomaly': {
        'title': 'Anomaly Detection',
        'slug': 'anomaly',
        'template': 'reports/ai_finance/anomaly.html',
        'builder': build_anomaly_detection_context,
        'needs_months': False,
    },
}


def ai_finance_permission(user) -> bool:
    return (
        user.is_superuser
        or PermissionChecker.has_permission(user, 'finance', 'view')
        or PermissionChecker.has_permission(user, 'reports', 'view')
    )


def _parse_forecast_months(request) -> int:
    raw = (request.GET.get('months') or '6').strip()
    try:
        m = int(raw)
    except ValueError:
        m = 6
    return m if m in (3, 6) else 6


def _nav_context(active_slug: str) -> dict:
    return {
        'ai_finance_nav': [
            {'slug': k, 'title': v['title'], 'active': k == active_slug}
            for k, v in AI_FINANCE_REPORTS.items()
        ],
    }


class AiFinanceIndexView(LoginRequiredMixin, View):
    def get(self, request):
        if not ai_finance_permission(request.user):
            raise PermissionDenied
        from apps.inventory.utils import get_openai_api_key, is_ai_available
        return render(
            request,
            'reports/ai_finance/index.html',
            {
                'title': 'AI Finance',
                'openai_configured': is_ai_available(),
                'disclaimer': 'AI-generated estimate — not financial advice.',
                **_nav_context(''),
            },
        )


class AiFinanceReportView(LoginRequiredMixin, View):
    report_key: str = ''

    def get(self, request):
        if not ai_finance_permission(request.user):
            raise PermissionDenied
        meta = AI_FINANCE_REPORTS.get(self.report_key)
        if not meta:
            raise PermissionDenied

        force_refresh = request.GET.get('refresh') == '1'
        forecast_months = _parse_forecast_months(request)
        export_fmt = (request.GET.get('export') or '').strip().lower()

        kwargs = {'force_refresh': force_refresh}
        if meta['needs_months']:
            kwargs['forecast_months'] = forecast_months

        context = meta['builder'](**kwargs)
        context['title'] = meta['title']
        context['report_slug'] = meta['slug']
        context.update(_nav_context(meta['slug']))

        if export_fmt in ('pdf', 'xlsx') and context.get('has_data'):
            cols, rows = _export_table(meta['slug'], context)
            generated_by = request.user.get_full_name() or request.user.username
            log_audit(
                request.user,
                'export',
                'Report',
                changes={'event': f'ai_finance_{meta["slug"]}', 'export': export_fmt},
                request=request,
            )
            if export_fmt == 'pdf':
                data = export_ai_finance_pdf(
                    meta['title'], cols, rows, generated_by,
                    summary=context.get('summary', ''),
                )
                resp = HttpResponse(data, content_type='application/pdf')
                resp['Content-Disposition'] = f'attachment; filename="ai_finance_{meta["slug"]}.pdf"'
                return resp
            data = export_ai_finance_xlsx(
                meta['title'], cols, rows, generated_by,
                summary=context.get('summary', ''),
            )
            resp = HttpResponse(
                data,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            resp['Content-Disposition'] = f'attachment; filename="ai_finance_{meta["slug"]}.xlsx"'
            return resp

        context['chart_json'] = json.dumps(context.get('chart') or context.get('combined_chart') or {})
        return render(request, meta['template'], context)


def _export_table(slug: str, context: dict) -> tuple[list, list]:
    if slug == 'cash-flow':
        cols = [
            {'key': 'month', 'label': 'Month'},
            {'key': 'actual_inflow', 'label': 'Actual Inflow'},
            {'key': 'actual_outflow', 'label': 'Actual Outflow'},
            {'key': 'actual_balance', 'label': 'Actual Balance'},
            {'key': 'forecast_balance', 'label': 'Forecast Balance'},
            {'key': 'confidence', 'label': 'Confidence'},
        ]
        return cols, context.get('table_rows') or []
    if slug == 'revenue':
        cols = [
            {'key': 'month', 'label': 'Month'},
            {'key': 'actual', 'label': 'Actual Revenue'},
            {'key': 'forecast', 'label': 'Forecast Revenue'},
            {'key': 'confidence', 'label': 'Confidence'},
        ]
        return cols, context.get('table_rows') or []
    if slug == 'receivables':
        cols = [
            {'key': 'invoice_number', 'label': 'Invoice'},
            {'key': 'customer', 'label': 'Customer'},
            {'key': 'amount', 'label': 'Amount'},
            {'key': 'due_date', 'label': 'Due Date'},
            {'key': 'predicted_pay_date', 'label': 'Predicted Pay Date'},
            {'key': 'probability_pct', 'label': 'Probability %'},
            {'key': 'risk', 'label': 'Risk'},
        ]
        return cols, context.get('table_rows') or []
    if slug == 'anomaly':
        cols = [
            {'key': 'severity', 'label': 'Severity'},
            {'key': 'category', 'label': 'Category'},
            {'key': 'reference', 'label': 'Reference'},
            {'key': 'party', 'label': 'Party'},
            {'key': 'amount', 'label': 'Amount'},
            {'key': 'date', 'label': 'Date'},
            {'key': 'reason', 'label': 'Reason'},
        ]
        return cols, context.get('table_rows') or []
    if slug == 'expense':
        cols = [{'key': 'month', 'label': 'Month'}]
        for cat in context.get('categories') or []:
            cols.append({'key': cat, 'label': cat})
        cols.append({'key': 'total', 'label': 'Total'})
        return cols, context.get('table_rows') or []
    cols = [{'key': 'month', 'label': 'Month'}, {'key': 'total', 'label': 'Forecast Total'}]
    return cols, context.get('table_rows') or []


class AiFinanceApiView(LoginRequiredMixin, View):
    report_key: str = ''

    def get(self, request):
        if not ai_finance_permission(request.user):
            return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
        meta = AI_FINANCE_REPORTS.get(self.report_key)
        if not meta:
            return JsonResponse({'ok': False, 'error': 'Unknown report.'}, status=404)
        kwargs = {'force_refresh': request.GET.get('refresh') == '1'}
        if meta['needs_months']:
            kwargs['forecast_months'] = _parse_forecast_months(request)
        context = meta['builder'](**kwargs)
        return JsonResponse({'ok': True, 'report': meta['slug'], 'data': context})


class CashFlowForecastApiView(AiFinanceApiView):
    report_key = 'cash-flow'


class RevenueForecastApiView(AiFinanceApiView):
    report_key = 'revenue'


class ExpenseForecastApiView(AiFinanceApiView):
    report_key = 'expense'


class ReceivablesForecastApiView(AiFinanceApiView):
    report_key = 'receivables'


class AnomalyDetectionApiView(AiFinanceApiView):
    report_key = 'anomaly'


class CashFlowForecastView(AiFinanceReportView):
    report_key = 'cash-flow'


class RevenueForecastView(AiFinanceReportView):
    report_key = 'revenue'


class ExpenseForecastView(AiFinanceReportView):
    report_key = 'expense'


class ReceivablesForecastView(AiFinanceReportView):
    report_key = 'receivables'


class AnomalyDetectionView(AiFinanceReportView):
    report_key = 'anomaly'
