"""Manufacturing → Actual — camera object counting."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from apps.inventory.utils import is_ai_available

from .models import ActualCountSetting
from .services.actual_count import get_daily_log_rows, reset_capture_baseline
from .views import MesAccessMixin, MesCompanyMixin


class ActualCountView(MesAccessMixin, MesCompanyMixin, TemplateView):
    template_name = 'mes/actual_count.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        ctx['title'] = 'Actual — Camera Count'
        ctx['company'] = company
        ctx['ai_available'] = is_ai_available()

        setting, _ = ActualCountSetting.objects.get_or_create(
            company=company,
            defaults={'item_names': [], 'last_capture_counts': {}},
        )
        ctx['setting'] = setting
        ctx['item_names'] = setting.item_names or []
        ctx['capture_interval'] = setting.capture_interval_seconds or 2
        ctx['daily_logs'] = get_daily_log_rows(company, days=30)

        today = timezone.localdate()
        ctx['today_totals'] = {
            row['item_name']: row['count']
            for row in ctx['daily_logs']
            if row['log_date'] == today.isoformat()
        }
        ctx['today_grand_total'] = sum(ctx['today_totals'].values())

        return ctx

    def post(self, request, *args, **kwargs):
        company = self.get_company()
        action = (request.POST.get('action') or 'save_items').strip()

        if action == 'reset_baseline':
            reset_capture_baseline(company)
            messages.success(request, 'Capture baseline reset.')
            return redirect('mes:actual')

        raw_items = request.POST.get('item_names', '')
        names = []
        for line in raw_items.replace(',', '\n').splitlines():
            name = line.strip()
            if name and name not in names:
                names.append(name)

        setting, _ = ActualCountSetting.objects.get_or_create(
            company=company,
            defaults={'item_names': [], 'last_capture_counts': {}},
        )
        setting.item_names = names
        try:
            interval = int(request.POST.get('capture_interval') or setting.capture_interval_seconds or 2)
            setting.capture_interval_seconds = max(1, min(interval, 30))
        except (TypeError, ValueError):
            pass
        setting.save(update_fields=['item_names', 'capture_interval_seconds', 'updated_at'])
        messages.success(request, f'Saved {len(names)} item(s) to count.')
        return redirect('mes:actual')
