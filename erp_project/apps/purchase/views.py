"""
Purchase Views - Vendors, Purchase Requests, Purchase Orders, Vendor Bills, Expense Claims, Recurring Expenses
All purchase transactions post to accounting module as single source of truth.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse, reverse_lazy
from django.db.models import Q, Sum
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from datetime import date
from decimal import Decimal

from .models import (
    Vendor, PurchaseRequest, PurchaseRequestItem, PurchaseRequestAttachment,
    PurchaseOrder, PurchaseOrderItem, VendorBill, VendorBillItem,
    ExpenseClaim, ExpenseClaimItem, RecurringExpense, RecurringExpenseLog
)
from .forms import (
    VendorForm, PurchaseRequestForm, PurchaseRequestItemFormSet,
    PurchaseOrderForm, PurchaseOrderItemFormSet,
    VendorBillForm, VendorBillItemFormSet,
    ExpenseClaimForm, ExpenseClaimItemFormSet, ExpenseClaimPaymentForm,
    RecurringExpenseForm
)
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker


# ============ VENDOR VIEWS ============

class VendorListView(PermissionRequiredMixin, ListView):
    model = Vendor
    template_name = 'purchase/vendor_list.html'
    context_object_name = 'vendors'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Vendor.objects.filter(is_active=True)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(vendor_number__icontains=search) |
                Q(email__icontains=search)
            )
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Vendors'
        context['form'] = VendorForm()
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'delete')
        
        # Calculate metrics
        all_vendors = Vendor.objects.filter(is_active=True)
        context['total_vendors'] = all_vendors.count()
        context['active_vendors'] = all_vendors.filter(status='active').count()
        context['total_pos'] = PurchaseOrder.objects.filter(is_active=True, vendor__is_active=True).count()
        
        return context
    
    def post(self, request, *args, **kwargs):
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'create')):
            messages.error(request, 'Permission denied.')
            return redirect('purchase:vendor_list')
        
        form = VendorForm(request.POST)
        if form.is_valid():
            vendor = form.save()
            messages.success(request, f'Vendor {vendor.name} created successfully.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        return redirect('purchase:vendor_list')


class VendorUpdateView(UpdatePermissionMixin, UpdateView):
    model = Vendor
    form_class = VendorForm
    template_name = 'purchase/vendor_form.html'
    success_url = reverse_lazy('purchase:vendor_list')
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Vendor: {self.object.name}'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Vendor {form.instance.name} updated successfully.')
        return super().form_valid(form)


@login_required
def vendor_delete(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'delete'):
        vendor.is_active = False
        vendor.save()
        messages.success(request, f'Vendor {vendor.name} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('purchase:vendor_list')


# ============ PURCHASE REQUEST VIEWS ============

class PurchaseRequestListView(PermissionRequiredMixin, ListView):
    model = PurchaseRequest
    template_name = 'purchase/pr_list.html'
    context_object_name = 'purchase_requests'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = PurchaseRequest.objects.filter(is_active=True).select_related('requested_by')
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(pr_number__icontains=search)
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Purchase Requests'
        context['status_choices'] = PurchaseRequest.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'delete')
        context['can_approve'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'approve')
        context['can_convert'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['today'] = date.today().isoformat()
        return context


class PurchaseRequestCreateView(CreatePermissionMixin, CreateView):
    model = PurchaseRequest
    form_class = PurchaseRequestForm
    template_name = 'purchase/pr_form.html'
    success_url = reverse_lazy('purchase:pr_list')
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Purchase Request'
        context['today'] = date.today().isoformat()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = PurchaseRequestItemFormSet(self.request.POST)
            else:
                context['items_formset'] = PurchaseRequestItemFormSet()
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        items_formset = PurchaseRequestItemFormSet(request.POST)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        form.instance.requested_by = self.request.user
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_total()
        # Save attachments
        for f in self.request.FILES.getlist('attachments'):
            PurchaseRequestAttachment.objects.create(
                purchase_request=self.object,
                file=f,
                filename=f.name,
                uploaded_by=self.request.user
            )
        messages.success(self.request, f'Purchase Request {self.object.pr_number} created.')
        return redirect(self.success_url)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class PurchaseRequestUpdateView(UpdatePermissionMixin, UpdateView):
    model = PurchaseRequest
    form_class = PurchaseRequestForm
    template_name = 'purchase/pr_form.html'
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit PR: {self.object.pr_number}'
        context['today'] = date.today().isoformat()
        context['can_convert'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = PurchaseRequestItemFormSet(self.request.POST, instance=self.object)
            else:
                context['items_formset'] = PurchaseRequestItemFormSet(instance=self.object)
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        items_formset = PurchaseRequestItemFormSet(request.POST, instance=self.object)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_total()
        # Save new attachments
        for f in self.request.FILES.getlist('attachments'):
            PurchaseRequestAttachment.objects.create(
                purchase_request=self.object,
                file=f,
                filename=f.name,
                uploaded_by=self.request.user
            )
        messages.success(self.request, f'Purchase Request {self.object.pr_number} updated.')
        return redirect('purchase:pr_list')
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class PurchaseRequestDetailView(PermissionRequiredMixin, DetailView):
    model = PurchaseRequest
    template_name = 'purchase/pr_detail.html'
    context_object_name = 'pr'
    module_name = 'purchase'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'PR: {self.object.pr_number}'
        context['can_edit'] = (
            (self.request.user.is_superuser or
             PermissionChecker.has_permission(self.request.user, 'purchase', 'edit'))
            and (self.object.status in ['draft', 'returned'] or
                 (self.request.user.is_superuser and self.object.status == 'approved'))
        )
        context['can_submit'] = context['can_edit'] and self.object.status in ['draft', 'returned']
        context['can_approve'] = (
            self.request.user.is_superuser or
            PermissionChecker.has_permission(self.request.user, 'purchase', 'approve')
        ) and self.object.status == 'pending'
        context['can_reject'] = context['can_approve']
        context['can_return'] = context['can_approve']
        context['can_convert'] = (
            self.request.user.is_superuser or
            PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        ) and self.object.status == 'approved'
        return context


@login_required
def pr_submit(request, pk):
    """Submit purchase request for approval."""
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    
    if pr.status not in ['draft', 'returned']:
        messages.error(request, 'Only draft or returned requests can be submitted.')
        return redirect('purchase:pr_detail', pk=pk)
    
    if pr.items.count() == 0:
        messages.error(request, 'Cannot submit without at least one line item.')
        return redirect('purchase:pr_detail', pk=pk)
    
    pr.status = 'pending'
    pr.rejection_reason = ''
    pr.save()
    
    from apps.settings_app.models import ApprovalConfiguration
    ApprovalConfiguration.notify_approver(pr, 'purchase_request')
    
    from apps.settings_app.models import Notification
    Notification.create(
        user=pr.requested_by,
        title='Purchase Request Submitted',
        message=f'Your Purchase Request {pr.pr_number} has been submitted for approval.',
        link=f'/purchase/requests/{pr.pk}/'
    )
    
    messages.success(request, f'Purchase Request {pr.pr_number} submitted for approval.')
    return redirect('purchase:pr_detail', pk=pk)


@login_required
def pr_approve(request, pk):
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'approve'):
        pr.status = 'approved'
        pr.rejection_reason = ''
        pr.save()
        from apps.settings_app.models import ApprovalAuditLog
        ApprovalAuditLog.objects.create(
            module='purchase_request',
            reference=pr.pr_number,
            approver=request.user,
            action='approve',
            comment=''
        )
        from apps.settings_app.models import Notification
        Notification.create(
            user=pr.requested_by,
            title='Purchase Request Approved',
            message=f'Purchase Request {pr.pr_number} has been approved.',
            link=f'/purchase/requests/{pr.pk}/'
        )
        messages.success(request, f'PR {pr.pr_number} approved.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('purchase:pr_detail', pk=pk)


@login_required
def pr_reject(request, pk):
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:pr_list')
    if pr.status != 'pending':
        messages.error(request, 'Only pending requests can be rejected.')
        return redirect('purchase:pr_detail', pk=pk)
    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()
        pr.status = 'rejected'
        pr.rejection_reason = comment
        pr.save()
        from apps.settings_app.models import ApprovalAuditLog, Notification
        ApprovalAuditLog.objects.create(
            module='purchase_request',
            reference=pr.pr_number,
            approver=request.user,
            action='reject',
            comment=comment
        )
        Notification.create(
            user=pr.requested_by,
            title='Purchase Request Rejected',
            message=f'Purchase Request {pr.pr_number} has been rejected.' + (f' Reason: {comment[:100]}...' if comment else ''),
            link=f'/purchase/requests/{pr.pk}/'
        )
        messages.success(request, f'PR {pr.pr_number} rejected.')
        return redirect('purchase:pr_list')
    return redirect('purchase:pr_detail', pk=pk)


@login_required
def pr_return(request, pk):
    """Return purchase request for revision with comment."""
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:pr_list')
    if pr.status != 'pending':
        messages.error(request, 'Only pending requests can be returned.')
        return redirect('purchase:pr_detail', pk=pk)
    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()
        pr.status = 'returned'
        pr.rejection_reason = comment
        pr.save()
        from apps.settings_app.models import ApprovalAuditLog, Notification
        ApprovalAuditLog.objects.create(
            module='purchase_request',
            reference=pr.pr_number,
            approver=request.user,
            action='return',
            comment=comment
        )
        Notification.create(
            user=pr.requested_by,
            title='Purchase Request Returned for Revision',
            message=f'Purchase Request {pr.pr_number} has been returned for revision. {comment[:100]}{"..." if len(comment) > 100 else ""}',
            link=f'/purchase/requests/{pr.pk}/'
        )
        messages.success(request, f'PR {pr.pr_number} returned for revision.')
        return redirect('purchase:pr_list')
    return redirect('purchase:pr_detail', pk=pk)


@login_required
def pr_delete(request, pk):
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'delete'):
        pr.is_active = False
        pr.save()
        messages.success(request, f'PR {pr.pr_number} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('purchase:pr_list')


@login_required
def pr_convert(request, pk):
    """Redirect to PO create with PR pre-selected. Only for approved PRs."""
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:pr_list')
    if pr.status != 'approved':
        messages.error(request, 'Only approved Purchase Requests can be converted to Purchase Order.')
        return redirect('purchase:pr_detail', pk=pk)
    url = reverse('purchase:po_create') + '?pr=' + str(pr.pk)
    return redirect(url)


@login_required
def pr_items_json(request, pk):
    """Return PR items as JSON for AJAX requests."""
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    items = []
    for item in pr.items.all():
        items.append({
            'description': item.description,
            'quantity': str(item.quantity),
            'estimated_price': str(item.estimated_price),
            # Use estimated_price as unit_price, and default VAT to 5%
            'unit_price': str(item.estimated_price),
            'vat_rate': '5.00',
        })
    return JsonResponse({'items': items})


@login_required
def po_items_json(request, pk):
    """Return PO items as JSON for AJAX requests."""
    po = get_object_or_404(PurchaseOrder, pk=pk)
    items = []
    for item in po.items.all():
        items.append({
            'description': item.description,
            'quantity': str(item.quantity),
            'unit_price': str(item.unit_price),
            'vat_rate': str(item.vat_rate),
        })
    return JsonResponse({
        'items': items,
        'vendor_id': po.vendor.id if po.vendor else None
    })


# ============ PURCHASE ORDER VIEWS ============

class PurchaseOrderListView(PermissionRequiredMixin, ListView):
    model = PurchaseOrder
    template_name = 'purchase/po_list.html'
    context_object_name = 'purchase_orders'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = PurchaseOrder.objects.filter(is_active=True).select_related('vendor')
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(po_number__icontains=search) |
                Q(vendor__name__icontains=search)
            )
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Purchase Orders'
        context['status_choices'] = PurchaseOrder.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'delete')
        context['today'] = date.today().isoformat()
        
        # Calculate metrics
        all_pos = PurchaseOrder.objects.filter(is_active=True)
        context['total_pos'] = all_pos.count()
        context['total_amount'] = all_pos.aggregate(total=Sum('total_amount'))['total'] or 0
        context['pending_pos'] = all_pos.filter(status__in=['draft', 'sent']).count()
        context['confirmed_pos'] = all_pos.filter(status='confirmed').count()
        
        return context


class PurchaseOrderCreateView(CreatePermissionMixin, CreateView):
    model = PurchaseOrder
    form_class = PurchaseOrderForm
    template_name = 'purchase/po_form.html'
    success_url = reverse_lazy('purchase:po_list')
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Purchase Order'
        context['today'] = date.today().isoformat()
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        context['preselect_pr'] = self.request.GET.get('pr')
        context['preselect_sr'] = self.request.GET.get('sr')
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = PurchaseOrderItemFormSet(self.request.POST)
            else:
                context['items_formset'] = PurchaseOrderItemFormSet()
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        items_formset = PurchaseOrderItemFormSet(request.POST)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_totals()
        # When PO is created from PR, update PR status to converted
        if self.object.purchase_request:
            self.object.purchase_request.status = 'converted'
            self.object.purchase_request.save(update_fields=['status'])
        # When PO is created from SR, update SR status to converted
        if self.object.service_request:
            self.object.service_request.status = 'converted'
            self.object.service_request.save(update_fields=['status'])
        messages.success(self.request, f'Purchase Order {self.object.po_number} created.')
        return redirect(self.success_url)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class PurchaseOrderUpdateView(UpdatePermissionMixin, UpdateView):
    model = PurchaseOrder
    form_class = PurchaseOrderForm
    template_name = 'purchase/po_form.html'
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit PO: {self.object.po_number}'
        context['today'] = date.today().isoformat()
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = PurchaseOrderItemFormSet(self.request.POST, instance=self.object)
            else:
                context['items_formset'] = PurchaseOrderItemFormSet(instance=self.object)
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        items_formset = PurchaseOrderItemFormSet(request.POST, instance=self.object)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_totals()
        messages.success(self.request, f'Purchase Order {self.object.po_number} updated.')
        return redirect('purchase:po_detail', pk=self.object.pk)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class PurchaseOrderDetailView(PermissionRequiredMixin, DetailView):
    model = PurchaseOrder
    template_name = 'purchase/po_detail.html'
    context_object_name = 'po'
    module_name = 'purchase'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'PO: {self.object.po_number}'
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        return context


@login_required
def po_delete(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'delete'):
        po.is_active = False
        po.save()
        messages.success(request, f'PO {po.po_number} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('purchase:po_list')


# ============ VENDOR BILL VIEWS ============

class VendorBillListView(PermissionRequiredMixin, ListView):
    model = VendorBill
    template_name = 'purchase/bill_list.html'
    context_object_name = 'bills'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = VendorBill.objects.filter(is_active=True).select_related('vendor')
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(bill_number__icontains=search) |
                Q(vendor__name__icontains=search)
            )
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Vendor Bills'
        context['status_choices'] = VendorBill.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'delete')
        context['today'] = date.today().isoformat()
        
        # Summary
        bills = self.get_queryset()
        context['total_billed'] = bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['total_paid'] = bills.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
        context['total_outstanding'] = context['total_billed'] - context['total_paid']
        return context


class VendorBillCreateView(CreatePermissionMixin, CreateView):
    model = VendorBill
    form_class = VendorBillForm
    template_name = 'purchase/bill_form.html'
    success_url = reverse_lazy('purchase:bill_list')
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Vendor Bill'
        context['today'] = date.today().isoformat()
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = VendorBillItemFormSet(self.request.POST)
            else:
                context['items_formset'] = VendorBillItemFormSet()
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        items_formset = VendorBillItemFormSet(request.POST)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_totals()
        messages.success(self.request, f'Vendor Bill {self.object.bill_number} created.')
        return redirect(self.success_url)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class VendorBillUpdateView(UpdatePermissionMixin, UpdateView):
    """Edit a vendor bill - only draft bills can be edited."""
    model = VendorBill
    form_class = VendorBillForm
    template_name = 'purchase/bill_form.html'
    module_name = 'purchase'
    
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Block editing posted bills
        if obj.status != 'draft':
            messages.error(self.request, 'Posted bills cannot be edited. Only draft bills are editable.')
            return None
        return obj
    
    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object is None:
            return redirect('purchase:bill_list')
        return super().get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Bill: {self.object.bill_number}'
        context['today'] = date.today().isoformat()
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = VendorBillItemFormSet(self.request.POST, instance=self.object)
            else:
                context['items_formset'] = VendorBillItemFormSet(instance=self.object)
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object is None:
            return redirect('purchase:bill_list')
        form = self.get_form()
        items_formset = VendorBillItemFormSet(request.POST, instance=self.object)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_totals()
        messages.success(self.request, f'Vendor Bill {self.object.bill_number} updated.')
        return redirect('purchase:bill_detail', pk=self.object.pk)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class VendorBillDetailView(PermissionRequiredMixin, DetailView):
    model = VendorBill
    template_name = 'purchase/bill_detail.html'
    context_object_name = 'bill'
    module_name = 'purchase'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        from apps.core.audit import get_entity_audit_history
        
        context = super().get_context_data(**kwargs)
        context['title'] = f'Bill: {self.object.bill_number}'
        has_permission = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        # Only allow editing draft bills
        context['can_edit'] = has_permission and self.object.status == 'draft'
        # Allow posting draft bills
        context['can_post'] = has_permission and self.object.status == 'draft' and self.object.total_amount > 0
        
        # Audit History
        context['audit_history'] = get_entity_audit_history('Bill', self.object.pk)
        
        return context


@login_required
def bill_delete(request, pk):
    bill = get_object_or_404(VendorBill, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'delete'):
        bill.is_active = False
        bill.save()
        messages.success(request, f'Bill {bill.bill_number} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('purchase:bill_list')


@login_required
def bill_post(request, pk):
    """
    Post vendor bill to accounting - creates journal entry.
    Debit Expense, Debit VAT Recoverable, Credit AP
    """
    from apps.core.audit import audit_bill_post
    
    bill = get_object_or_404(VendorBill, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:bill_list')
    
    if bill.status != 'draft':
        messages.error(request, 'Only draft bills can be posted to accounting.')
        return redirect('purchase:bill_detail', pk=pk)
    
    try:
        journal = bill.post_to_accounting(user=request.user)
        # Audit log with IP address
        audit_bill_post(bill, request.user, request=request)
        messages.success(request, f'Bill {bill.bill_number} posted to accounting. Journal: {journal.entry_number}')
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f'Error posting bill: {e}')
    
    return redirect('purchase:bill_detail', pk=pk)


# ============ EXPENSE CLAIM VIEWS ============

class ExpenseClaimListView(PermissionRequiredMixin, ListView):
    """
    List all expense claims.
    Moved from Finance module to Purchase module.
    """
    model = ExpenseClaim
    template_name = 'purchase/expenseclaim_list.html'
    context_object_name = 'claims'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = ExpenseClaim.objects.filter(is_active=True).select_related('employee')
        
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(claim_number__icontains=search) |
                Q(employee__first_name__icontains=search) |
                Q(employee__last_name__icontains=search)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Expense Claims'
        context['status_choices'] = ExpenseClaim.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_approve'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'approve')
        context['today'] = date.today().isoformat()
        
        # Metrics
        all_claims = ExpenseClaim.objects.filter(is_active=True)
        context['total_claims'] = all_claims.count()
        context['pending_claims'] = all_claims.filter(status='submitted').count()
        context['approved_unpaid'] = all_claims.filter(status='approved').count()
        context['total_amount'] = all_claims.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        return context


class ExpenseClaimCreateView(CreatePermissionMixin, CreateView):
    """Create a new expense claim."""
    model = ExpenseClaim
    form_class = ExpenseClaimForm
    template_name = 'purchase/expenseclaim_form.html'
    success_url = reverse_lazy('purchase:expenseclaim_list')
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Expense Claim'
        context['today'] = date.today().isoformat()
        if self.request.POST:
            context['items_formset'] = ExpenseClaimItemFormSet(self.request.POST, self.request.FILES)
        else:
            context['items_formset'] = ExpenseClaimItemFormSet()
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        items_formset = context['items_formset']
        
        if items_formset.is_valid():
            form.instance.employee = self.request.user
            self.object = form.save()
            items_formset.instance = self.object
            items_formset.save()
            self.object.calculate_totals()
            messages.success(self.request, f'Expense Claim {self.object.claim_number} created.')
            return redirect(self.success_url)
        else:
            return self.render_to_response(context)


class ExpenseClaimDetailView(PermissionRequiredMixin, DetailView):
    """View expense claim details."""
    model = ExpenseClaim
    template_name = 'purchase/expenseclaim_detail.html'
    context_object_name = 'claim'
    module_name = 'purchase'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        from apps.core.audit import get_entity_audit_history
        
        context = super().get_context_data(**kwargs)
        context['title'] = f'Expense Claim: {self.object.claim_number}'
        
        # Permissions
        has_permission = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        can_approve = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'approve')
        
        context['can_submit'] = has_permission and self.object.status == 'draft'
        context['can_approve'] = can_approve and self.object.status == 'submitted'
        context['can_reject'] = can_approve and self.object.status == 'submitted'
        context['can_pay'] = has_permission and self.object.status == 'approved'
        
        # Payment form for approved claims
        if self.object.status == 'approved':
            context['payment_form'] = ExpenseClaimPaymentForm(initial={'payment_date': date.today()})
        
        # Audit History
        context['audit_history'] = get_entity_audit_history('ExpenseClaim', self.object.pk)
        
        return context


@login_required
def expenseclaim_submit(request, pk):
    """Submit expense claim for approval."""
    claim = get_object_or_404(ExpenseClaim, pk=pk)
    
    if claim.status != 'draft':
        messages.error(request, 'Only draft claims can be submitted.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    if claim.items.count() == 0:
        messages.error(request, 'Cannot submit claim without any expense items.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    claim.status = 'submitted'
    claim.save()
    messages.success(request, f'Expense Claim {claim.claim_number} submitted for approval.')
    return redirect('purchase:expenseclaim_detail', pk=pk)


@login_required
def expenseclaim_approve(request, pk):
    """
    Approve an expense claim and post to accounting.
    Creates journal entry: Dr Expense, Dr VAT Recoverable, Cr Employee Payable
    """
    from apps.core.audit import audit_expense_approve
    
    claim = get_object_or_404(ExpenseClaim, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    if claim.status != 'submitted':
        messages.error(request, 'Only submitted claims can be approved.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    claim.status = 'approved'
    claim.approved_by = request.user
    claim.approved_date = timezone.now()
    claim.save()
    
    # Post to accounting
    try:
        journal = claim.post_approval_journal(user=request.user)
        # Audit log with IP address
        audit_expense_approve(claim, request.user, request=request)
        messages.success(request, f'Expense Claim {claim.claim_number} approved and posted to accounting. Journal: {journal.entry_number}')
    except ValidationError as e:
        messages.warning(request, f'Claim approved but journal entry failed: {str(e)}')
    except Exception as e:
        messages.warning(request, f'Claim approved but journal entry failed: {str(e)}')
    
    return redirect('purchase:expenseclaim_detail', pk=pk)


@login_required
def expenseclaim_reject(request, pk):
    """Reject an expense claim."""
    claim = get_object_or_404(ExpenseClaim, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    if claim.status != 'submitted':
        messages.error(request, 'Only submitted claims can be rejected.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    reason = request.POST.get('rejection_reason', '')
    claim.status = 'rejected'
    claim.rejection_reason = reason
    claim.save()
    
    messages.success(request, f'Expense Claim {claim.claim_number} rejected.')
    return redirect('purchase:expenseclaim_detail', pk=pk)


@login_required
def expenseclaim_pay(request, pk):
    """
    Pay an approved expense claim.
    Creates journal entry: Dr Employee Payable, Cr Bank Account
    """
    claim = get_object_or_404(ExpenseClaim, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    if claim.status != 'approved':
        messages.error(request, 'Only approved claims can be paid.')
        return redirect('purchase:expenseclaim_detail', pk=pk)
    
    if request.method == 'POST':
        form = ExpenseClaimPaymentForm(request.POST)
        if form.is_valid():
            try:
                journal = claim.post_payment_journal(
                    bank_account=form.cleaned_data['bank_account'],
                    payment_date=form.cleaned_data['payment_date'],
                    reference=form.cleaned_data['payment_reference'],
                    user=request.user
                )
                messages.success(request, f'Expense Claim {claim.claim_number} paid. Journal: {journal.entry_number}')
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'Error processing payment: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    
    return redirect('purchase:expenseclaim_detail', pk=pk)


# ============ RECURRING EXPENSE VIEWS ============

class RecurringExpenseListView(PermissionRequiredMixin, ListView):
    """List all recurring expenses."""
    model = RecurringExpense
    template_name = 'purchase/recurringexpense_list.html'
    context_object_name = 'recurring_expenses'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = RecurringExpense.objects.filter(is_active=True).select_related(
            'vendor', 'expense_account', 'bank_account'
        )
        
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(vendor__name__icontains=search)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Recurring Expenses'
        context['status_choices'] = RecurringExpense.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'delete')
        context['today'] = date.today()
        
        # Metrics
        all_recurring = RecurringExpense.objects.filter(is_active=True)
        context['total_recurring'] = all_recurring.count()
        context['active_recurring'] = all_recurring.filter(status='active').count()
        context['monthly_total'] = all_recurring.filter(
            status='active', frequency='monthly'
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        # Due this month
        today = date.today()
        context['due_this_month'] = all_recurring.filter(
            status='active',
            next_run_date__year=today.year,
            next_run_date__month=today.month
        ).count()
        
        return context


class RecurringExpenseCreateView(CreatePermissionMixin, CreateView):
    """Create a new recurring expense."""
    model = RecurringExpense
    form_class = RecurringExpenseForm
    template_name = 'purchase/recurringexpense_form.html'
    success_url = reverse_lazy('purchase:recurringexpense_list')
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Recurring Expense'
        context['today'] = date.today().isoformat()
        return context
    
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Recurring Expense "{self.object.name}" created.')
        return redirect(self.success_url)


class RecurringExpenseUpdateView(UpdatePermissionMixin, UpdateView):
    """Edit a recurring expense."""
    model = RecurringExpense
    form_class = RecurringExpenseForm
    template_name = 'purchase/recurringexpense_form.html'
    success_url = reverse_lazy('purchase:recurringexpense_list')
    module_name = 'purchase'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit: {self.object.name}'
        context['today'] = date.today().isoformat()
        return context
    
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Recurring Expense "{self.object.name}" updated.')
        return redirect(self.success_url)


class RecurringExpenseDetailView(PermissionRequiredMixin, DetailView):
    """View recurring expense details and execution history."""
    model = RecurringExpense
    template_name = 'purchase/recurringexpense_detail.html'
    context_object_name = 'recurring_expense'
    module_name = 'purchase'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Recurring Expense: {self.object.name}'
        context['logs'] = self.object.logs.all()[:20]  # Last 20 executions
        
        has_permission = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_edit'] = has_permission
        context['can_execute'] = has_permission and self.object.status == 'active'
        context['can_pause'] = has_permission and self.object.status == 'active'
        context['can_resume'] = has_permission and self.object.status == 'paused'
        
        return context


@login_required
def recurringexpense_delete(request, pk):
    """Soft delete a recurring expense."""
    expense = get_object_or_404(RecurringExpense, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'delete'):
        expense.is_active = False
        expense.save()
        messages.success(request, f'Recurring Expense "{expense.name}" deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('purchase:recurringexpense_list')


@login_required
def recurringexpense_execute(request, pk):
    """Manually execute a recurring expense (generate expense and journal entry)."""
    expense = get_object_or_404(RecurringExpense, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:recurringexpense_detail', pk=pk)
    
    if expense.status != 'active':
        messages.error(request, 'Only active recurring expenses can be executed.')
        return redirect('purchase:recurringexpense_detail', pk=pk)
    
    try:
        log = expense.execute(user=request.user)
        if log:
            if log.status == 'success':
                messages.success(request, f'Recurring expense executed successfully. Journal: {log.journal_entry.entry_number if log.journal_entry else "N/A"}')
            else:
                messages.warning(request, f'Execution failed: {log.error_message}')
        else:
            messages.info(request, 'Expense not due for execution or already completed.')
    except Exception as e:
        messages.error(request, f'Error executing recurring expense: {str(e)}')
    
    return redirect('purchase:recurringexpense_detail', pk=pk)


@login_required
def recurringexpense_pause(request, pk):
    """Pause a recurring expense."""
    expense = get_object_or_404(RecurringExpense, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:recurringexpense_detail', pk=pk)
    
    if expense.status != 'active':
        messages.error(request, 'Only active recurring expenses can be paused.')
        return redirect('purchase:recurringexpense_detail', pk=pk)
    
    expense.status = 'paused'
    expense.save()
    messages.success(request, f'Recurring Expense "{expense.name}" paused.')
    return redirect('purchase:recurringexpense_detail', pk=pk)


@login_required
def recurringexpense_resume(request, pk):
    """Resume a paused recurring expense."""
    expense = get_object_or_404(RecurringExpense, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:recurringexpense_detail', pk=pk)
    
    if expense.status != 'paused':
        messages.error(request, 'Only paused recurring expenses can be resumed.')
        return redirect('purchase:recurringexpense_detail', pk=pk)
    
    expense.status = 'active'
    expense.save()
    messages.success(request, f'Recurring Expense "{expense.name}" resumed.')
    return redirect('purchase:recurringexpense_detail', pk=pk)



# ============ PAYMENT VOUCHER FOR VENDOR BILL ============

@login_required
def bill_make_payment(request, pk):
    """
    Record payment made for a vendor bill.
    SAP/Oracle Standard: Payment creates clearing entry for AP.
    
    Dr Accounts Payable
    Cr Bank
    """
    from apps.finance.models import (
        Payment, BankAccount, JournalEntry, JournalEntryLine, 
        Account, AccountType, AccountMapping
    )
    from decimal import Decimal, InvalidOperation
    from datetime import date
    
    bill = get_object_or_404(VendorBill, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:bill_detail', pk=pk)
    
    # Bill must be posted first
    if bill.status == 'draft':
        messages.error(request, 'Bill must be posted to accounting before making payment.')
        return redirect('purchase:bill_detail', pk=pk)
    
    # Check if already fully paid
    if bill.balance <= 0:
        messages.error(request, 'Bill is already fully paid.')
        return redirect('purchase:bill_detail', pk=pk)
    
    if request.method == 'POST':
        # Get payment details
        amount = request.POST.get('amount')
        payment_method = request.POST.get('payment_method', 'bank')
        bank_account_id = request.POST.get('bank_account')
        payment_date = request.POST.get('payment_date')
        reference = request.POST.get('reference', '')
        
        try:
            amount = Decimal(amount)
            if amount <= 0:
                raise ValueError("Amount must be positive")
            if amount > bill.balance:
                messages.warning(request, f'Amount exceeds balance. Adjusted to {bill.balance}')
                amount = bill.balance
        except (ValueError, InvalidOperation) as e:
            messages.error(request, f'Invalid amount: {e}')
            return redirect('purchase:bill_detail', pk=pk)
        
        # Get bank account
        bank_account = None
        if payment_method == 'bank' and bank_account_id:
            bank_account = BankAccount.objects.filter(pk=bank_account_id, is_active=True).first()
            if not bank_account:
                messages.error(request, 'Invalid bank account selected.')
                return redirect('purchase:bill_detail', pk=pk)
        elif payment_method == 'bank':
            # Use default bank account
            bank_account = BankAccount.objects.filter(is_active=True).first()
        
        if payment_method == 'bank' and not bank_account:
            messages.error(request, 'Bank account is required for bank transfer payments.')
            return redirect('purchase:bill_detail', pk=pk)
        
        # Parse payment date
        from datetime import datetime
        try:
            if payment_date:
                payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
            else:
                payment_date = date.today()
        except ValueError:
            payment_date = date.today()
        
        # Create Payment record
        payment = Payment.objects.create(
            payment_type='made',
            payment_method=payment_method,
            payment_date=payment_date,
            party_type='vendor',
            party_id=bill.vendor_id,
            party_name=bill.vendor.name,
            amount=amount,
            reference=reference or bill.bill_number,
            bank_account=bank_account,
            status='draft',
        )
        
        # Get accounts using Account Mapping
        ap_account = AccountMapping.get_account_or_default('vendor_payment_ap_clear', '2000')
        if not ap_account:
            ap_account = Account.objects.filter(
                account_type=AccountType.LIABILITY, is_active=True, name__icontains='payable'
            ).first()
        
        if not ap_account:
            messages.error(request, 'Accounts Payable account not configured.')
            return redirect('purchase:bill_detail', pk=pk)
        
        # Get bank GL account
        if payment_method == 'bank' and bank_account and bank_account.gl_account:
            bank_gl_account = bank_account.gl_account
        else:
            # Use cash account for cash payments
            bank_gl_account = Account.objects.filter(
                account_type=AccountType.ASSET, is_active=True, name__icontains='cash'
            ).first()
            if not bank_gl_account:
                bank_gl_account = Account.objects.filter(
                    account_type=AccountType.ASSET, is_active=True
                ).first()
        
        if not bank_gl_account:
            messages.error(request, 'Bank/Cash account not configured.')
            return redirect('purchase:bill_detail', pk=pk)
        
        # Create journal entry: Dr AP, Cr Bank
        journal = JournalEntry.objects.create(
            date=payment_date,
            reference=payment.payment_number,
            description=f"Payment Voucher: {bill.bill_number} - {bill.vendor.name}",
            entry_type='standard',
            source_module='payment',
        )
        
        # Debit Accounts Payable (clears liability)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f"AP Clearing - {bill.bill_number}",
            debit=amount,
            credit=Decimal('0.00'),
        )
        
        # Credit Bank/Cash
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_gl_account,
            description=f"Payment to {bill.vendor.name}",
            debit=Decimal('0.00'),
            credit=amount,
        )
        
        journal.calculate_totals()
        
        try:
            journal.post(request.user)
            payment.journal_entry = journal
            payment.status = 'confirmed'
            payment.allocated_amount = amount
            payment.save()
            
            # Update bill
            bill.paid_amount += amount
            if bill.paid_amount >= bill.total_amount:
                bill.status = 'paid'
            else:
                bill.status = 'partial'
            bill.save()
            
            messages.success(request, f'Payment of AED {amount:,.2f} recorded. Voucher: {payment.payment_number}')
        except Exception as e:
            journal.delete()
            payment.delete()
            messages.error(request, f'Error posting payment: {e}')
        
        return redirect('purchase:bill_detail', pk=pk)
    
    # GET - Show payment form
    bank_accounts = BankAccount.objects.filter(is_active=True)
    context = {
        'title': f'Make Payment - {bill.bill_number}',
        'bill': bill,
        'bank_accounts': bank_accounts,
        'today': date.today().strftime('%Y-%m-%d'),
    }
    return render(request, 'purchase/bill_make_payment.html', context)
