"""CEO Dashboard views."""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.settings_app.ceo_access import user_can_access_ceo_dashboard


class CeoAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return user_can_access_ceo_dashboard(self.request.user)

    def handle_no_permission(self):
        return redirect('dashboard')


class CeoDashboardView(CeoAccessMixin, TemplateView):
    template_name = 'settings/ceo_dashboard.html'

    def get_context_data(self, **kwargs):
        from apps.inventory.utils import is_ai_available
        from apps.reports.services.ai_finance.cash_flow_forecast import build_cash_flow_forecast_context
        from apps.settings_app.services.ceo_ai import (
            generate_daily_briefing,
            generate_risk_alerts,
        )
        from apps.settings_app.services.ceo_metrics import build_ceo_metrics

        context = super().get_context_data(**kwargs)
        force = (self.request.GET.get('refresh') or '').lower() in ('1', 'true', 'yes')
        data = build_ceo_metrics()
        metrics_snapshot = data['metrics_snapshot']

        briefing = generate_daily_briefing(metrics_snapshot, force=force)
        risks = generate_risk_alerts(metrics_snapshot, data['rule_alerts'], force=force)

        cash_forecast = build_cash_flow_forecast_context(forecast_months=3, force_refresh=force)
        cf_chart = cash_forecast.get('combined_chart') or {}
        forecast_labels = cf_chart.get('labels') or []
        forecast_balance = cf_chart.get('forecast_balance') or cf_chart.get('actual_balance') or []

        context.update({
            'title': 'CEO',
            'openai_configured': is_ai_available(),
            'briefing': briefing.get('text', ''),
            'briefing_cached': briefing.get('from_cache', False),
            'alerts': risks.get('alerts', []),
            'money_cards': data['money_cards'],
            'pipeline': data['pipeline'],
            'currency': data['metrics'].get('currency', 'AED'),
            'charts_json': json.dumps({
                **data['charts'],
                'cash_forecast': {
                    'labels': forecast_labels[-6:] if forecast_labels else [],
                    'values': forecast_balance[-6:] if forecast_balance else [],
                },
            }),
            'ask_url': reverse('settings:ceo_ask'),
        })
        return context


@login_required
@require_POST
def ceo_ask_business(request):
    if not user_can_access_ceo_dashboard(request.user):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    question = (request.POST.get('question') or '').strip()
    from apps.settings_app.services.ceo_ai import answer_business_question

    result = answer_business_question(question)
    status = 200 if result.get('ok') else 400
    return JsonResponse(result, status=status)
