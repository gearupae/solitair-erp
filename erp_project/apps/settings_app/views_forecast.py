"""Monthly cash-flow estimation under Settings → Forecast."""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.core.mixins import PermissionRequiredMixin
from apps.core.utils import PermissionChecker
from apps.settings_app.models import CashFlowChequeLine, CashFlowExpenseLine, CashFlowIncomeLine

from .services.cashflow_service import (
    build_sheet_context,
    dismiss_auto_line,
    estimate_forecast_available,
    get_or_create_sheet,
    invoice_forecast_available,
    master_data,
    patch_income_expected,
    patch_income_sales_man,
    save_cheque_line,
    save_expense_line,
    save_income_line,
    vendor_bill_forecast_available,
)


class ForecastView(PermissionRequiredMixin, TemplateView):
    template_name = 'settings/forecast.html'
    module_name = 'settings'
    permission_type = 'view'

    def _parse_year_month(self):
        today = timezone.localdate()
        try:
            year = int(self.request.GET.get('year', today.year))
        except (TypeError, ValueError):
            year = today.year
        try:
            month = int(self.request.GET.get('month', today.month))
        except (TypeError, ValueError):
            month = today.month
        month = max(1, min(12, month))
        if year < 2000 or year > 2100:
            year = today.year
        return year, month

    def _redirect(self, year, month):
        return redirect(reverse('settings:forecast') + f'?year={year}&month={month}')

    def _can_edit(self):
        return self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'settings', 'edit'
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        year, month = self._parse_year_month()
        today = timezone.localdate()
        sheet = get_or_create_sheet(year, month)
        sheet_ctx = build_sheet_context(sheet)
        masters = master_data()

        from apps.settings_app.models import CompanySettings

        company = CompanySettings.get_settings()
        invoice_options = [
            {
                'pk': inv.pk,
                'label': inv.invoice_number,
                'customer_id': inv.customer_id,
                'max_amount': float(invoice_forecast_available(inv.pk)),
            }
            for inv in masters['invoices']
        ]
        quotation_options = [
            {
                'pk': est.pk,
                'label': est.display_estimate_number,
                'customer_id': est.customer_id,
                'max_amount': float(estimate_forecast_available(est.pk)),
            }
            for est in masters['quotations']
        ]
        bill_options = [
            {
                'pk': bill.pk,
                'label': f'{bill.bill_number} — {bill.vendor.name}',
                'vendor_id': bill.vendor_id,
                'max_amount': float(vendor_bill_forecast_available(bill.pk)),
            }
            for bill in masters['vendor_bills']
        ]

        ctx.update(sheet_ctx)
        ctx.update(masters)
        ctx.update(
            {
                'title': 'Forecast',
                'year': year,
                'month': month,
                'today': today,
                'month_choices': list(range(1, 13)),
                'year_choices': list(range(today.year - 2, today.year + 2)),
                'company': company,
                'can_edit': self._can_edit(),
                'income_categories': CashFlowIncomeLine.INCOME_CATEGORY_CHOICES,
                'income_payment_types': CashFlowIncomeLine.PAYMENT_TYPE_CHOICES,
                'expense_accounts': CashFlowExpenseLine.ACCOUNT_CHOICES,
                'expense_payment_types': CashFlowExpenseLine.PAYMENT_TYPE_CHOICES,
                'invoice_options': invoice_options,
                'quotation_options': quotation_options,
                'bill_options': bill_options,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        if not self._can_edit():
            messages.error(request, 'Permission denied.')
            return self._redirect(*self._parse_year_month())

        year, month = self._parse_year_month()
        sheet = get_or_create_sheet(year, month)
        action = (request.POST.get('action') or '').strip()

        if action == 'save_summary':
            from .services.cashflow_service import _parse_decimal

            sheet.cash_bank_in_hand = _parse_decimal(request.POST.get('cash_bank_in_hand'))
            sheet.save(update_fields=['cash_bank_in_hand', 'updated_at'])
            messages.success(request, 'Summary updated.')
            return self._redirect(year, month)

        if action == 'add_income':
            _, err = save_income_line(sheet, request.POST)
            if err:
                messages.error(request, err)
            else:
                messages.success(request, 'Income line added.')
        elif action == 'update_income':
            line_id = request.POST.get('line_id')
            if line_id and str(line_id).isdigit():
                _, err = save_income_line(sheet, request.POST, int(line_id))
                if err:
                    messages.error(request, err)
                else:
                    messages.success(request, 'Income line updated.')
        elif action == 'delete_income':
            line_id = request.POST.get('line_id')
            if line_id and str(line_id).isdigit():
                if dismiss_auto_line(CashFlowIncomeLine, sheet, int(line_id)):
                    messages.success(request, 'Income line removed.')
                else:
                    messages.error(request, 'Income line not found.')

        elif action == 'patch_income_expected':
            line_id = request.POST.get('line_id')
            from .services.cashflow_service import _parse_decimal

            if line_id and str(line_id).isdigit():
                err = patch_income_expected(sheet, int(line_id), _parse_decimal(request.POST.get('income_expected')))
                if err:
                    messages.error(request, err)
                else:
                    messages.success(request, 'Expected amount updated.')

        elif action == 'patch_income_sales_man':
            line_id = request.POST.get('line_id')
            raw_emp = (request.POST.get('employee') or '').strip()
            employee_id = int(raw_emp) if raw_emp.isdigit() else None
            if line_id and str(line_id).isdigit():
                err = patch_income_sales_man(sheet, int(line_id), employee_id)
                if err:
                    messages.error(request, err)
                else:
                    messages.success(request, 'Sales person updated.')

        elif action == 'add_cheque':
            _, err = save_cheque_line(sheet, request.POST)
            if err:
                messages.error(request, err)
            else:
                messages.success(request, 'Cheque line added.')
        elif action == 'update_cheque':
            line_id = request.POST.get('line_id')
            if line_id and str(line_id).isdigit():
                _, err = save_cheque_line(sheet, request.POST, int(line_id))
                if err:
                    messages.error(request, err)
                else:
                    messages.success(request, 'Cheque line updated.')
        elif action == 'delete_cheque':
            line_id = request.POST.get('line_id')
            if line_id and str(line_id).isdigit():
                if dismiss_auto_line(CashFlowChequeLine, sheet, int(line_id)):
                    messages.success(request, 'Cheque line removed.')
                else:
                    messages.error(request, 'Cheque line not found.')

        elif action == 'add_expense':
            _, err = save_expense_line(sheet, request.POST)
            if err:
                messages.error(request, err)
            else:
                messages.success(request, 'Expense line added.')
        elif action == 'update_expense':
            line_id = request.POST.get('line_id')
            if line_id and str(line_id).isdigit():
                _, err = save_expense_line(sheet, request.POST, int(line_id))
                if err:
                    messages.error(request, err)
                else:
                    messages.success(request, 'Expense line updated.')
        elif action == 'delete_expense':
            line_id = request.POST.get('line_id')
            if line_id and str(line_id).isdigit():
                if dismiss_auto_line(CashFlowExpenseLine, sheet, int(line_id)):
                    messages.success(request, 'Expense line removed.')
                else:
                    messages.error(request, 'Expense line not found.')
        else:
            messages.error(request, 'Unknown action.')

        return self._redirect(year, month)
