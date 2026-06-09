"""Extended inventory views — Inter-entity transfers."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView

from apps.core.mixins import PermissionRequiredMixin
from apps.core.utils import PermissionChecker
from apps.inventory.models_inter_entity import InterEntityTransfer
from apps.inventory.services.inter_entity_service import (
    approve_transfer,
    issue_transfer,
    receive_transfer,
    reconciliation_report,
)


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
