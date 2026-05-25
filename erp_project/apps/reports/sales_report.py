"""Standard ERP sales report — invoicing, collections, receivables, quotations."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce

from apps.advances.models import CustomerAdvance
from apps.finance.models import Payment
from apps.sales.models import Estimate, Invoice, SalesCreditNote

INVOICE_REVENUE_STATUSES = ('posted', 'sent', 'paid', 'partial', 'overdue')
PAYMENT_RECEIVED_STATUSES = ('confirmed', 'reconciled')


def _pct(numerator: Decimal, denominator: Decimal) -> int:
    if not denominator:
        return 0
    return int((numerator / denominator * Decimal('100')).quantize(Decimal('1')))


def _money_agg(qs, *, subtotal_field='subtotal', vat_field='vat_amount', total_field='total_amount'):
    return qs.aggregate(
        count=Count('id'),
        subtotal=Coalesce(Sum(subtotal_field), Decimal('0.00')),
        vat=Coalesce(Sum(vat_field), Decimal('0.00')),
        total=Coalesce(Sum(total_field), Decimal('0.00')),
    )


def build_sales_report(*, start_date, end_date):
    """Period sales report aligned with typical ERP sales dashboards."""
    zero = Decimal('0.00')

    # --- Invoiced revenue (by invoice date) ---
    invoice_qs = (
        Invoice.objects.filter(
            is_active=True,
            invoice_date__gte=start_date,
            invoice_date__lte=end_date,
            status__in=INVOICE_REVENUE_STATUSES,
        )
        .select_related('customer', 'estimate')
        .order_by('-invoice_date', '-id')
    )
    invoiced = _money_agg(invoice_qs)
    invoiced_paid = invoice_qs.aggregate(
        paid=Coalesce(Sum('paid_amount'), zero),
    )['paid'] or zero

    # --- Open receivables (current snapshot, invoices issued on/before period end) ---
    outstanding_qs = (
        Invoice.objects.filter(
            is_active=True,
            invoice_date__lte=end_date,
            status__in=INVOICE_REVENUE_STATUSES,
        )
        .annotate(
            balance=ExpressionWrapper(
                F('total_amount') - F('paid_amount'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        .filter(balance__gt=zero)
        .select_related('customer')
        .order_by('-invoice_date', '-id')
    )
    outstanding_agg = outstanding_qs.aggregate(
        count=Count('id'),
        total=Coalesce(Sum('balance'), zero),
    )

    # --- Collections in period ---
    payment_qs = (
        Payment.objects.filter(
            is_active=True,
            payment_type='received',
            party_type='customer',
            status__in=PAYMENT_RECEIVED_STATUSES,
            payment_date__gte=start_date,
            payment_date__lte=end_date,
        )
        .order_by('-payment_date', '-id')
    )
    payments_agg = payment_qs.aggregate(
        count=Count('id'),
        total=Coalesce(Sum('amount'), zero),
    )

    receipt_qs = (
        CustomerAdvance.objects.filter(
            is_active=True,
            status='posted',
            date__gte=start_date,
            date__lte=end_date,
        )
        .select_related('customer')
        .order_by('-date', '-id')
    )
    receipts_agg = _money_agg(
        receipt_qs,
        subtotal_field='amount',
        vat_field='vat_amount',
        total_field='total_amount',
    )

    collected_total = (payments_agg['total'] or zero) + (receipts_agg['total'] or zero)
    collected_count = (payments_agg['count'] or 0) + (receipts_agg['count'] or 0)

    # --- Credit notes in period ---
    credit_qs = SalesCreditNote.objects.filter(
        is_active=True,
        status='posted',
        date__gte=start_date,
        date__lte=end_date,
    )
    credit_notes = _money_agg(credit_qs)

    # --- Quotations in period (by estimate date) ---
    estimate_base = Estimate.objects.filter(
        is_active=True,
        date__gte=start_date,
        date__lte=end_date,
    )
    pipeline_rows = []
    status_labels = dict(Estimate.STATUS_CHOICES)
    for status_code, label in Estimate.STATUS_CHOICES:
        qs = estimate_base.filter(status=status_code)
        agg = _money_agg(qs)
        pipeline_rows.append({
            'status': status_code,
            'label': label,
            'count': agg['count'] or 0,
            'total': agg['total'] or zero,
        })

    won_qs = estimate_base.filter(status='quotation_won').select_related('customer')
    lost_qs = estimate_base.filter(status='quotation_lost').select_related('customer')
    won = _money_agg(won_qs)
    lost = _money_agg(lost_qs)

    pipeline_max = max([row['count'] for row in pipeline_rows] + [1])

    quotation_rows = [
        {
            'pk': est.pk,
            'display_estimate_number': est.display_estimate_number,
            'customer_name': est.customer.name if est.customer_id else '',
            'date': est.date,
            'total_amount': est.total_amount,
            'status': est.get_status_display(),
            'status_code': est.status,
        }
        for est in estimate_base.select_related('customer').order_by('-date', '-id')[:500]
    ]

    invoiced_total = invoiced['total'] or zero

    return {
        'start_date': start_date,
        'end_date': end_date,
        'invoiced': invoiced,
        'invoiced_paid': invoiced_paid,
        'outstanding': outstanding_agg,
        'payments': payments_agg,
        'receipts': receipts_agg,
        'collected': {
            'count': collected_count,
            'total': collected_total,
        },
        'credit_notes': credit_notes,
        'won': won,
        'lost': lost,
        'pipeline_rows': pipeline_rows,
        'pipeline_max_count': pipeline_max,
        'quotation_rows': quotation_rows,
        'collection_pct': _pct(collected_total, invoiced_total),
        'invoice_collection_pct': _pct(invoiced_paid, invoiced_total),
        'invoice_rows': [
            {
                'pk': inv.pk,
                'invoice_number': inv.invoice_number,
                'customer_name': inv.customer.name if inv.customer_id else '',
                'date': inv.invoice_date,
                'status': inv.get_status_display(),
                'subtotal': inv.subtotal,
                'vat_amount': inv.vat_amount,
                'total_amount': inv.total_amount,
                'paid_amount': inv.paid_amount,
                'balance': inv.balance,
            }
            for inv in invoice_qs[:500]
        ],
        'outstanding_rows': [
            {
                'pk': inv.pk,
                'invoice_number': inv.invoice_number,
                'customer_name': inv.customer.name if inv.customer_id else '',
                'date': inv.invoice_date,
                'due_date': inv.due_date,
                'total_amount': inv.total_amount,
                'paid_amount': inv.paid_amount,
                'balance': inv.balance,
            }
            for inv in outstanding_qs[:500]
        ],
        'won_rows': [
            {
                'pk': est.pk,
                'display_estimate_number': est.display_estimate_number,
                'customer_name': est.customer.name if est.customer_id else '',
                'date': est.date,
                'total_amount': est.total_amount,
            }
            for est in won_qs[:500]
        ],
        'lost_rows': [
            {
                'pk': est.pk,
                'display_estimate_number': est.display_estimate_number,
                'customer_name': est.customer.name if est.customer_id else '',
                'date': est.date,
                'total_amount': est.total_amount,
            }
            for est in lost_qs[:500]
        ],
        'payment_rows': [
            {
                'pk': pay.pk,
                'payment_number': pay.payment_number,
                'party_name': pay.party_name,
                'date': pay.payment_date,
                'amount': pay.amount,
                'reference': pay.reference,
                'method': pay.get_payment_method_display(),
            }
            for pay in payment_qs[:500]
        ],
        'receipt_rows': [
            {
                'pk': adv.pk,
                'advance_number': adv.advance_number,
                'customer_name': adv.customer.name if adv.customer_id else '',
                'date': adv.date,
                'total_amount': adv.total_amount,
            }
            for adv in receipt_qs[:500]
        ],
    }
