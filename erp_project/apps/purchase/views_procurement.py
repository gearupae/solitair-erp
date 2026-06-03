"""Extended purchase views — GRN & RFQ / CPA."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView

from apps.core.mixins import PermissionRequiredMixin
from apps.core.utils import PermissionChecker
from apps.purchase.models import PurchaseOrder, Vendor
from apps.purchase.models_grn import GoodsReceiptNote
from apps.purchase.models_rfq import RFQ, RFQLine, SupplierQuote, SupplierQuoteLine
from apps.purchase.services.grn_service import cancel_grn, post_grn_from_po
from apps.purchase.services.rfq_service import (
    award_rfq,
    build_comparison_matrix,
    convert_awards_to_pos,
    pull_lines_from_mr,
)


class GRNListView(PermissionRequiredMixin, ListView):
    model = GoodsReceiptNote
    template_name = 'purchase/grn_list.html'
    context_object_name = 'grns'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25

    def get_queryset(self):
        return GoodsReceiptNote.objects.select_related(
            'supplier', 'purchase_order', 'warehouse', 'received_by'
        ).order_by('-received_on', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Goods Receipt Notes'
        return ctx


class GRNDetailView(PermissionRequiredMixin, DetailView):
    model = GoodsReceiptNote
    template_name = 'purchase/grn_detail.html'
    context_object_name = 'grn'
    module_name = 'purchase'
    permission_type = 'view'

    def get_queryset(self):
        return GoodsReceiptNote.objects.prefetch_related('lines__item', 'attachments').select_related(
            'supplier', 'purchase_order', 'warehouse'
        )


@login_required
def grn_cancel(request, pk):
    grn = get_object_or_404(GoodsReceiptNote, pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:grn_detail', pk=pk)
    try:
        cancel_grn(grn, request.user, request.POST.get('reason', ''))
        messages.success(request, f'GRN {grn.grn_number} cancelled.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('purchase:grn_detail', pk=pk)


class RFQListView(PermissionRequiredMixin, ListView):
    model = RFQ
    template_name = 'purchase/rfq_list.html'
    context_object_name = 'rfqs'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'RFQs / Competitive Analysis'
        return ctx


class RFQDetailView(PermissionRequiredMixin, DetailView):
    model = RFQ
    template_name = 'purchase/rfq_detail.html'
    context_object_name = 'rfq'
    module_name = 'purchase'
    permission_type = 'view'

    def get_queryset(self):
        return RFQ.objects.prefetch_related('lines', 'quotes__lines', 'quotes__supplier', 'awards')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['comparison'] = build_comparison_matrix(self.object)
        ctx['suppliers'] = Vendor.objects.filter(is_active=True, status='active')
        return ctx


@login_required
def rfq_award(request, pk):
    rfq = get_object_or_404(RFQ, pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:rfq_detail', pk=pk)
    awards = []
    for line in rfq.lines.all():
        sid = request.POST.get(f'supplier_{line.pk}')
        if not sid:
            continue
        awards.append({
            'rfq_line_id': line.pk,
            'supplier_id': int(sid),
            'awarded_qty': request.POST.get(f'qty_{line.pk}', line.quantity),
            'unit_price': request.POST.get(f'price_{line.pk}', '0'),
        })
    try:
        award_rfq(
            rfq, request.user, awards,
            justification=request.POST.get('justification', 'price'),
            award_notes=request.POST.get('award_notes', ''),
        )
        messages.success(request, f'RFQ {rfq.rfq_number} awarded.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('purchase:rfq_detail', pk=pk)


@login_required
def rfq_convert_po(request, pk):
    rfq = get_object_or_404(RFQ, pk=pk)
    try:
        pos = convert_awards_to_pos(rfq, request.user)
        messages.success(request, f'Created {len(pos)} purchase order(s).')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('purchase:rfq_detail', pk=pk)


@login_required
def rfq_pull_mr(request, pk):
    rfq = get_object_or_404(RFQ, pk=pk)
    mr_id = request.POST.get('material_requisition_id')
    if mr_id:
        from apps.inventory.models import ConsumableRequest
        mr = get_object_or_404(ConsumableRequest, pk=mr_id, request_kind='material')
        pull_lines_from_mr(rfq, mr)
        messages.success(request, 'RFQ lines populated from MR.')
    return redirect('purchase:rfq_detail', pk=pk)
