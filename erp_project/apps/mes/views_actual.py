"""Manufacturing → Actual — camera object counting."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from apps.inventory.utils import is_ai_available

from .models import ActualCountExampleImage, ActualCountSetting
from .services.actual_count import get_daily_log_rows, get_example_images_for_ui, reset_capture_baseline
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
            defaults={'item_names': [], 'last_capture_counts': {}, 'presence_state': {}},
        )
        ctx['setting'] = setting
        ctx['item_names'] = setting.item_names or []
        ctx['capture_interval'] = setting.capture_interval_seconds if setting.capture_interval_seconds is not None else 0
        ctx['example_images'] = get_example_images_for_ui(company, ctx['item_names'])
        ctx['items_with_examples'] = [
            {'name': name, 'examples': ctx['example_images'].get(name, [])}
            for name in ctx['item_names']
        ]
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

        if action == 'delete_example':
            try:
                pk = int(request.POST.get('example_id') or 0)
            except (TypeError, ValueError):
                pk = 0
            deleted, _ = ActualCountExampleImage.objects.filter(
                company=company,
                pk=pk,
            ).delete()
            if deleted:
                messages.success(request, 'Example photo removed.')
            else:
                messages.warning(request, 'Example photo not found.')
            return redirect('mes:actual')

        if action == 'upload_example':
            item_name = (request.POST.get('item_name') or '').strip()
            upload = request.FILES.get('example_image')
            if not item_name:
                messages.error(request, 'Select an item name for the example photo.')
                return redirect('mes:actual')
            if not upload:
                messages.error(request, 'Choose a photo to upload.')
                return redirect('mes:actual')

            setting = ActualCountSetting.objects.filter(company=company).first()
            configured = [_n.strip() for _n in (setting.item_names if setting else []) if _n.strip()]
            if item_name not in configured:
                messages.error(request, f'"{item_name}" is not in your saved item list.')
                return redirect('mes:actual')

            ActualCountExampleImage.objects.create(
                company=company,
                item_name=item_name,
                image=upload,
                created_by=request.user,
            )
            messages.success(request, f'Example photo added for "{item_name}".')
            return redirect('mes:actual')

        raw_items = request.POST.get('item_names', '')
        names = []
        for line in raw_items.replace(',', '\n').splitlines():
            name = line.strip()
            if name and name not in names:
                names.append(name)

        setting, _ = ActualCountSetting.objects.get_or_create(
            company=company,
            defaults={'item_names': [], 'last_capture_counts': {}, 'presence_state': {}},
        )
        setting.item_names = names
        try:
            interval = int(request.POST.get('capture_interval') or setting.capture_interval_seconds or 0)
            setting.capture_interval_seconds = max(0, min(interval, 30))
        except (TypeError, ValueError):
            pass
        setting.save(update_fields=['item_names', 'capture_interval_seconds', 'updated_at'])
        messages.success(request, f'Saved {len(names)} item(s) to count.')
        return redirect('mes:actual')
