"""
Service Request views.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from datetime import date
from decimal import Decimal

from .models import ServiceRequest, ServiceRequestItem, ServiceRequestAttachment, ServiceOrder
from .forms import (
    ServiceRequestForm, ServiceRequestItemFormSet,
    ServiceRequestAttachmentForm, ServiceRequestRejectForm
)
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker


# ============ SERVICE REQUEST VIEWS ============

class ServiceRequestListView(PermissionRequiredMixin, ListView):
    model = ServiceRequest
    template_name = 'service_request/sr_list.html'
    context_object_name = 'service_requests'
    module_name = 'service_request'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = ServiceRequest.objects.filter(is_active=True).select_related(
            'requested_by', 'department'
        )
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(sr_number__icontains=search)
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Service Requests'
        context['status_choices'] = ServiceRequest.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'service_request', 'create'
        )
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'service_request', 'edit'
        )
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'service_request', 'delete'
        )
        context['can_approve'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'service_request', 'approve'
        )
        context['can_convert'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'service_request', 'edit'
        )
        context['today'] = date.today().isoformat()
        return context


class ServiceRequestCreateView(CreatePermissionMixin, CreateView):
    model = ServiceRequest
    form_class = ServiceRequestForm
    template_name = 'service_request/sr_form.html'
    success_url = reverse_lazy('service_request:sr_list')
    module_name = 'service_request'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Service Request'
        context['today'] = date.today().isoformat()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = ServiceRequestItemFormSet(self.request.POST)
            else:
                context['items_formset'] = ServiceRequestItemFormSet()
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        items_formset = ServiceRequestItemFormSet(request.POST)
        
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
        for f in self.request.FILES.getlist('attachments'):
            ServiceRequestAttachment.objects.create(
                service_request=self.object,
                file=f,
                filename=f.name,
                uploaded_by=self.request.user
            )
        messages.success(self.request, f'Service Request {self.object.sr_number} created.')
        return redirect(self.success_url)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class ServiceRequestUpdateView(UpdatePermissionMixin, UpdateView):
    model = ServiceRequest
    form_class = ServiceRequestForm
    template_name = 'service_request/sr_form.html'
    module_name = 'service_request'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit SR: {self.object.sr_number}'
        context['today'] = date.today().isoformat()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = ServiceRequestItemFormSet(
                    self.request.POST, instance=self.object
                )
            else:
                context['items_formset'] = ServiceRequestItemFormSet(instance=self.object)
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        items_formset = ServiceRequestItemFormSet(request.POST, instance=self.object)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_total()
        for f in self.request.FILES.getlist('attachments'):
            ServiceRequestAttachment.objects.create(
                service_request=self.object,
                file=f,
                filename=f.name,
                uploaded_by=self.request.user
            )
        messages.success(self.request, f'Service Request {self.object.sr_number} updated.')
        return redirect('service_request:sr_list')
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class ServiceRequestDetailView(PermissionRequiredMixin, DetailView):
    model = ServiceRequest
    template_name = 'service_request/sr_detail.html'
    context_object_name = 'sr'
    module_name = 'service_request'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'SR: {self.object.sr_number}'
        context['can_edit'] = (
            (self.request.user.is_superuser or
             PermissionChecker.has_permission(self.request.user, 'service_request', 'edit'))
            and (self.object.status in ['draft', 'returned'] or
                 (self.request.user.is_superuser and self.object.status == 'approved'))
        )
        context['can_submit'] = context['can_edit'] and self.object.status in ['draft', 'returned']
        context['can_approve'] = (
            self.request.user.is_superuser or
            PermissionChecker.has_permission(self.request.user, 'service_request', 'approve')
        ) and self.object.status == 'pending'
        context['can_reject'] = context['can_approve']
        context['can_return'] = context['can_approve']
        context['can_convert'] = (
            self.request.user.is_superuser or
            PermissionChecker.has_permission(self.request.user, 'service_request', 'edit')
        ) and self.object.status == 'approved'
        context['reject_form'] = ServiceRequestRejectForm()
        return context


@login_required
def sr_submit(request, pk):
    """Submit service request for approval."""
    sr = get_object_or_404(ServiceRequest, pk=pk)
    
    if sr.status not in ['draft', 'returned']:
        messages.error(request, 'Only draft or returned requests can be submitted.')
        return redirect('service_request:sr_detail', pk=pk)
    
    if sr.items.count() == 0:
        messages.error(request, 'Cannot submit without at least one service line item.')
        return redirect('service_request:sr_detail', pk=pk)
    
    sr.status = 'pending'
    sr.save()
    
    # Notify approver via approval config
    from apps.settings_app.models import ApprovalConfiguration
    ApprovalConfiguration.notify_approver(sr, 'service_request')
    
    # Notify requester
    from apps.settings_app.models import Notification
    Notification.create(
        user=sr.requested_by,
        title='Service Request Submitted',
        message=f'Your Service Request {sr.sr_number} has been submitted for approval.',
        link=f'/service-request/{sr.pk}/'
    )
    
    messages.success(request, f'Service Request {sr.sr_number} submitted for approval.')
    return redirect('service_request:sr_detail', pk=pk)


@login_required
def sr_approve(request, pk):
    sr = get_object_or_404(ServiceRequest, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'service_request', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('service_request:sr_list')
    
    if sr.status != 'pending':
        messages.error(request, 'Only pending requests can be approved.')
        return redirect('service_request:sr_detail', pk=pk)
    
    sr.status = 'approved'
    sr.rejection_reason = ''
    sr.save()
    
    from apps.settings_app.models import ApprovalAuditLog
    ApprovalAuditLog.objects.create(
        module='service_request',
        reference=sr.sr_number,
        approver=request.user,
        action='approve',
        comment=''
    )
    
    # Notify requester
    from apps.settings_app.models import Notification
    Notification.create(
        user=sr.requested_by,
        title='Service Request Approved',
        message=f'Service Request {sr.sr_number} has been approved.',
        link=f'/service-request/{sr.pk}/'
    )
    
    messages.success(request, f'SR {sr.sr_number} approved.')
    return redirect('service_request:sr_detail', pk=pk)


@login_required
def sr_reject(request, pk):
    sr = get_object_or_404(ServiceRequest, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'service_request', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('service_request:sr_list')
    
    if sr.status != 'pending':
        messages.error(request, 'Only pending requests can be rejected.')
        return redirect('service_request:sr_detail', pk=pk)
    
    if request.method == 'POST':
        form = ServiceRequestRejectForm(request.POST)
        if form.is_valid():
            sr.status = 'rejected'
            sr.rejection_reason = form.cleaned_data['comment']
            sr.save()
            
            from apps.settings_app.models import Notification, ApprovalAuditLog
            ApprovalAuditLog.objects.create(
                module='service_request',
                reference=sr.sr_number,
                approver=request.user,
                action='reject',
                comment=form.cleaned_data['comment']
            )
            
            Notification.create(
                user=sr.requested_by,
                title='Service Request Rejected',
                message=f'Service Request {sr.sr_number} has been rejected. Reason: {sr.rejection_reason[:100]}...',
                link=f'/service-request/{sr.pk}/'
            )
            
            messages.success(request, f'SR {sr.sr_number} rejected.')
            return redirect('service_request:sr_list')
    
    return redirect('service_request:sr_detail', pk=pk)


@login_required
def sr_return(request, pk):
    """Return for revision with comments."""
    sr = get_object_or_404(ServiceRequest, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'service_request', 'approve')):
        messages.error(request, 'Permission denied.')
        return redirect('service_request:sr_list')
    
    if sr.status != 'pending':
        messages.error(request, 'Only pending requests can be returned.')
        return redirect('service_request:sr_detail', pk=pk)
    
    if request.method == 'POST':
        form = ServiceRequestRejectForm(request.POST)
        if form.is_valid():
            sr.status = 'returned'
            sr.rejection_reason = form.cleaned_data['comment']
            sr.save()
            
            from apps.settings_app.models import Notification, ApprovalAuditLog
            ApprovalAuditLog.objects.create(
                module='service_request',
                reference=sr.sr_number,
                approver=request.user,
                action='return',
                comment=form.cleaned_data['comment']
            )
            Notification.create(
                user=sr.requested_by,
                title='Service Request Returned for Revision',
                message=f'Service Request {sr.sr_number} has been returned. Reason: {sr.rejection_reason[:100]}...',
                link=f'/service-request/{sr.pk}/edit/'
            )
            
            messages.success(request, f'SR {sr.sr_number} returned for revision.')
            return redirect('service_request:sr_list')
    
    return redirect('service_request:sr_detail', pk=pk)


@login_required
def sr_delete(request, pk):
    sr = get_object_or_404(ServiceRequest, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'service_request', 'delete'):
        sr.is_active = False
        sr.save()
        messages.success(request, f'SR {sr.sr_number} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('service_request:sr_list')


@login_required
def sr_convert(request, pk):
    """Redirect to PO create with SR pre-selected. User selects vendor on PO form (like PR conversion)."""
    sr = get_object_or_404(ServiceRequest, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'service_request', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('service_request:sr_list')
    
    if sr.status != 'approved':
        messages.error(request, 'Only approved requests can be converted.')
        return redirect('service_request:sr_detail', pk=pk)
    
    from django.urls import reverse
    url = reverse('purchase:po_create') + '?sr=' + str(sr.pk)
    return redirect(url)


@login_required
def sr_items_json(request, pk):
    """Return SR items as JSON for AJAX requests (used when creating PO from SR)."""
    sr = get_object_or_404(ServiceRequest, pk=pk)
    items = []
    for item in sr.items.all():
        items.append({
            'description': item.service_description,
            'quantity': str(item.quantity),
            'estimated_price': str(item.estimated_unit_cost),
            'unit_price': str(item.estimated_unit_cost),
        })
    return JsonResponse({'items': items})
