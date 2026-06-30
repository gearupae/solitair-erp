"""Monthly cash-flow estimation — expected vs received/paid."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Max, Q, Sum

from apps.crm.models import Customer
from apps.finance.models import Payment
from apps.purchase.models import Vendor, VendorBill
from apps.sales.models import Estimate, Invoice
from apps.settings_app.models import (
    CashFlowChequeLine,
    CashFlowExpenseLine,
    CashFlowIncomeLine,
    CashFlowMonthSheet,
)

ZERO = Decimal('0.00')
PAYMENT_DONE_STATUSES = ('confirmed', 'reconciled')


def _money(val) -> Decimal:
    if val is None:
        return ZERO
    return Decimal(str(val)).quantize(Decimal('0.01'))


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return start, end


def _parse_decimal(raw) -> Decimal:
    raw = (raw or '').strip().replace(',', '')
    if not raw:
        return ZERO
    return _money(Decimal(raw))


def _parse_date(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


_PDC_EXCLUDED_STATUSES = ('cleared', 'bounced', 'returned', 'replaced', 'cancelled')
_QUOTATION_PIPELINE_STATUSES = ('sent', 'approved', 'under_negotiation', 'quotation_won')
_PDC_PURPOSE_CATEGORY = {
    'rent': 'maintenance',
    'security_deposit': 'office',
    'maintenance': 'maintenance',
    'other': 'project',
}


def _estimate_category(estimate: Estimate) -> str:
    work = (estimate.type_of_work or '').lower()
    if 'amc' in work:
        return 'amc'
    if work == 'maintenance':
        return 'maintenance'
    return 'project'


def sync_auto_forecast_lines(sheet: CashFlowMonthSheet) -> None:
    """Pull PDC cheques, quotations, AMC renewals, and vendor bills into the month sheet."""
    month_start, month_end = _month_bounds(sheet.year, sheet.month)
    sort_income = _next_sort_order(sheet.income_lines.all())
    sort_cheque = _next_sort_order(sheet.cheque_lines.all())
    sort_expense = _next_sort_order(sheet.expense_lines.all())

    # --- PDC cheques (cheque date in this month, still in hand) ---
    try:
        from apps.property.models import PDCCheque

        pdc_qs = PDCCheque.objects.filter(
            is_active=True,
            cheque_date__gte=month_start,
            cheque_date__lte=month_end,
        ).exclude(status__in=_PDC_EXCLUDED_STATUSES).select_related('tenant')
        active_pdc_ids = set()

        for pdc in pdc_qs:
            active_pdc_ids.add(pdc.pk)
            if CashFlowChequeLine.objects.filter(
                sheet=sheet,
                pdc_cheque_id=pdc.pk,
                sync_suppressed=True,
            ).exists():
                continue

            line = CashFlowChequeLine.objects.filter(sheet=sheet, pdc_cheque_id=pdc.pk).first()
            if not line:
                line = CashFlowChequeLine(
                    sheet=sheet,
                    pdc_cheque=pdc,
                    line_source='auto_pdc',
                    sort_order=sort_cheque,
                )
                sort_cheque += 1
                line.income_balance = _money(pdc.amount)

            line.is_active = True
            line.line_date = pdc.cheque_date
            line.category = _PDC_PURPOSE_CATEGORY.get(pdc.purpose, 'maintenance')
            line.details = f'{pdc.pdc_number} · {pdc.cheque_number} ({pdc.bank_name})'
            line.save()

        CashFlowChequeLine.objects.filter(
            sheet=sheet,
            line_source='auto_pdc',
            is_active=True,
            sync_suppressed=False,
        ).exclude(pdc_cheque_id__in=active_pdc_ids).update(is_active=False)
    except ImportError:
        pass

    # --- Open quotations with outstanding balance ---
    estimate_qs = (
        Estimate.objects.filter(is_active=True, status__in=_QUOTATION_PIPELINE_STATUSES)
        .select_related('customer', 'sales_engineer', 'assigned_to')
        .order_by('-date')
    )
    active_estimate_ids = set()

    for estimate in estimate_qs:
        outstanding = _estimate_outstanding(estimate)
        if outstanding <= ZERO:
            continue
        active_estimate_ids.add(estimate.pk)
        if CashFlowIncomeLine.objects.filter(
            sheet=sheet,
            estimate_id=estimate.pk,
            line_source='auto_quotation',
            sync_suppressed=True,
        ).exists():
            continue

        existing = CashFlowIncomeLine.objects.filter(
            sheet=sheet,
            estimate_id=estimate.pk,
            is_active=True,
        ).first()
        if existing and existing.line_source != 'auto_quotation':
            continue

        line = CashFlowIncomeLine.objects.filter(
            sheet=sheet,
            estimate_id=estimate.pk,
            line_source='auto_quotation',
        ).first()
        if not line:
            line = CashFlowIncomeLine(
                sheet=sheet,
                estimate=estimate,
                line_source='auto_quotation',
                sort_order=sort_income,
            )
            sort_income += 1
            line.income_expected = outstanding

        line.is_active = True
        line.customer = estimate.customer
        line.line_date = estimate.valid_until or estimate.date
        line.category = _estimate_category(estimate)
        line.details = estimate.display_estimate_number
        line.payment_type = 'bank_adcb'
        line.sales_man = resolve_sales_man(estimate=estimate, customer=estimate.customer)
        if estimate.sales_engineer_id:
            line.employee_id = estimate.sales_engineer_id
        line.save()

    CashFlowIncomeLine.objects.filter(
        sheet=sheet,
        line_source='auto_quotation',
        is_active=True,
        sync_suppressed=False,
    ).exclude(estimate_id__in=active_estimate_ids).update(is_active=False)

    # --- AMC contracts ending this month (renewals due) ---
    from apps.operations.utils import get_amc_contract_queryset

    amc_qs = get_amc_contract_queryset().filter(
        end_date__gte=month_start,
        end_date__lte=month_end,
    ).exclude(status='cancelled').select_related('customer')
    active_amc_ids = set()

    for contract in amc_qs:
        active_amc_ids.add(contract.pk)
        if CashFlowIncomeLine.objects.filter(
            sheet=sheet,
            amc_contract_id=contract.pk,
            line_source='auto_amc',
            sync_suppressed=True,
        ).exists():
            continue

        existing = CashFlowIncomeLine.objects.filter(
            sheet=sheet,
            amc_contract_id=contract.pk,
            is_active=True,
        ).first()
        if existing and existing.line_source != 'auto_amc':
            continue

        line = CashFlowIncomeLine.objects.filter(
            sheet=sheet,
            amc_contract_id=contract.pk,
            line_source='auto_amc',
        ).first()
        if not line:
            line = CashFlowIncomeLine(
                sheet=sheet,
                amc_contract=contract,
                line_source='auto_amc',
                sort_order=sort_income,
            )
            sort_income += 1
            line.income_expected = _money(contract.contract_value)

        line.is_active = True
        line.customer = contract.customer
        line.line_date = contract.end_date
        line.category = 'amc'
        line.details = f'AMC renewal — {contract.name}'
        line.payment_type = 'bank_adcb'
        line.sales_man = resolve_sales_man(amc_contract=contract, customer=contract.customer)
        line.save()

    CashFlowIncomeLine.objects.filter(
        sheet=sheet,
        line_source='auto_amc',
        is_active=True,
        sync_suppressed=False,
    ).exclude(amc_contract_id__in=active_amc_ids).update(is_active=False)

    # --- Vendor bills dated this month ---
    bill_qs = VendorBill.objects.filter(
        is_active=True,
        bill_date__gte=month_start,
        bill_date__lte=month_end,
    ).exclude(status='cancelled').select_related('vendor')
    active_bill_ids = set()

    for bill in bill_qs:
        outstanding = _vendor_bill_outstanding(bill)
        if outstanding <= ZERO:
            continue
        active_bill_ids.add(bill.pk)
        if CashFlowExpenseLine.objects.filter(
            sheet=sheet,
            vendor_bill_id=bill.pk,
            line_source='auto_vendor_bill',
            sync_suppressed=True,
        ).exists():
            continue

        existing = CashFlowExpenseLine.objects.filter(
            sheet=sheet,
            vendor_bill_id=bill.pk,
            is_active=True,
        ).first()
        if existing and existing.line_source != 'auto_vendor_bill':
            continue

        line = CashFlowExpenseLine.objects.filter(
            sheet=sheet,
            vendor_bill_id=bill.pk,
            line_source='auto_vendor_bill',
        ).first()
        if not line:
            line = CashFlowExpenseLine(
                sheet=sheet,
                vendor_bill=bill,
                line_source='auto_vendor_bill',
                sort_order=sort_expense,
            )
            sort_expense += 1
            line.expense = outstanding

        line.is_active = True
        line.vendor = bill.vendor
        line.line_date = bill.bill_date
        line.account = 'purchase'
        line.details = bill.bill_number
        line.payment_type = 'bank'
        line.save()

    CashFlowExpenseLine.objects.filter(
        sheet=sheet,
        line_source='auto_vendor_bill',
        is_active=True,
        sync_suppressed=False,
    ).exclude(vendor_bill_id__in=active_bill_ids).update(is_active=False)


def get_or_create_sheet(year: int, month: int) -> CashFlowMonthSheet:
    sheet, _ = CashFlowMonthSheet.objects.get_or_create(
        year=year,
        month=month,
        defaults={'is_active': True},
    )
    sync_auto_forecast_lines(sheet)
    return sheet


_MONTH_LABELS = (
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
)


def build_month_columns(year: int) -> list[dict]:
    """Month pill navigation for the forecast workbook."""
    return [{'month': m, 'label': _MONTH_LABELS[m - 1]} for m in range(1, 13)]


def _payments_received(customer_id: int | None, month_start: date, month_end: date, reference: str = '') -> Decimal:
    if not customer_id:
        return ZERO
    qs = Payment.objects.filter(
        is_active=True,
        payment_type='received',
        party_type='customer',
        party_id=customer_id,
        payment_date__gte=month_start,
        payment_date__lte=month_end,
        status__in=PAYMENT_DONE_STATUSES,
    )
    ref = (reference or '').strip()
    if ref:
        qs = qs.filter(Q(reference__icontains=ref) | Q(notes__icontains=ref))
    from django.db.models import Sum

    total = qs.aggregate(t=Sum('amount'))['t']
    return _money(total)


def _payments_made(vendor_id: int | None, month_start: date, month_end: date, reference: str = '') -> Decimal:
    if not vendor_id:
        return ZERO
    qs = Payment.objects.filter(
        is_active=True,
        payment_type='made',
        party_type='vendor',
        party_id=vendor_id,
        payment_date__gte=month_start,
        payment_date__lte=month_end,
        status__in=PAYMENT_DONE_STATUSES,
    )
    ref = (reference or '').strip()
    if ref:
        qs = qs.filter(Q(reference__icontains=ref) | Q(notes__icontains=ref))
    from django.db.models import Sum

    total = qs.aggregate(t=Sum('amount'))['t']
    return _money(total)


def _invoice_outstanding(invoice: Invoice) -> Decimal:
    return _money(invoice.total_amount - invoice.paid_amount)


def _vendor_bill_outstanding(bill: VendorBill) -> Decimal:
    return _money(bill.total_amount - bill.paid_amount)


def _estimate_outstanding(estimate: Estimate) -> Decimal:
    invoiced = Invoice.objects.filter(
        estimate_id=estimate.pk,
        is_active=True,
    ).exclude(status='cancelled').aggregate(t=Sum('total_amount'))['t']
    return max(ZERO, _money(estimate.total_amount) - _money(invoiced))


def estimate_forecast_allocated(
    estimate_id: int,
    *,
    exclude_income_id: int | None = None,
) -> Decimal:
    qs = CashFlowIncomeLine.objects.filter(is_active=True, estimate_id=estimate_id)
    if exclude_income_id:
        qs = qs.exclude(pk=exclude_income_id)
    total = qs.aggregate(t=Sum('income_expected'))['t']
    return _money(total)


def estimate_forecast_available(
    estimate_id: int,
    *,
    exclude_income_id: int | None = None,
) -> Decimal:
    estimate = Estimate.objects.filter(pk=estimate_id, is_active=True).first()
    if not estimate:
        return ZERO
    remaining = _estimate_outstanding(estimate) - estimate_forecast_allocated(
        estimate_id,
        exclude_income_id=exclude_income_id,
    )
    return max(ZERO, remaining)


def invoice_forecast_allocated(
    invoice_id: int,
    *,
    exclude_income_id: int | None = None,
    exclude_cheque_id: int | None = None,
) -> Decimal:
    income_qs = CashFlowIncomeLine.objects.filter(is_active=True, invoice_id=invoice_id)
    if exclude_income_id:
        income_qs = income_qs.exclude(pk=exclude_income_id)
    cheque_qs = CashFlowChequeLine.objects.filter(is_active=True, invoice_id=invoice_id)
    if exclude_cheque_id:
        cheque_qs = cheque_qs.exclude(pk=exclude_cheque_id)
    income_total = income_qs.aggregate(t=Sum('income_expected'))['t']
    cheque_total = cheque_qs.aggregate(t=Sum('income_balance'))['t']
    return _money(income_total) + _money(cheque_total)


def vendor_bill_forecast_allocated(bill_id: int, *, exclude_expense_id: int | None = None) -> Decimal:
    qs = CashFlowExpenseLine.objects.filter(is_active=True, vendor_bill_id=bill_id)
    if exclude_expense_id:
        qs = qs.exclude(pk=exclude_expense_id)
    total = qs.aggregate(t=Sum('expense'))['t']
    return _money(total)


def invoice_forecast_available(
    invoice_id: int,
    *,
    exclude_income_id: int | None = None,
    exclude_cheque_id: int | None = None,
) -> Decimal:
    invoice = Invoice.objects.filter(pk=invoice_id, is_active=True).first()
    if not invoice:
        return ZERO
    remaining = _invoice_outstanding(invoice) - invoice_forecast_allocated(
        invoice_id,
        exclude_income_id=exclude_income_id,
        exclude_cheque_id=exclude_cheque_id,
    )
    return max(ZERO, remaining)


def vendor_bill_forecast_available(bill_id: int, *, exclude_expense_id: int | None = None) -> Decimal:
    bill = VendorBill.objects.filter(pk=bill_id, is_active=True).first()
    if not bill:
        return ZERO
    remaining = _vendor_bill_outstanding(bill) - vendor_bill_forecast_allocated(
        bill_id,
        exclude_expense_id=exclude_expense_id,
    )
    return max(ZERO, remaining)


def validate_income_amount(
    *,
    estimate_id: int | None = None,
    invoice_id: int | None = None,
    amount: Decimal,
    exclude_line_id: int | None = None,
) -> str | None:
    if amount <= ZERO:
        return None
    if estimate_id:
        available = estimate_forecast_available(estimate_id, exclude_income_id=exclude_line_id)
        if amount > available:
            estimate = Estimate.objects.get(pk=estimate_id)
            return (
                f'Amount exceeds quotation {estimate.display_estimate_number} balance. '
                f'Maximum available: AED {available:,.2f}.'
            )
        return None
    if invoice_id:
        available = invoice_forecast_available(invoice_id, exclude_income_id=exclude_line_id)
        if amount > available:
            invoice = Invoice.objects.get(pk=invoice_id)
            return (
                f'Amount exceeds invoice {invoice.invoice_number} balance. '
                f'Maximum available: AED {available:,.2f}.'
            )
    return None


def validate_cheque_amount(invoice_id: int | None, amount: Decimal, *, exclude_line_id: int | None = None) -> str | None:
    if not invoice_id or amount <= ZERO:
        return None
    available = invoice_forecast_available(invoice_id, exclude_cheque_id=exclude_line_id)
    if amount > available:
        invoice = Invoice.objects.get(pk=invoice_id)
        return (
            f'Amount exceeds invoice {invoice.invoice_number} balance. '
            f'Maximum available: AED {available:,.2f}.'
        )
    return None


def validate_expense_amount(bill_id: int | None, amount: Decimal, *, exclude_line_id: int | None = None) -> str | None:
    if not bill_id or amount <= ZERO:
        return None
    available = vendor_bill_forecast_available(bill_id, exclude_expense_id=exclude_line_id)
    if amount > available:
        bill = VendorBill.objects.get(pk=bill_id)
        return (
            f'Amount exceeds bill {bill.bill_number} balance. '
            f'Maximum available: AED {available:,.2f}.'
        )
    return None


def resolve_sales_man(*, invoice=None, estimate=None, project=None, amc_contract=None, customer=None) -> str:
    if estimate:
        if estimate.sales_engineer_id:
            return estimate.sales_engineer.full_name
        if estimate.assigned_to_id:
            u = estimate.assigned_to
            return (u.get_full_name() or u.username).strip()

    if invoice:
        if invoice.estimate_id and invoice.estimate.sales_engineer_id:
            return invoice.estimate.sales_engineer.full_name
        if invoice.estimate_id and invoice.estimate.assigned_to_id:
            u = invoice.estimate.assigned_to
            return (u.get_full_name() or u.username).strip()
        if invoice.customer_id and invoice.customer.assigned_salesperson_id:
            return invoice.customer.assigned_salesperson.full_name

    if project:
        est = project.estimates.filter(is_active=True).select_related('assigned_to', 'sales_engineer').order_by('-date').first()
        if est:
            if est.sales_engineer_id:
                return est.sales_engineer.full_name
            if est.assigned_to_id:
                return (est.assigned_to.get_full_name() or est.assigned_to.username).strip()

    if customer and customer.assigned_salesperson_id:
        return customer.assigned_salesperson.full_name
    return ''


def income_line_received(line: CashFlowIncomeLine, month_start: date, month_end: date) -> Decimal:
    ref = ''
    if line.estimate_id:
        ref = line.estimate.estimate_number
    elif line.invoice_id:
        ref = line.invoice.invoice_number
    elif line.project_id:
        ref = line.project.project_code
    elif line.amc_contract_id:
        ref = line.amc_contract.contract_number
    received = _payments_received(line.customer_id, month_start, month_end, ref)
    if received <= ZERO and line.invoice_id and line.invoice.paid_amount:
        received = _money(min(line.invoice.paid_amount, line.income_expected or line.invoice.paid_amount))
    return received


def cheque_line_received(line: CashFlowChequeLine, month_start: date, month_end: date) -> Decimal:
    ref = line.invoice.invoice_number if line.invoice_id else ''
    received = _payments_received(line.customer_id, month_start, month_end, ref)
    if received <= ZERO and line.invoice_id:
        received = _money(min(line.invoice.paid_amount, line.income_balance or line.invoice.paid_amount))
    return received


def expense_line_paid(line: CashFlowExpenseLine, month_start: date, month_end: date) -> Decimal:
    ref = line.vendor_bill.bill_number if line.vendor_bill_id else ''
    paid = _payments_made(line.vendor_id, month_start, month_end, ref)
    if paid <= ZERO and line.vendor_bill_id and line.vendor_bill.paid_amount:
        paid = _money(min(line.vendor_bill.paid_amount, line.expense or line.vendor_bill.paid_amount))
    return paid


def _line_row(line, *, expected_field, received_val, label=''):
    expected = _money(getattr(line, expected_field))
    received = _money(received_val)
    balance = expected - received
    return {
        'pk': line.pk,
        'line_date': line.line_date,
        'details': line.details,
        'expected': float(expected),
        'received': float(received),
        'balance': float(balance),
        'line_kind': getattr(line, 'line_kind', 'normal'),
        'label': label,
        'obj': line,
    }


def build_income_rows(sheet: CashFlowMonthSheet, month_start: date, month_end: date) -> list[dict]:
    lines = sheet.income_lines.filter(is_active=True).select_related(
        'customer',
        'employee',
        'estimate',
        'estimate__sales_engineer',
        'invoice',
        'project',
        'amc_contract',
        'invoice__estimate',
        'invoice__estimate__sales_engineer',
    )
    rows = []
    for line in lines:
        received = income_line_received(line, month_start, month_end)
        row = _line_row(line, expected_field='income_expected', received_val=received)
        row.update(
            {
                'customer': line.customer.name if line.customer_id else '—',
                'customer_id': line.customer_id,
                'category': line.get_category_display(),
                'category_code': line.category,
                'payment_type': line.get_payment_type_display(),
                'payment_type_code': line.payment_type,
                'sales_man': (
                    line.employee.full_name
                    if line.employee_id
                    else line.sales_man
                    or resolve_sales_man(
                        invoice=line.invoice,
                        estimate=line.estimate,
                        project=line.project,
                        amc_contract=line.amc_contract,
                        customer=line.customer,
                    )
                ),
                'employee_id': line.employee_id,
                'estimate_id': line.estimate_id,
                'invoice_id': line.invoice_id,
                'project_id': line.project_id,
                'amc_contract_id': line.amc_contract_id,
                'line_source': line.line_source,
                'line_source_label': line.get_line_source_display(),
                'is_auto': line.line_source != 'manual',
            }
        )
        rows.append(row)
    return rows


def build_cheque_rows(sheet: CashFlowMonthSheet, month_start: date, month_end: date) -> list[dict]:
    rows = []
    for line in sheet.cheque_lines.filter(is_active=True).select_related(
        'customer', 'invoice', 'pdc_cheque', 'pdc_cheque__tenant'
    ):
        received = cheque_line_received(line, month_start, month_end)
        row = _line_row(line, expected_field='income_balance', received_val=received)
        if line.pdc_cheque_id:
            customer_label = line.pdc_cheque.tenant.name
        else:
            customer_label = line.customer.name if line.customer_id else '—'
        row.update(
            {
                'customer': customer_label,
                'customer_id': line.customer_id,
                'category': line.get_category_display(),
                'category_code': line.category,
                'payment_type': 'Cheque',
                'invoice_id': line.invoice_id,
                'pdc_cheque_id': line.pdc_cheque_id,
                'line_source': line.line_source,
                'line_source_label': line.get_line_source_display(),
                'is_auto': line.line_source != 'manual',
            }
        )
        rows.append(row)
    return rows


def build_expense_rows(sheet: CashFlowMonthSheet, month_start: date, month_end: date) -> list[dict]:
    rows = []
    for line in sheet.expense_lines.filter(is_active=True).select_related('vendor', 'vendor_bill'):
        paid = expense_line_paid(line, month_start, month_end)
        row = _line_row(line, expected_field='expense', received_val=paid)
        row.update(
            {
                'vendor': line.vendor.name if line.vendor_id else '—',
                'vendor_id': line.vendor_id,
                'account': line.get_account_display(),
                'account_code': line.account,
                'payment_type': line.get_payment_type_display(),
                'payment_type_code': line.payment_type,
                'vendor_bill_id': line.vendor_bill_id,
                'line_source': line.line_source,
                'line_source_label': line.get_line_source_display(),
                'is_auto': line.line_source != 'manual',
            }
        )
        rows.append(row)
    return rows


def _totals(rows: list[dict]) -> dict:
    return {
        'expected': sum(r['expected'] for r in rows),
        'received': sum(r['received'] for r in rows),
        'balance': sum(r['balance'] for r in rows),
    }


def build_summary(sheet: CashFlowMonthSheet, income_rows, cheque_rows, expense_rows) -> dict:
    income_tot = _totals(income_rows)
    cheque_tot = _totals(cheque_rows)
    expense_tot = _totals(expense_rows)

    cash_bank = float(_money(sheet.cash_bank_in_hand))
    cheque_in_hand = cheque_tot['balance']
    total_expense = expense_tot['balance']
    balance = cash_bank + cheque_in_hand - total_expense
    expected_income = income_tot['balance']
    closing_balance = balance + expected_income

    return {
        'total_expense': expense_tot['balance'],
        'total_expense_paid': expense_tot['received'],
        'total_expense_expected': expense_tot['expected'],
        'cash_bank_in_hand': cash_bank,
        'cheque_in_hand': cheque_in_hand,
        'balance': balance,
        'expected_income': expected_income,
        'closing_balance': closing_balance,
        'income_totals': income_tot,
        'cheque_totals': cheque_tot,
        'expense_totals': expense_tot,
    }


def build_sheet_context(sheet: CashFlowMonthSheet) -> dict:
    month_start, month_end = _month_bounds(sheet.year, sheet.month)
    income_rows = build_income_rows(sheet, month_start, month_end)
    cheque_rows = build_cheque_rows(sheet, month_start, month_end)
    expense_rows = build_expense_rows(sheet, month_start, month_end)
    summary = build_summary(sheet, income_rows, cheque_rows, expense_rows)
    return {
        'sheet': sheet,
        'month_start': month_start,
        'month_end': month_end,
        'income_rows': income_rows,
        'cheque_rows': cheque_rows,
        'expense_rows': expense_rows,
        'summary': summary,
    }


def _next_sort_order(qs):
    return (qs.aggregate(m=Max('sort_order')).get('m') or 0) + 1


def save_income_line(sheet, post_data, line_id=None):
    line = CashFlowIncomeLine.objects.filter(pk=line_id, sheet=sheet).first() if line_id else CashFlowIncomeLine(sheet=sheet)
    if line_id and not line:
        return None, 'Income line not found.'

    line_kind = post_data.get('line_kind') or 'normal'
    customer_id = post_data.get('customer') or None
    if customer_id and str(customer_id).isdigit():
        line.customer_id = int(customer_id)
    elif line_kind == 'unexpected_income':
        line.customer = None

    line.line_date = _parse_date(post_data.get('line_date'))
    line.category = post_data.get('category') or 'project'
    line.details = (post_data.get('details') or '')[:500]
    line.payment_type = post_data.get('payment_type') or 'bank_adcb'
    income_expected = _parse_decimal(post_data.get('income_expected'))
    line.line_kind = line_kind

    for fk, key in (('estimate', 'estimate'), ('amc_contract', 'amc_contract')):
        raw = post_data.get(key)
        setattr(line, f'{fk}_id', int(raw) if raw and str(raw).isdigit() else None)
    line.invoice_id = None
    line.project_id = None

    raw_emp = post_data.get('employee')
    line.employee_id = int(raw_emp) if raw_emp and str(raw_emp).isdigit() else None

    if line.estimate_id:
        error = validate_income_amount(
            estimate_id=line.estimate_id,
            amount=income_expected,
            exclude_line_id=line.pk,
        )
        if error:
            return None, error

    line.income_expected = income_expected

    if line.employee_id:
        from apps.hr.models import Employee

        emp = Employee.objects.filter(pk=line.employee_id).first()
        line.sales_man = emp.full_name if emp else ''
    elif not line.sales_man:
        line.sales_man = resolve_sales_man(
            estimate=line.estimate if line.estimate_id else None,
            amc_contract=line.amc_contract if line.amc_contract_id else None,
            customer=line.customer if line.customer_id else None,
        )

    if not line.pk:
        line.sort_order = _next_sort_order(sheet.income_lines.all())

    line.save()
    return line, None


def patch_income_expected(sheet, line_id: int, amount: Decimal) -> str | None:
    """Update only the expected amount on an income line (inline edit)."""
    line = CashFlowIncomeLine.objects.filter(pk=line_id, sheet=sheet, is_active=True).first()
    if not line:
        return 'Income line not found.'
    if amount < ZERO:
        return 'Amount cannot be negative.'
    if line.estimate_id:
        error = validate_income_amount(
            estimate_id=line.estimate_id,
            amount=amount,
            exclude_line_id=line.pk,
        )
        if error:
            return error
    if line.invoice_id:
        error = validate_income_amount(
            invoice_id=line.invoice_id,
            amount=amount,
            exclude_line_id=line.pk,
        )
        if error:
            return error
    line.income_expected = amount
    line.save(update_fields=['income_expected', 'updated_at'])
    return None


def patch_income_sales_man(sheet, line_id: int, employee_id: int | None) -> str | None:
    """Update sales person on an income line (inline edit)."""
    line = CashFlowIncomeLine.objects.filter(pk=line_id, sheet=sheet, is_active=True).first()
    if not line:
        return 'Income line not found.'

    from apps.hr.models import Employee

    if employee_id:
        emp = Employee.objects.filter(pk=employee_id, is_active=True).first()
        if not emp:
            return 'Employee not found.'
        line.employee = emp
        line.sales_man = emp.full_name
        line.save(update_fields=['employee', 'sales_man', 'updated_at'])
    else:
        line.employee = None
        line.sales_man = resolve_sales_man(
            invoice=line.invoice if line.invoice_id else None,
            estimate=line.estimate if line.estimate_id else None,
            project=line.project if line.project_id else None,
            amc_contract=line.amc_contract if line.amc_contract_id else None,
            customer=line.customer if line.customer_id else None,
        )
        line.save(update_fields=['employee', 'sales_man', 'updated_at'])
    return None


def dismiss_auto_line(model_cls, sheet, line_id: int) -> bool:
    """Soft-delete an auto-synced line and prevent it from being recreated."""
    line = model_cls.objects.filter(pk=line_id, sheet=sheet, is_active=True).first()
    if not line:
        return False
    update_fields = ['is_active', 'updated_at']
    if line.line_source != 'manual':
        line.sync_suppressed = True
        update_fields.append('sync_suppressed')
    line.is_active = False
    line.save(update_fields=update_fields)
    return True


def save_cheque_line(sheet, post_data, line_id=None):
    line = CashFlowChequeLine.objects.filter(pk=line_id, sheet=sheet).first() if line_id else CashFlowChequeLine(sheet=sheet)
    if line_id and not line:
        return None, 'Cheque line not found.'

    raw_cust = post_data.get('customer')
    line.customer_id = int(raw_cust) if raw_cust and str(raw_cust).isdigit() else None
    line.line_date = _parse_date(post_data.get('line_date'))
    line.category = post_data.get('category') or 'maintenance'
    line.details = (post_data.get('details') or '')[:500]
    income_balance = _parse_decimal(post_data.get('income_balance'))
    raw_inv = post_data.get('invoice')
    line.invoice_id = int(raw_inv) if raw_inv and str(raw_inv).isdigit() else None

    if line.invoice_id:
        error = validate_cheque_amount(line.invoice_id, income_balance, exclude_line_id=line.pk)
        if error:
            return None, error

    line.income_balance = income_balance
    if not line.pk:
        line.sort_order = _next_sort_order(sheet.cheque_lines.all())
    line.save()
    return line, None


def save_expense_line(sheet, post_data, line_id=None):
    line = CashFlowExpenseLine.objects.filter(pk=line_id, sheet=sheet).first() if line_id else CashFlowExpenseLine(sheet=sheet)
    if line_id and not line:
        return None, 'Expense line not found.'

    line_kind = post_data.get('line_kind') or 'normal'
    raw_vendor = post_data.get('vendor')
    line.vendor_id = int(raw_vendor) if raw_vendor and str(raw_vendor).isdigit() else None
    line.line_date = _parse_date(post_data.get('line_date'))
    line.account = post_data.get('account') or 'purchase'
    line.details = (post_data.get('details') or '')[:500]
    line.payment_type = post_data.get('payment_type') or 'bank'
    expense = _parse_decimal(post_data.get('expense'))
    line.line_kind = line_kind
    raw_bill = post_data.get('vendor_bill')
    line.vendor_bill_id = int(raw_bill) if raw_bill and str(raw_bill).isdigit() else None

    if line.vendor_bill_id:
        error = validate_expense_amount(line.vendor_bill_id, expense, exclude_line_id=line.pk)
        if error:
            return None, error

    line.expense = expense
    if not line.pk:
        line.sort_order = _next_sort_order(sheet.expense_lines.all())
    line.save()
    return line, None


def master_data():
    from apps.hr.models import Employee
    from apps.operations.utils import get_amc_contract_queryset

    return {
        'customers': Customer.objects.filter(is_active=True).order_by('name', 'company'),
        'employees': Employee.objects.filter(is_active=True).order_by('first_name', 'last_name'),
        'vendors': Vendor.objects.filter(is_active=True).order_by('name'),
        'invoices': Invoice.objects.filter(is_active=True).exclude(status='cancelled').select_related('customer').order_by('-invoice_date')[:500],
        'quotations': Estimate.objects.filter(is_active=True)
        .exclude(status__in=('rejected', 'quotation_lost'))
        .select_related('customer')
        .order_by('-date')[:500],
        'amc_contracts': get_amc_contract_queryset()[:300],
        'vendor_bills': VendorBill.objects.filter(is_active=True).exclude(status='cancelled').select_related('vendor').order_by('-bill_date')[:300],
    }
