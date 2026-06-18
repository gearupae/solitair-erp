"""Public customer-facing quotation view (no login)."""
from __future__ import annotations

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.sales.estimate_public_view import attach_device_cookie, get_or_create_device_id, record_public_view
from apps.sales.models import Estimate, EstimateItem


@require_GET
def public_estimate_view(request, token):
    """Render quotation HTML (same layout as PDF) via secret public link."""
    items_qs = EstimateItem.objects.select_related('inventory_item', 'tax_code').order_by(
        'sort_order', 'id'
    )
    estimate = get_object_or_404(
        Estimate.objects.filter(is_active=True, public_view_token=token)
        .select_related('customer', 'assigned_to', 'project')
        .prefetch_related(Prefetch('items', queryset=items_qs)),
    )

    device_id, is_new_cookie = get_or_create_device_id(request)
    record_public_view(request, estimate, device_id=device_id)

    from apps.sales.views import _build_estimate_pdf_context

    context = _build_estimate_pdf_context(request, estimate)
    context.update({
        'document_heading': 'QUOTATION',
        'document_number': estimate.display_estimate_number,
        'page_title': f'Quotation — {estimate.display_estimate_number}',
        'print_button_label': 'Print quotation',
        'show_pdf_status': False,
        'pdf_variant': 'quotation',
        'pdf_details_heading': 'Quotation details',
        'pdf_date_label': 'Quotation date',
        'is_public_view': True,
    })

    response = render(request, 'sales/estimate_pdf.html', context)
    if is_new_cookie:
        attach_device_cookie(response, device_id)
    return response
