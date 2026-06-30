"""Accounting Dashboard view — read-only."""
from django.views.generic import TemplateView

from apps.core.mixins import PermissionRequiredMixin


class AccountingDashboardView(PermissionRequiredMixin, TemplateView):
    template_name = 'finance/accounting_dashboard.html'
    module_name = 'finance'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        from .accounting_dashboard import build_accounting_dashboard_context

        ctx = super().get_context_data(**kwargs)
        ctx.update(build_accounting_dashboard_context(self.request.GET))
        ctx['title'] = 'Accounting Dashboard'
        ctx['selected_fy_id'] = self.request.GET.get('fiscal_year', '')
        return ctx
