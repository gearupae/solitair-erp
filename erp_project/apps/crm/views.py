"""
CRM Views - Customer/Lead Management
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.urls import reverse_lazy
from django.http import JsonResponse, HttpResponseNotAllowed
from django.db.models import Q, Count

from apps.projects.models import Project

from .models import Customer
from .forms import CustomerForm
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin, DeletePermissionMixin
from apps.core.utils import PermissionChecker
from apps.settings_app.models import AuditLog
from apps.core.middleware import get_current_request


def log_action(user, action, model, record_id, changes=None):
    """Log an action to the audit log."""
    request = get_current_request()
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0]
        else:
            ip_address = request.META.get('REMOTE_ADDR')
    
    AuditLog.objects.create(
        user=user,
        action=action,
        model=model,
        record_id=str(record_id),
        changes=changes or {},
        ip_address=ip_address
    )


class CustomerListView(PermissionRequiredMixin, ListView):
    """List all customers with inline create form."""
    model = Customer
    template_name = 'crm/customer_list.html'
    context_object_name = 'customers'
    module_name = 'crm'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Customer.objects.all()
        
        # Search
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(company__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search) |
                Q(customer_number__icontains=search) |
                Q(trn__icontains=search) |
                Q(website__icontains=search) |
                Q(job_type__icontains=search)
            )
        
        # Filter by type
        customer_type = self.request.GET.get('type')
        if customer_type:
            queryset = queryset.filter(customer_type=customer_type)
        
        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Customers'
        context['form'] = CustomerForm(
            projects_queryset=Project.objects.filter(is_active=True).order_by('name'),
        )
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'crm', 'create'
        )
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'crm', 'edit'
        )
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'crm', 'delete'
        )
        
        # Summary stats
        customers = Customer.objects.all()
        context['total_customers'] = customers.count()
        context['active_customers'] = customers.filter(status='active').count()
        context['total_leads'] = customers.filter(customer_type='lead').count()
        context['prospects'] = customers.filter(status='prospect').count()
        context['project_choices'] = Project.objects.filter(is_active=True).order_by('name')
        context['scope_choices'] = Customer.SCOPE_CHOICES
        context['crm_customer_type_choices'] = Customer.CUSTOMER_TYPE_CHOICES
        context['crm_status_choices'] = Customer.STATUS_CHOICES

        return context
    
    def post(self, request, *args, **kwargs):
        """Handle inline form submission."""
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'crm', 'create')):
            messages.error(request, 'You do not have permission to create customers.')
            return redirect('crm:customer_list')
        
        form = CustomerForm(
            request.POST,
            projects_queryset=Project.objects.filter(is_active=True).order_by('name'),
        )
        if form.is_valid():
            customer = form.save()
            log_action(request.user, 'create', 'Customer', customer.id, {
                'name': customer.name,
                'customer_number': customer.customer_number
            })
            messages.success(request, f'Customer {customer.name} created successfully.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        
        return redirect('crm:customer_list')


@login_required
def customer_inline_update(request, pk):
    """POST: update customer_type and/or status from list. One field per form."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    customer = get_object_or_404(Customer, pk=pk)

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'crm', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('crm:customer_list')

    next_url = request.POST.get('next', '').strip()
    updated = False

    if 'customer_type' in request.POST:
        val = request.POST['customer_type']
        if val in dict(Customer.CUSTOMER_TYPE_CHOICES) and customer.customer_type != val:
            customer.customer_type = val
            customer.save(update_fields=['customer_type'])
            log_action(request.user, 'update', 'Customer', customer.id, {'customer_type': val})
            updated = True

    if 'status' in request.POST:
        val = request.POST['status']
        if val in dict(Customer.STATUS_CHOICES) and customer.status != val:
            customer.status = val
            customer.save(update_fields=['status'])
            log_action(request.user, 'update', 'Customer', customer.id, {'status': val})
            updated = True

    if updated:
        messages.success(request, f'Customer {customer.name} updated.')

    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('crm:customer_detail', pk=pk)


class CustomerDetailView(PermissionRequiredMixin, DetailView):
    """View customer details."""
    model = Customer
    template_name = 'crm/customer_detail.html'
    context_object_name = 'customer'
    module_name = 'crm'
    permission_type = 'view'

    def get_queryset(self):
        return Customer.objects.select_related('primary_project').prefetch_related('projects')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Customer: {self.object.name}'
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'crm', 'edit'
        )
        # Inject customer advances for the advances tab
        try:
            from apps.advances.models import CustomerAdvance
            from apps.advances.forms import CustomerAdvanceForm
            from datetime import date
            context['customer_advances'] = CustomerAdvance.objects.filter(
                customer=self.object, is_active=True
            ).select_related('bank_account').order_by('-date')
            context['advance_form'] = CustomerAdvanceForm(initial={'date': date.today()})
        except Exception:
            context['customer_advances'] = []
            context['advance_form'] = None
        return context


class CustomerUpdateView(UpdatePermissionMixin, UpdateView):
    """Edit customer details."""
    model = Customer
    form_class = CustomerForm
    template_name = 'crm/customer_form.html'
    success_url = reverse_lazy('crm:customer_list')
    module_name = 'crm'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['projects_queryset'] = Project.objects.filter(is_active=True).order_by('name')
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Customer: {self.object.name}'
        context['project_choices'] = Project.objects.filter(is_active=True).order_by('name')
        return context
    
    def form_valid(self, form):
        # Track changes
        old_obj = Customer.objects.get(pk=self.object.pk)
        changes = {}
        for field in form.changed_data:
            changes[field] = {
                'old': str(getattr(old_obj, field)),
                'new': str(form.cleaned_data[field])
            }
        
        response = super().form_valid(form)
        
        log_action(self.request.user, 'update', 'Customer', self.object.id, changes)
        messages.success(self.request, f'Customer {self.object.name} updated successfully.')
        return response


class CustomerDeleteView(DeletePermissionMixin, DeleteView):
    """Delete customer (soft delete by setting is_active=False)."""
    model = Customer
    success_url = reverse_lazy('crm:customer_list')
    module_name = 'crm'
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        # Soft delete
        self.object.is_active = False
        self.object.save()
        
        log_action(request.user, 'delete', 'Customer', self.object.id, {
            'name': self.object.name,
            'action': 'soft_delete'
        })
        messages.success(request, f'Customer {self.object.name} has been deactivated.')
        return redirect(self.success_url)


@login_required
def convert_to_customer(request, pk):
    """Convert a lead to a customer."""
    customer = get_object_or_404(Customer, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'crm', 'edit')):
        messages.error(request, 'You do not have permission to convert leads.')
        return redirect('crm:customer_list')
    
    if customer.customer_type == 'lead':
        customer.customer_type = 'customer'
        customer.save()
        log_action(request.user, 'update', 'Customer', customer.id, {
            'action': 'converted_to_customer',
            'old_type': 'lead',
            'new_type': 'customer'
        })
        messages.success(request, f'{customer.name} has been converted to a customer.')
    else:
        messages.info(request, f'{customer.name} is already a customer.')
    
    return redirect('crm:customer_list')

