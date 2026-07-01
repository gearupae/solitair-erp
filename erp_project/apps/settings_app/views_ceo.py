"""CEO Dashboard views."""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from apps.settings_app.ceo_access import user_can_access_ceo_dashboard


class CeoAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return user_can_access_ceo_dashboard(self.request.user)

    def handle_no_permission(self):
        return redirect('dashboard')


def _ceo_force(request) -> bool:
    return (request.GET.get('force') or '').lower() in ('1', 'true', 'yes')


class CeoDashboardView(CeoAccessMixin, TemplateView):
    """Fast initial render — live metrics only; AI sections load via API after paint."""

    template_name = 'settings/ceo_dashboard.html'

    def get_context_data(self, **kwargs):
        from apps.inventory.utils import is_ai_available
        from apps.settings_app.services.ceo_metrics import build_ceo_metrics
        from apps.settings_app.services.ceo_executive_reports import (
            build_executive_report,
            parse_ceo_filters,
        )

        context = super().get_context_data(**kwargs)
        filters = parse_ceo_filters(self.request)
        data = build_ceo_metrics()
        exec_report = build_executive_report(self.request.user, filters)

        context.update({
            'title': 'CEO',
            'openai_configured': is_ai_available(),
            'rule_alerts': data['rule_alerts'],
            'money_cards': data['money_cards'],
            'pipeline': data['pipeline'],
            'yesterday_deltas': data['yesterday_deltas'],
            'currency': data['metrics'].get('currency', 'AED'),
            'charts_json': json.dumps(data['charts']),
            'exec_report': exec_report,
            'ceo_filters': filters,
            'briefing_url': reverse('settings:ceo_api_briefing'),
            'alerts_url': reverse('settings:ceo_api_alerts'),
            'cash_forecast_url': reverse('settings:ceo_api_cash_forecast'),
            'predictive_cash_url': reverse('settings:ceo_api_predictive_cash'),
            'collections_url': reverse('settings:ceo_api_collections'),
            'yesterday_url': reverse('settings:ceo_api_yesterday'),
            'operations_url': reverse('settings:ceo_api_operations'),
            'projects_overview': data['projects_overview'],
            'hr_overview': data['hr_overview'],
        })
        return context


def _metrics_payload():
    from apps.settings_app.services.ceo_metrics import build_ceo_metrics

    return build_ceo_metrics()


@login_required
def ceo_api_briefing(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.settings_app.services.ceo_ai import generate_daily_briefing

    data = _metrics_payload()
    result = generate_daily_briefing(data['metrics_snapshot'], force=_ceo_force(request))
    return JsonResponse({
        'ok': True,
        'text': result.get('text', ''),
        'from_cache': result.get('from_cache', False),
        'ai_used': result.get('ai_used', False),
    })


@login_required
def ceo_api_alerts(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.settings_app.services.ceo_ai import generate_risk_alerts

    data = _metrics_payload()
    result = generate_risk_alerts(
        data['metrics_snapshot'],
        data['rule_alerts'],
        force=_ceo_force(request),
    )
    return JsonResponse({
        'ok': True,
        'alerts': result.get('alerts', []),
        'from_cache': result.get('from_cache', False),
        'ai_used': result.get('ai_used', False),
    })


@login_required
def ceo_api_cash_forecast(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.reports.services.ai_finance.cash_flow_forecast import build_cash_flow_forecast_context

    ctx = build_cash_flow_forecast_context(forecast_months=3, force_refresh=_ceo_force(request))
    cf_chart = ctx.get('combined_chart') or {}
    labels = cf_chart.get('labels') or []
    values = cf_chart.get('forecast_balance') or cf_chart.get('actual_balance') or []
    return JsonResponse({
        'ok': True,
        'labels': labels[-8:] if labels else [],
        'values': values[-8:] if values else [],
        'summary': ctx.get('summary', ''),
        'from_cache': ctx.get('from_cache', False),
    })


@login_required
def ceo_api_predictive_cash(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.settings_app.services.ceo_ai import generate_predictive_cash_alert

    data = _metrics_payload()
    result = generate_predictive_cash_alert(data['metrics_snapshot'], force=_ceo_force(request))
    return JsonResponse({'ok': True, **result})


@login_required
def ceo_api_collections(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.settings_app.services.ceo_ai import generate_ranked_collections

    data = _metrics_payload()
    candidates = data['metrics_snapshot'].get('collection_candidates') or []
    result = generate_ranked_collections(
        data['metrics_snapshot'],
        candidates,
        force=_ceo_force(request),
    )
    return JsonResponse({'ok': True, **result})


@login_required
def ceo_api_yesterday(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    data = _metrics_payload()
    return JsonResponse({
        'ok': True,
        'deltas': data.get('yesterday_deltas') or [],
        'as_of': data['metrics'].get('as_of'),
    })


@login_required
def ceo_api_operations(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.settings_app.services.ceo_ai import generate_operations_summaries

    data = _metrics_payload()
    result = generate_operations_summaries(
        data['projects_overview'],
        data['hr_overview'],
        force=_ceo_force(request),
    )
    return JsonResponse({'ok': True, **result})
