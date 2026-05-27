"""
CRM Views - Customer/Lead Management
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.urls import reverse_lazy
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.db.models import Q, Count
import json

from .models import Customer, CustomerPublicUpload, CrmLeadKanbanStage
from .forms import CustomerForm
from apps.core.visibility import crm_show_my_leads_label, filter_customers_for_user
from .utils import (
    annotate_latest_estimate_value,
    CRM_KANBAN_UNASSIGNED_THEME,
    CRM_KANBAN_WON_THEME,
    CRM_KANBAN_CUSTOMERS_THEME,
    CRM_KANBAN_STAGE_THEMES,
    kanban_theme_style,
    get_crm_project_queryset,
    get_sales_employee_queryset,
    project_choice_label,
    get_sales_employee_for_user,
    salesperson_display_name,
    user_can_access_customer,
)
from .activity import get_customer_activity_feed
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
        queryset = filter_customers_for_user(
            Customer.objects.select_related('assigned_salesperson', 'lead_kanban_stage'),
            self.request.user,
        )
        
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
        user = self.request.user
        sales_rep_only = crm_show_my_leads_label(user)
        context['crm_sales_rep_only'] = sales_rep_only
        context['title'] = 'My Leads & Customers' if sales_rep_only else 'Customers'
        context['form'] = CustomerForm(
            projects_queryset=get_crm_project_queryset(self.request.user),
            user=user,
        )
        context['salesman_choices'] = get_sales_employee_queryset()
        context['salesman_choice_options'] = [
            {'id': e.pk, 'label': salesperson_display_name(e)}
            for e in context['salesman_choices']
        ]
        default_emp = get_sales_employee_for_user(user)
        context['default_assigned_salesperson_id'] = default_emp.pk if default_emp else None
        context['show_assign_salesman'] = True
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'crm', 'create'
        )
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'crm', 'edit'
        )
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'crm', 'delete'
        )
        
        # Summary stats (scoped for sales reps)
        customers = filter_customers_for_user(Customer.objects.all(), user)
        context['total_customers'] = customers.count()
        context['active_customers'] = customers.filter(status='active').count()
        context['total_leads'] = customers.filter(customer_type='lead').count()
        context['prospects'] = customers.filter(status='prospect').count()
        context['project_choices'] = get_crm_project_queryset(self.request.user)
        context['crm_customer_type_choices'] = Customer.CUSTOMER_TYPE_CHOICES
        context['crm_status_choices'] = Customer.STATUS_CHOICES

        # Kanban board (leads pipeline + fixed customers column)
        board_stages = list(
            CrmLeadKanbanStage.objects.filter(
                is_active=True,
                converts_to_customer=False,
            ).order_by('sort_order', 'id')
        )
        context['crm_kanban_stages'] = board_stages
        context['crm_kanban_won_stage'] = (
            CrmLeadKanbanStage.objects.filter(
                is_active=True,
                converts_to_customer=True,
            ).first()
        )
        board_leads = annotate_latest_estimate_value(
            filter_customers_for_user(
                Customer.objects.filter(customer_type='lead', is_active=True)
                .select_related('lead_kanban_stage', 'assigned_salesperson'),
                user,
            )
        ).order_by('customer_number')
        leads_by_stage = {s.id: [] for s in board_stages}
        unassigned = []
        for lead in board_leads:
            sid = lead.lead_kanban_stage_id
            if sid and sid in leads_by_stage:
                leads_by_stage[sid].append(lead)
            else:
                unassigned.append(lead)
        context['kanban_lead_columns'] = [
            {
                'stage': s,
                'leads': leads_by_stage[s.id],
                'theme_style': kanban_theme_style(
                    CRM_KANBAN_STAGE_THEMES[i % len(CRM_KANBAN_STAGE_THEMES)]
                ),
            }
            for i, s in enumerate(board_stages)
        ]
        context['kanban_leads_unassigned'] = unassigned
        context['kanban_unassigned_style'] = kanban_theme_style(CRM_KANBAN_UNASSIGNED_THEME)
        context['kanban_won_style'] = kanban_theme_style(CRM_KANBAN_WON_THEME)
        context['kanban_customers_style'] = kanban_theme_style(CRM_KANBAN_CUSTOMERS_THEME)
        context['crm_show_customers_column'] = True
        context['kanban_customers'] = list(
            annotate_latest_estimate_value(
                filter_customers_for_user(
                    Customer.objects.filter(customer_type='customer', is_active=True)
                    .select_related('assigned_salesperson'),
                    user,
                )
            ).order_by('name', 'customer_number')[:400]
        )
        context['can_configure_kanban'] = (
            self.request.user.is_superuser
            or PermissionChecker.has_permission(self.request.user, 'settings', 'edit')
        )

        return context

    def post(self, request, *args, **kwargs):
        """Handle inline form submission."""
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'crm', 'create')):
            messages.error(request, 'You do not have permission to create customers.')
            return redirect('crm:customer_list')

        form = CustomerForm(
            request.POST,
            request.FILES,
            projects_queryset=get_crm_project_queryset(self.request.user),
            user=request.user,
        )
        if form.is_valid():
            customer = form.save(commit=False)
            customer.save()
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
def crm_project_options(request):
    """JSON list of projects for CRM customer form dropdowns."""
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'crm', 'view')
    ):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    projects = [
        {'id': p.pk, 'label': project_choice_label(p), 'name': p.name}
        for p in get_crm_project_queryset(self.request.user)
    ]
    return JsonResponse({'projects': projects})


@login_required
@require_POST
def crm_kanban_move(request):
    """JSON: move lead between pipeline stages, unassigned, or Won (converts to customer)."""
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'crm', 'edit')
    ):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    try:
        body = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    pk = body.get('customer_id')
    stage_raw = body.get('stage_id')

    if not pk:
        return JsonResponse({'error': 'customer_id required.'}, status=400)

    try:
        pk = int(pk)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid customer_id.'}, status=400)

    # Won / convert
    if stage_raw in ('won', '__won__', True):
        won = CrmLeadKanbanStage.objects.filter(
            is_active=True,
            converts_to_customer=True,
        ).first()
        if not won:
            return JsonResponse(
                {'error': 'No “Won” stage configured. Add one under Settings → CRM Kanban.'},
                status=400,
            )
        cust = Customer.objects.filter(
            pk=pk,
            customer_type='lead',
            is_active=True,
        ).first()
        if not cust or not user_can_access_customer(request.user, cust):
            return JsonResponse({'error': 'Lead not found.'}, status=404)
        cust.customer_type = 'customer'
        cust.lead_kanban_stage = None
        cust.save()
        log_action(
            request.user,
            'update',
            'Customer',
            cust.id,
            {'action': 'kanban_won', 'converted_to_customer': True},
        )
        return JsonResponse({'ok': True, 'converted': True})

    cust = Customer.objects.filter(pk=pk, is_active=True).first()
    if not cust or cust.customer_type != 'lead' or not user_can_access_customer(request.user, cust):
        return JsonResponse(
            {'error': 'Only active leads can be moved on the pipeline.'},
            status=400,
        )

    if stage_raw in (None, '', 0, '0', 'null', 'unassigned'):
        Customer.objects.filter(pk=pk).update(lead_kanban_stage=None)
        log_action(
            request.user,
            'update',
            'Customer',
            pk,
            {'lead_kanban_stage': 'unassigned'},
        )
        return JsonResponse({'ok': True})

    try:
        stage_id = int(stage_raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid stage_id.'}, status=400)

    stage = CrmLeadKanbanStage.objects.filter(
        pk=stage_id,
        is_active=True,
        converts_to_customer=False,
    ).first()
    if not stage:
        return JsonResponse({'error': 'Invalid pipeline stage.'}, status=400)

    cust.lead_kanban_stage = stage
    cust.save()
    log_action(
        request.user,
        'update',
        'Customer',
        pk,
        {'lead_kanban_stage': stage.slug},
    )
    return JsonResponse({'ok': True})


@never_cache
@require_http_methods(['GET', 'POST'])
def public_customer_upload(request):
    """
    Public (no login): select a lead or customer and attach files or photos.
    Files appear on that record's CRM detail page for staff.
    """
    base = Customer.objects.filter(is_active=True).order_by('customer_number')
    crm_leads = list(base.filter(customer_type='lead'))
    crm_customers = list(base.filter(customer_type='customer'))

    if request.method == 'POST':
        raw_id = request.POST.get('customer')
        note = (request.POST.get('note') or '').strip()[:500]
        if not raw_id or not str(raw_id).isdigit():
            messages.error(request, 'Please select a lead or customer.')
            return render(
                request,
                'crm/public_upload_form.html',
                {
                    'crm_leads': crm_leads,
                    'crm_customers': crm_customers,
                    'posted_note': note,
                },
                status=400,
            )
        cust = Customer.objects.filter(pk=int(raw_id), is_active=True).first()
        if not cust:
            messages.error(request, 'Invalid record.')
            return render(
                request,
                'crm/public_upload_form.html',
                {
                    'crm_leads': crm_leads,
                    'crm_customers': crm_customers,
                    'posted_note': note,
                },
                status=400,
            )
        files = request.FILES.getlist('files')
        if not files:
            messages.error(request, 'Please add at least one file or photo.')
            return render(
                request,
                'crm/public_upload_form.html',
                {
                    'crm_leads': crm_leads,
                    'crm_customers': crm_customers,
                    'selected_customer_id': cust.pk,
                    'posted_note': note,
                },
                status=400,
            )
        created = 0
        for f in files:
            if not f.name:
                continue
            CustomerPublicUpload.objects.create(
                customer=cust,
                file=f,
                original_filename=(getattr(f, 'name', '') or '')[:255],
                note=note,
            )
            created += 1
        if created == 0:
            messages.error(request, 'No files were saved. Try again.')
            return render(
                request,
                'crm/public_upload_form.html',
                {
                    'crm_leads': crm_leads,
                    'crm_customers': crm_customers,
                    'selected_customer_id': cust.pk,
                    'posted_note': note,
                },
                status=400,
            )
        type_label = 'Lead' if cust.customer_type == 'lead' else 'Customer'
        messages.success(
            request,
            f'Thank you. {created} file(s) were uploaded to {type_label} {cust.customer_number} — {cust.display_name}.',
        )
        return redirect('crm:public_upload')

    return render(
        request,
        'crm/public_upload_form.html',
        {'crm_leads': crm_leads, 'crm_customers': crm_customers},
    )


@login_required
def customer_inline_update(request, pk):
    """POST: update customer_type and/or status from list. One field per form."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    customer = get_object_or_404(Customer, pk=pk)
    if not user_can_access_customer(request.user, customer):
        messages.error(request, 'You do not have access to this lead.')
        return redirect('crm:customer_list')

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
        return filter_customers_for_user(
            Customer.objects.select_related(
                'primary_project', 'lead_kanban_stage', 'assigned_salesperson',
            ).prefetch_related('projects', 'public_uploads'),
            self.request.user,
        )
    
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
        context['public_uploads'] = (
            self.object.public_uploads.filter(is_active=True).order_by('-created_at')
        )
        context['customer_activity'] = get_customer_activity_feed(self.object)
        return context


class CustomerUpdateView(UpdatePermissionMixin, UpdateView):
    """Edit customer details."""
    model = Customer
    form_class = CustomerForm
    template_name = 'crm/customer_form.html'
    success_url = reverse_lazy('crm:customer_list')
    module_name = 'crm'

    def get_queryset(self):
        return filter_customers_for_user(
            Customer.objects.select_related('assigned_salesperson', 'primary_project'),
            self.request.user,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['projects_queryset'] = get_crm_project_queryset(self.request.user)
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Customer: {self.object.name}'
        context['project_choices'] = get_crm_project_queryset(self.request.user)
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

    def get_queryset(self):
        return filter_customers_for_user(Customer.objects.all(), self.request.user)
    
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
    if not user_can_access_customer(request.user, customer):
        messages.error(request, 'You do not have access to this lead.')
        return redirect('crm:customer_list')
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'crm', 'edit')):
        messages.error(request, 'You do not have permission to convert leads.')
        return redirect('crm:customer_list')
    
    if customer.customer_type == 'lead':
        customer.customer_type = 'customer'
        customer.lead_kanban_stage = None
        customer.save()
        log_action(request.user, 'update', 'Customer', customer.id, {
            'action': 'converted_to_customer',
            'old_type': 'lead',
            'new_type': 'customer'
        })
        messages.success(
            request,
            f'{customer.name} has been converted to a customer. Set B2B/B2C and any B2B documents on the next screen.',
        )
        return redirect('crm:customer_edit', pk=customer.pk)
    else:
        messages.info(request, f'{customer.name} is already a customer.')
    
    return redirect('crm:customer_list')

