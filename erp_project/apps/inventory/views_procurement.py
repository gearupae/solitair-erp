"""Extended inventory views — Material Requisitions & Inter-entity transfers."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView, ListView

from apps.core.mixins import PermissionRequiredMixin
from apps.core.utils import PermissionChecker
from apps.inventory.forms import ConsumableRequestForm, ConsumableRequestItemFormSet
from apps.inventory.models import ConsumableRequest, Warehouse
from apps.inventory.models_inter_entity import InterEntityTransfer, InterEntityTransferLine
from apps.inventory.services.inter_entity_service import (
    approve_transfer,
    issue_transfer,
    receive_transfer,
    reconciliation_report,
)
from apps.inventory.services.requisition_service import (
    approve_requisition,
    close_requisition,
    issue_requisition,
    reject_requisition,
    submit_requisition,
)


class MaterialRequisitionListView(PermissionRequiredMixin, ListView):
    model = ConsumableRequest
    template_name = 'inventory/material_requisition_list.html'
    context_object_name = 'requisitions'
    module_name = 'inventory'
    permission_type = 'view'
    paginate_by = 25

    def get_queryset(self):
        qs = ConsumableRequest.objects.filter(is_active=True, request_kind='material').select_related(
            'requested_by', 'department', 'project', 'warehouse'
        )
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs.order_by('-request_date', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Material Requisitions'
        ctx['status_filter'] = self.request.GET.get('status', '')
        ctx['status_choices'] = ConsumableRequest.STATUS_CHOICES
        return ctx


class MaterialRequisitionDetailView(PermissionRequiredMixin, DetailView):
    model = ConsumableRequest
    template_name = 'inventory/material_requisition_detail.html'
    context_object_name = 'req'
    module_name = 'inventory'
    permission_type = 'view'

    def get_queryset(self):
        return ConsumableRequest.objects.filter(is_active=True, request_kind='material').prefetch_related(
            'items__item', 'issue_events__lines', 'attachments'
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'MR {self.object.request_number}'
        ctx['can_edit'] = PermissionChecker.has_permission(self.request.user, 'inventory', 'edit')
        ctx['can_approve'] = PermissionChecker.has_permission(self.request.user, 'inventory', 'approve')
        ctx['warehouses'] = Warehouse.objects.filter(is_active=True, status='active')
        return ctx


@login_required
def material_requisition_create(request):
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:material_requisition_list')

    if request.method == 'POST':
        form = ConsumableRequestForm(request.POST)
        formset = ConsumableRequestItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            req = form.save(commit=False)
            req.request_kind = 'material'
            req.requested_by = request.user
            req.status = 'draft'
            req.save()
            formset.instance = req
            formset.save()
            req.recalculate_total()
            messages.success(request, f'MR {req.request_number} created.')
            return redirect('inventory:material_requisition_detail', pk=req.pk)
    else:
        form = ConsumableRequestForm()
        formset = ConsumableRequestItemFormSet()

    return render(request, 'inventory/material_requisition_form.html', {
        'title': 'New Material Requisition',
        'form': form,
        'formset': formset,
    })


@login_required
def material_requisition_submit(request, pk):
    req = get_object_or_404(ConsumableRequest, pk=pk, request_kind='material', is_active=True)
    try:
        submit_requisition(req, request.user)
        messages.success(request, f'MR {req.request_number} submitted.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('inventory:material_requisition_detail', pk=pk)


@login_required
def material_requisition_approve(request, pk):
    req = get_object_or_404(ConsumableRequest, pk=pk, request_kind='material', is_active=True)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:material_requisition_detail', pk=pk)
    wh_pk = request.POST.get('warehouse')
    warehouse = Warehouse.objects.filter(pk=wh_pk).first() if wh_pk else None
    try:
        approve_requisition(req, request.user, warehouse=warehouse)
        messages.success(request, f'MR {req.request_number} approved.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('inventory:material_requisition_detail', pk=pk)


@login_required
def material_requisition_issue(request, pk):
    req = get_object_or_404(ConsumableRequest, pk=pk, request_kind='material', is_active=True)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:material_requisition_detail', pk=pk)
    wh = get_object_or_404(Warehouse, pk=request.POST.get('warehouse'))
    line_qty = {
        int(k.replace('issue_', '')): request.POST.get(k)
        for k in request.POST
        if k.startswith('issue_') and request.POST.get(k)
    }
    try:
        issue_requisition(req, request.user, wh, line_qty, notes=request.POST.get('notes', ''))
        messages.success(request, f'Stock issued for MR {req.request_number}.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('inventory:material_requisition_detail', pk=pk)


@login_required
def material_requisition_reject(request, pk):
    req = get_object_or_404(ConsumableRequest, pk=pk, request_kind='material', is_active=True)
    try:
        reject_requisition(req, request.user, request.POST.get('reason', ''))
        messages.success(request, f'MR {req.request_number} rejected.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('inventory:material_requisition_detail', pk=pk)


@login_required
def material_requisition_close(request, pk):
    req = get_object_or_404(ConsumableRequest, pk=pk, request_kind='material', is_active=True)
    try:
        close_requisition(req, request.user)
        messages.success(request, f'MR {req.request_number} closed.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('inventory:material_requisition_detail', pk=pk)


class InterEntityTransferListView(PermissionRequiredMixin, ListView):
    model = InterEntityTransfer
    template_name = 'inventory/inter_entity_transfer_list.html'
    context_object_name = 'transfers'
    module_name = 'inventory'
    permission_type = 'view'
    paginate_by = 25

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Inter-entity Transfers'
        return ctx


class InterEntityTransferDetailView(PermissionRequiredMixin, DetailView):
    model = InterEntityTransfer
    template_name = 'inventory/inter_entity_transfer_detail.html'
    context_object_name = 'transfer'
    module_name = 'inventory'
    permission_type = 'view'

    def get_queryset(self):
        return InterEntityTransfer.objects.prefetch_related('lines__item').select_related(
            'source_entity', 'destination_entity', 'source_warehouse', 'destination_warehouse'
        )


@login_required
def inter_entity_reconciliation(request):
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    return render(request, 'inventory/inter_entity_reconciliation.html', {
        'title': 'Inter-entity Reconciliation',
        'rows': reconciliation_report(),
    })


@login_required
def inter_entity_transfer_action(request, pk, action):
    if request.method != 'POST':
        messages.error(request, 'Invalid request.')
        return redirect('inventory:inter_entity_transfer_detail', pk=pk)
    transfer = get_object_or_404(InterEntityTransfer, pk=pk)
    try:
        if action == 'approve_source':
            approve_transfer(transfer, request.user, 'source')
        elif action == 'issue':
            issue_transfer(transfer, request.user)
        elif action == 'receive':
            receive_transfer(transfer, request.user)
        messages.success(request, f'Transfer {transfer.transfer_number} updated.')
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect('inventory:inter_entity_transfer_detail', pk=pk)
