"""
Sales Views - Estimates and Invoices
Invoices post to accounting module as single source of truth.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse, reverse_lazy
from django.db.models import Q, Sum, Prefetch
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from datetime import date
from decimal import Decimal, InvalidOperation
import json

from .models import Estimate, EstimateItem, Invoice, InvoiceItem
from .forms import EstimateForm, EstimateItemFormSet, InvoiceForm, InvoiceItemFormSet
from apps.crm.models import Customer
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.notification_utils import notify_if_new_assignee
from apps.core.utils import PermissionChecker


@login_required
def estimate_items_sample_csv(request):
    """Download CSV template for estimate line items (inventory item_code + pricing fields)."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'create')):
        return HttpResponseForbidden('Permission denied.')
    from .estimate_csv import sample_csv_content

    response = HttpResponse(sample_csv_content(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="estimate_line_items_sample.csv"'
    return response


# ============ ESTIMATE VIEWS ============

class EstimateListView(PermissionRequiredMixin, ListView):
    """List all estimates."""
    model = Estimate
    template_name = 'sales/estimate_list.html'
    context_object_name = 'estimates'
    module_name = 'sales'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Estimate.objects.filter(is_active=True).select_related('customer')
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(estimate_number__icontains=search) |
                Q(customer__name__icontains=search)
            )
        
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Estimates'
        context['customers'] = Customer.objects.filter(is_active=True)
        context['status_choices'] = Estimate.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'create'
        )
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'edit'
        )
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'delete'
        )
        context['today'] = date.today().isoformat()
        
        # Summary stats
        estimates = self.get_queryset()
        context['total_estimates'] = estimates.count()
        context['total_amount'] = estimates.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['approved_amount'] = estimates.filter(status='approved').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['pending_count'] = estimates.filter(status__in=['draft', 'sent', 'pending']).count()
        
        return context


class EstimateCreateView(CreatePermissionMixin, CreateView):
    """Create a new estimate."""
    model = Estimate
    form_class = EstimateForm
    template_name = 'sales/estimate_form.html'
    success_url = reverse_lazy('sales:estimate_list')
    module_name = 'sales'

    def get_initial(self):
        from apps.settings_app.models import CompanySettings
        initial = super().get_initial()
        cs = CompanySettings.get_settings()
        initial['assigned_to'] = self.request.user.pk
        u = self.request.user
        initial['prepared_by'] = (u.get_full_name() or '').strip() or u.username
        if cs.estimate_default_client_note:
            initial['client_note'] = cs.estimate_default_client_note
        if cs.estimate_default_terms:
            initial['terms_and_conditions'] = cs.estimate_default_terms
        return initial
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        from apps.inventory.models import Item
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Estimate'
        context['today'] = date.today().isoformat()
        context['scope_choices'] = Estimate.SCOPE_CHOICES
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        rows = list(
            Item.objects.filter(is_active=True, status='active')
            .values('id', 'item_code', 'name', 'selling_price', 'tax_code_id')[:2000]
        )
        context['inventory_items_json'] = json.dumps(rows, cls=DjangoJSONEncoder)
        context['estimate_items_sample_csv_url'] = reverse('sales:estimate_items_sample_csv')
        context['inventory_items_export_csv_url'] = reverse('inventory:item_export_csv')
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = EstimateItemFormSet(
                    self.request.POST, self.request.FILES, prefix='items'
                )
            else:
                context['items_formset'] = EstimateItemFormSet(prefix='items')
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = None
        csv_file = request.FILES.get('items_csv')
        if csv_file and getattr(csv_file, 'size', 0) > 0:
            from .estimate_csv import bulk_create_estimate_items, parse_estimate_items_csv

            form = self.get_form()
            if form.is_valid():
                try:
                    rows = parse_estimate_items_csv(csv_file)
                except ValueError as e:
                    messages.error(request, str(e))
                    items_formset = EstimateItemFormSet(request.POST, request.FILES, prefix='items')
                    return self.form_invalid(form, items_formset)
                self.object = form.save()
                bulk_create_estimate_items(self.object, rows, replace_existing=False)
                messages.success(request, f'Estimate {self.object.estimate_number} created successfully.')
                est = self.object
                link = reverse('sales:estimate_detail', kwargs={'pk': est.pk})
                notify_if_new_assignee(
                    est.assigned_to,
                    request.user,
                    f'Estimate assigned: {est.estimate_number}',
                    f'{est.customer.name} — {est.estimate_number}' if est.customer else est.estimate_number,
                    link,
                )
                return redirect(self.success_url)
            items_formset = EstimateItemFormSet(request.POST, request.FILES, prefix='items')
            return self.form_invalid(form, items_formset)

        form = self.get_form()
        items_formset = EstimateItemFormSet(request.POST, request.FILES, prefix='items')

        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_totals()
        messages.success(self.request, f'Estimate {self.object.estimate_number} created successfully.')
        est = self.object
        link = reverse('sales:estimate_detail', kwargs={'pk': est.pk})
        notify_if_new_assignee(
            est.assigned_to,
            self.request.user,
            f'Estimate assigned: {est.estimate_number}',
            f'{est.customer.name} — {est.estimate_number}' if est.customer else est.estimate_number,
            link,
        )
        return redirect(self.success_url)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class EstimateUpdateView(UpdatePermissionMixin, UpdateView):
    """Edit an estimate."""
    model = Estimate
    form_class = EstimateForm
    template_name = 'sales/estimate_form.html'
    module_name = 'sales'
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        from apps.inventory.models import Item
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Estimate: {self.object.estimate_number}'
        context['today'] = date.today().isoformat()
        context['scope_choices'] = Estimate.SCOPE_CHOICES
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        rows = list(
            Item.objects.filter(is_active=True, status='active')
            .values('id', 'item_code', 'name', 'selling_price', 'tax_code_id')[:2000]
        )
        context['inventory_items_json'] = json.dumps(rows, cls=DjangoJSONEncoder)
        context['estimate_items_sample_csv_url'] = reverse('sales:estimate_items_sample_csv')
        context['inventory_items_export_csv_url'] = reverse('inventory:item_export_csv')
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = EstimateItemFormSet(
                    self.request.POST, self.request.FILES, instance=self.object, prefix='items'
                )
            else:
                context['items_formset'] = EstimateItemFormSet(instance=self.object, prefix='items')
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        csv_file = request.FILES.get('items_csv')
        if csv_file and getattr(csv_file, 'size', 0) > 0:
            from .estimate_csv import bulk_create_estimate_items, parse_estimate_items_csv

            form = self.get_form()
            if form.is_valid():
                try:
                    rows = parse_estimate_items_csv(csv_file)
                except ValueError as e:
                    messages.error(request, str(e))
                    items_formset = EstimateItemFormSet(
                        request.POST, request.FILES, instance=self.object, prefix='items'
                    )
                    return self.form_invalid(form, items_formset)
                old_assignee_id = self.object.assigned_to_id
                self.object = form.save()
                bulk_create_estimate_items(self.object, rows, replace_existing=True)
                messages.success(request, f'Estimate {self.object.estimate_number} updated successfully.')
                est = self.object
                if est.assigned_to_id and est.assigned_to_id != old_assignee_id:
                    link = reverse('sales:estimate_detail', kwargs={'pk': est.pk})
                    notify_if_new_assignee(
                        est.assigned_to,
                        request.user,
                        f'Estimate assigned to you: {est.estimate_number}',
                        f'{est.customer.name} — reassigned by {request.user.get_full_name() or request.user.username}'
                        if est.customer
                        else est.estimate_number,
                        link,
                    )
                return redirect('sales:estimate_detail', pk=self.object.pk)
            items_formset = EstimateItemFormSet(request.POST, request.FILES, instance=self.object, prefix='items')
            return self.form_invalid(form, items_formset)

        form = self.get_form()
        items_formset = EstimateItemFormSet(request.POST, request.FILES, instance=self.object, prefix='items')

        form_valid = form.is_valid()
        formset_valid = items_formset.is_valid()

        if not form_valid:
            messages.error(request, f'Form errors: {form.errors}')
        if not formset_valid:
            messages.error(request, f'Formset errors: {items_formset.errors}')
            if items_formset.non_form_errors():
                messages.error(request, f'Formset non-form errors: {items_formset.non_form_errors()}')

        if form_valid and formset_valid:
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        old_assignee_id = self.object.assigned_to_id
        # Save the main form first
        self.object = form.save()
        # Then save the formset with the instance
        items_formset.instance = self.object
        items_formset.save()
        # Recalculate totals
        self.object.calculate_totals()
        # Refresh from database to ensure we have latest data
        self.object.refresh_from_db()
        messages.success(self.request, f'Estimate {self.object.estimate_number} updated successfully.')
        est = self.object
        if est.assigned_to_id and est.assigned_to_id != old_assignee_id:
            link = reverse('sales:estimate_detail', kwargs={'pk': est.pk})
            notify_if_new_assignee(
                est.assigned_to,
                self.request.user,
                f'Estimate assigned to you: {est.estimate_number}',
                f'{est.customer.name} — reassigned by {self.request.user.get_full_name() or self.request.user.username}'
                if est.customer
                else est.estimate_number,
                link,
            )
        return redirect('sales:estimate_detail', pk=self.object.pk)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class EstimateDetailView(PermissionRequiredMixin, DetailView):
    """View estimate details."""
    model = Estimate
    template_name = 'sales/estimate_detail.html'
    context_object_name = 'estimate'
    module_name = 'sales'
    permission_type = 'view'

    def get_queryset(self):
        items_qs = EstimateItem.objects.select_related('inventory_item', 'tax_code').order_by('sort_order', 'id')
        return Estimate.objects.select_related(
            'customer', 'assigned_to', 'project', 'created_by', 'updated_by',
        ).prefetch_related(Prefetch('items', queryset=items_qs))
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Estimate: {self.object.estimate_number}'
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'edit'
        )
        return context


@login_required
def estimate_delete(request, pk):
    """Soft delete an estimate."""
    estimate = get_object_or_404(Estimate, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'delete'):
        estimate.is_active = False
        estimate.save()
        messages.success(request, f'Estimate {estimate.estimate_number} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('sales:estimate_list')


@login_required
def estimate_update_status(request, pk, status):
    """Update estimate status."""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('sales:estimate_detail', pk=pk)
    
    estimate = get_object_or_404(Estimate, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_detail', pk=pk)
    
    valid_statuses = ['draft', 'sent', 'approved', 'rejected', 'expired']
    if status not in valid_statuses:
        messages.error(request, 'Invalid status.')
        return redirect('sales:estimate_detail', pk=pk)
    
    old_status = estimate.status
    estimate.status = status
    estimate.save()
    
    status_display = dict(Estimate.STATUS_CHOICES).get(status, status)
    messages.success(request, f'Estimate {estimate.estimate_number} status updated to {status_display}.')
    
    return redirect('sales:estimate_detail', pk=pk)


@login_required
def estimate_convert_to_invoice(request, pk):
    """Convert approved estimate to invoice."""
    estimate = get_object_or_404(Estimate, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_list')
    
    # Create invoice from estimate
    invoice = Invoice.objects.create(
        estimate=estimate,
        customer=estimate.customer,
        invoice_date=date.today(),
        due_date=date.today(),
        status='draft',
        notes=estimate.notes,
    )
    
    # Copy items (use final rate as invoice unit price)
    for item in estimate.items.all():
        InvoiceItem.objects.create(
            invoice=invoice,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.rate,
            tax_code=item.tax_code,
            vat_rate=item.vat_rate,
            is_vat_inclusive=item.is_vat_inclusive,
        )
    
    invoice.calculate_totals()
    messages.success(request, f'Invoice {invoice.invoice_number} created from estimate.')
    link = reverse('sales:invoice_edit', kwargs={'pk': invoice.pk})
    notify_if_new_assignee(
        estimate.assigned_to,
        request.user,
        f'Invoice from estimate: {invoice.invoice_number}',
        f'{estimate.estimate_number} → {invoice.invoice_number} for {estimate.customer.name}'
        if estimate.customer
        else invoice.invoice_number,
        link,
    )
    return redirect('sales:invoice_edit', pk=invoice.pk)


def _build_estimate_pdf_context(request, estimate):
    """
    Shared context for proposal and proforma invoice HTML (print/PDF).
    Caller adds document_heading, document_number, print_button_label, page_title.
    """
    from apps.settings_app.models import CompanySettings

    company = CompanySettings.get_settings()

    def number_to_words(n):
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
                'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

        if n < 20:
            return ones[n]
        if n < 100:
            return tens[n // 10] + ('' if n % 10 == 0 else ' ' + ones[n % 10])
        if n < 1000:
            return ones[n // 100] + ' Hundred' + ('' if n % 100 == 0 else ' and ' + number_to_words(n % 100))
        if n < 1000000:
            return number_to_words(n // 1000) + ' Thousand' + ('' if n % 1000 == 0 else ' ' + number_to_words(n % 1000))
        if n < 1000000000:
            return number_to_words(n // 1000000) + ' Million' + ('' if n % 1000000 == 0 else ' ' + number_to_words(n % 1000000))
        return str(n)

    try:
        amount_whole = int(estimate.total_amount)
        amount_decimal = int((estimate.total_amount - amount_whole) * 100)
        amount_words = number_to_words(amount_whole)
        if amount_decimal > 0:
            amount_words += f" and {amount_decimal}/100"
        amount_words += " Dirhams Only"
    except Exception:
        amount_words = ""

    vat_summary = {}
    for item in estimate.items.all():
        rate = float(item.vat_rate)
        if rate not in vat_summary:
            vat_summary[rate] = {'taxable': 0, 'vat': 0}
        vat_summary[rate]['taxable'] += float(item.total)
        vat_summary[rate]['vat'] += float(item.vat_amount)

    logo_absolute_url = ''
    if company.logo:
        logo_absolute_url = request.build_absolute_uri(company.logo.url)

    authorized_signature_url = ''
    if estimate.authorized_signature:
        authorized_signature_url = request.build_absolute_uri(estimate.authorized_signature.url)
    customer_signature_url = ''
    if estimate.customer_signature:
        customer_signature_url = request.build_absolute_uri(estimate.customer_signature.url)

    return {
        'estimate': estimate,
        'company': company,
        'logo_absolute_url': logo_absolute_url,
        'authorized_signature_url': authorized_signature_url,
        'customer_signature_url': customer_signature_url,
        'amount_words': amount_words,
        'vat_summary': vat_summary,
        'is_pdf': True,
    }


@login_required
def estimate_pdf(request, pk):
    """
    Proposal PDF (HTML for print): same layout as proforma, different heading and document number.
    """
    items_qs = EstimateItem.objects.select_related('inventory_item', 'tax_code').order_by('sort_order', 'id')
    estimate = get_object_or_404(
        Estimate.objects.select_related('customer', 'assigned_to', 'project').prefetch_related(
            Prefetch('items', queryset=items_qs)
        ),
        pk=pk,
    )

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_list')

    context = _build_estimate_pdf_context(request, estimate)
    context.update({
        'document_heading': 'PROPOSAL',
        'document_number': estimate.estimate_number,
        'page_title': f'Proposal — {estimate.estimate_number}',
        'print_button_label': 'Print proposal',
        'show_pdf_status': True,
    })
    return render(request, 'sales/estimate_pdf.html', context)


@login_required
def estimate_proforma_pdf(request, pk):
    """Proforma invoice: same template as proposal; document number PI-{estimate_number}."""
    items_qs = EstimateItem.objects.select_related('inventory_item', 'tax_code').order_by('sort_order', 'id')
    estimate = get_object_or_404(
        Estimate.objects.select_related('customer', 'assigned_to', 'project').prefetch_related(
            Prefetch('items', queryset=items_qs)
        ),
        pk=pk,
    )

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_list')

    proforma_number = f'PI-{estimate.estimate_number}'
    context = _build_estimate_pdf_context(request, estimate)
    context.update({
        'document_heading': 'PROFORMA INVOICE',
        'document_number': proforma_number,
        'page_title': f'Proforma invoice — {proforma_number}',
        'print_button_label': 'Print proforma invoice',
        'show_pdf_status': False,
    })
    return render(request, 'sales/estimate_pdf.html', context)


@login_required
def estimate_set_status(request, pk):
    """POST: update estimate status from list (inline). Fields: status, next (optional relative URL)."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    estimate = get_object_or_404(Estimate, pk=pk)

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_list')

    status = request.POST.get('status')
    valid_statuses = [c[0] for c in Estimate.STATUS_CHOICES]
    if status not in valid_statuses:
        messages.error(request, 'Invalid status.')
        return redirect('sales:estimate_list')

    estimate.status = status
    estimate.save()

    status_display = dict(Estimate.STATUS_CHOICES).get(status, status)
    messages.success(request, f'Estimate {estimate.estimate_number} status updated to {status_display}.')

    next_url = request.POST.get('next', '').strip()
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('sales:estimate_detail', pk=pk)


@login_required
def inventory_item_json(request, pk):
    """JSON for populating estimate line from inventory item."""
    from apps.inventory.models import Item
    item = get_object_or_404(
        Item.objects.filter(is_active=True, status='active'),
        pk=pk,
    )
    return JsonResponse({
        'id': item.pk,
        'item_code': item.item_code,
        'name': item.name,
        'description': item.description or '',
        'selling_price': str(item.selling_price),
        'tax_code_id': item.tax_code_id,
    })


# ============ INVOICE VIEWS ============

class InvoiceListView(PermissionRequiredMixin, ListView):
    """List all invoices."""
    model = Invoice
    template_name = 'sales/invoice_list.html'
    context_object_name = 'invoices'
    module_name = 'sales'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Invoice.objects.filter(is_active=True).select_related('customer', 'estimate')
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(customer__name__icontains=search)
            )
        
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Invoices'
        context['customers'] = Customer.objects.filter(is_active=True)
        context['status_choices'] = Invoice.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'create'
        )
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'edit'
        )
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'delete'
        )
        context['today'] = date.today().isoformat()
        
        # Summary stats
        invoices = self.get_queryset()
        context['total_invoiced'] = invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['total_paid'] = invoices.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
        context['total_outstanding'] = context['total_invoiced'] - context['total_paid']
        
        return context


class InvoiceCreateView(CreatePermissionMixin, CreateView):
    """Create a new invoice."""
    model = Invoice
    form_class = InvoiceForm
    template_name = 'sales/invoice_form.html'
    success_url = reverse_lazy('sales:invoice_list')
    module_name = 'sales'
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Invoice'
        context['today'] = date.today().isoformat()
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = InvoiceItemFormSet(self.request.POST)
            else:
                context['items_formset'] = InvoiceItemFormSet()
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        items_formset = InvoiceItemFormSet(request.POST)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_totals()
        messages.success(self.request, f'Invoice {self.object.invoice_number} created successfully.')
        inv = self.object
        est = inv.estimate if inv.estimate_id else None
        if est and est.assigned_to_id:
            link = reverse('sales:invoice_detail', kwargs={'pk': inv.pk})
            notify_if_new_assignee(
                est.assigned_to,
                self.request.user,
                f'Invoice created: {inv.invoice_number}',
                f'From estimate {est.estimate_number} — {inv.customer.name}' if inv.customer else inv.invoice_number,
                link,
            )
        return redirect(self.success_url)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class InvoiceUpdateView(UpdatePermissionMixin, UpdateView):
    """Edit an invoice - only draft invoices can be edited."""
    model = Invoice
    form_class = InvoiceForm
    template_name = 'sales/invoice_form.html'
    module_name = 'sales'
    
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Block editing posted invoices
        if obj.status != 'draft':
            messages.error(self.request, 'Posted invoices cannot be edited. Only draft invoices are editable.')
            return None
        return obj
    
    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object is None:
            return redirect('sales:invoice_list')
        return super().get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Invoice: {self.object.invoice_number}'
        context['today'] = date.today().isoformat()
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = TaxCode.objects.filter(is_active=True, is_default=True).first()
        if 'items_formset' not in kwargs:
            if self.request.POST:
                context['items_formset'] = InvoiceItemFormSet(self.request.POST, instance=self.object)
            else:
                context['items_formset'] = InvoiceItemFormSet(instance=self.object)
        else:
            context['items_formset'] = kwargs['items_formset']
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object is None:
            return redirect('sales:invoice_list')
        form = self.get_form()
        items_formset = InvoiceItemFormSet(request.POST, instance=self.object)
        
        if form.is_valid() and items_formset.is_valid():
            return self.form_valid(form, items_formset)
        else:
            return self.form_invalid(form, items_formset)
    
    def form_valid(self, form, items_formset):
        # Save the main form first
        self.object = form.save()
        # Then save the formset with the instance
        items_formset.instance = self.object
        items_formset.save()
        # Recalculate totals
        self.object.calculate_totals()
        # Refresh from database to ensure we have latest data
        self.object.refresh_from_db()
        messages.success(self.request, f'Invoice {self.object.invoice_number} updated successfully.')
        return redirect('sales:invoice_detail', pk=self.object.pk)
    
    def form_invalid(self, form, items_formset):
        return self.render_to_response(
            self.get_context_data(form=form, items_formset=items_formset)
        )


class InvoiceDetailView(PermissionRequiredMixin, DetailView):
    """View invoice details."""
    model = Invoice
    template_name = 'sales/invoice_detail.html'
    context_object_name = 'invoice'
    module_name = 'sales'
    permission_type = 'view'
    
    def get_context_data(self, **kwargs):
        from apps.core.audit import get_entity_audit_history
        
        context = super().get_context_data(**kwargs)
        context['title'] = f'Invoice: {self.object.invoice_number}'
        has_permission = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'sales', 'edit'
        )
        # Only allow editing draft invoices
        context['can_edit'] = has_permission and self.object.status == 'draft'
        # Allow posting draft invoices
        context['can_post'] = has_permission and self.object.status == 'draft' and self.object.total_amount > 0
        
        # Audit History
        context['audit_history'] = get_entity_audit_history('Invoice', self.object.pk)
        
        return context


@login_required
def invoice_delete(request, pk):
    """Soft delete an invoice."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'delete'):
        invoice.is_active = False
        invoice.save()
        messages.success(request, f'Invoice {invoice.invoice_number} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('sales:invoice_list')


@login_required
def invoice_post(request, pk):
    """
    Post invoice to accounting - creates journal entry.
    Debit AR, Credit Sales, Credit VAT Payable
    """
    from apps.core.audit import audit_invoice_post
    
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('sales:invoice_detail', pk=pk)
    
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:invoice_list')
    
    if invoice.status != 'draft':
        messages.error(request, 'Only draft invoices can be posted to accounting.')
        return redirect('sales:invoice_detail', pk=pk)
    
    try:
        journal = invoice.post_to_accounting(user=request.user)
        # Audit log with IP address
        audit_invoice_post(invoice, request.user, request=request)
        messages.success(request, f'Invoice {invoice.invoice_number} posted to accounting. Journal: {journal.entry_number}')
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        messages.error(request, f'Error posting invoice: {e}')
    
    return redirect('sales:invoice_detail', pk=pk)


@login_required
def invoice_update_status(request, pk, status):
    """Update invoice status."""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('sales:invoice_detail', pk=pk)
    
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:invoice_detail', pk=pk)
    
    valid_statuses = ['sent', 'paid', 'partial', 'overdue', 'cancelled']
    if status not in valid_statuses:
        messages.error(request, 'Invalid status.')
        return redirect('sales:invoice_detail', pk=pk)
    
    # Don't allow changing draft invoices - they need to be posted first
    if invoice.status == 'draft':
        messages.error(request, 'Please post the invoice to accounting first.')
        return redirect('sales:invoice_detail', pk=pk)
    
    old_status = invoice.status
    invoice.status = status
    invoice.save()
    
    status_display = dict(Invoice.STATUS_CHOICES).get(status, status)
    messages.success(request, f'Invoice {invoice.invoice_number} status updated to {status_display}.')
    
    return redirect('sales:invoice_detail', pk=pk)


@login_required
def invoice_pdf(request, pk):
    """
    Generate FTA-compliant Tax Invoice PDF.
    UAE VAT Requirements per FTA guidelines:
    - Seller details (Name, Address, TRN)
    - Buyer details (Name, Address, TRN if B2B)
    - Invoice number and date
    - Supply date (if different)
    - Description of goods/services
    - Quantity and unit price
    - VAT rate and amount
    - Total amount in AED
    """
    from django.http import HttpResponse
    from apps.settings_app.models import CompanySettings
    
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer', 'estimate').prefetch_related('items'),
        pk=pk
    )
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:invoice_list')
    
    # Get company settings
    company = CompanySettings.get_settings()
    
    # Convert amount to words (simple implementation)
    def number_to_words(n):
        """Convert number to words (simplified English)."""
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 
                'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
        
        if n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + ('' if n % 10 == 0 else ' ' + ones[n % 10])
        elif n < 1000:
            return ones[n // 100] + ' Hundred' + ('' if n % 100 == 0 else ' and ' + number_to_words(n % 100))
        elif n < 1000000:
            return number_to_words(n // 1000) + ' Thousand' + ('' if n % 1000 == 0 else ' ' + number_to_words(n % 1000))
        elif n < 1000000000:
            return number_to_words(n // 1000000) + ' Million' + ('' if n % 1000000 == 0 else ' ' + number_to_words(n % 1000000))
        return str(n)
    
    try:
        amount_whole = int(invoice.total_amount)
        amount_decimal = int((invoice.total_amount - amount_whole) * 100)
        amount_words = number_to_words(amount_whole)
        if amount_decimal > 0:
            amount_words += f" and {amount_decimal}/100"
        amount_words += " Dirhams Only"
    except:
        amount_words = ""
    
    # Calculate VAT summary by rate
    vat_summary = {}
    for item in invoice.items.all():
        rate = float(item.vat_rate)
        if rate not in vat_summary:
            vat_summary[rate] = {'taxable': 0, 'vat': 0}
        vat_summary[rate]['taxable'] += float(item.total)
        vat_summary[rate]['vat'] += float(item.vat_amount)

    logo_absolute_url = ''
    if company.logo:
        logo_absolute_url = request.build_absolute_uri(company.logo.url)

    context = {
        'invoice': invoice,
        'company': company,
        'amount_words': amount_words,
        'vat_summary': vat_summary,
        'logo_absolute_url': logo_absolute_url,
        'is_pdf': True,
    }
    
    # Check if we should return HTML (for browser print) or try PDF generation
    output_format = request.GET.get('format', 'html')
    
    if output_format == 'pdf':
        # Try to generate actual PDF using weasyprint
        try:
            from weasyprint import HTML, CSS
            from django.template.loader import get_template
            
            template = get_template('sales/invoice_pdf.html')
            html_string = template.render(context)
            
            # Generate PDF
            html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
            pdf = html.write_pdf()
            
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="Invoice_{invoice.invoice_number}.pdf"'
            return response
            
        except ImportError:
            # WeasyPrint not installed, fall back to HTML
            messages.info(request, 'PDF generation requires WeasyPrint. Showing printable HTML version.')
            return render(request, 'sales/invoice_pdf.html', context)
    
    # Return printable HTML version
    return render(request, 'sales/invoice_pdf.html', context)



# ============ PAYMENT RECEIPT FOR INVOICE ============

@login_required
def invoice_receive_payment(request, pk):
    """
    Record payment received for an invoice.
    SAP/Oracle Standard: Payment creates clearing entry for AR.
    
    Dr Bank
    Cr Accounts Receivable
    """
    from apps.finance.models import (
        Payment, BankAccount, JournalEntry, JournalEntryLine, 
        Account, AccountType, AccountMapping
    )
    
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:invoice_detail', pk=pk)
    
    # Invoice must be posted first
    if invoice.status == 'draft':
        messages.error(request, 'Invoice must be posted to accounting before receiving payment.')
        return redirect('sales:invoice_detail', pk=pk)
    
    # Check if already fully paid
    if invoice.balance <= 0:
        messages.error(request, 'Invoice is already fully paid.')
        return redirect('sales:invoice_detail', pk=pk)
    
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
            if amount > invoice.balance:
                messages.warning(request, f'Amount exceeds balance. Adjusted to {invoice.balance}')
                amount = invoice.balance
        except (ValueError, InvalidOperation) as e:
            messages.error(request, f'Invalid amount: {e}')
            return redirect('sales:invoice_detail', pk=pk)
        
        # Get bank account
        bank_account = None
        if payment_method == 'bank' and bank_account_id:
            bank_account = BankAccount.objects.filter(pk=bank_account_id, is_active=True).first()
            if not bank_account:
                messages.error(request, 'Invalid bank account selected.')
                return redirect('sales:invoice_detail', pk=pk)
        elif payment_method == 'bank':
            # Use default bank account
            bank_account = BankAccount.objects.filter(is_active=True).first()
        
        if payment_method == 'bank' and not bank_account:
            messages.error(request, 'Bank account is required for bank transfer payments.')
            return redirect('sales:invoice_detail', pk=pk)
        
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
            payment_type='received',
            payment_method=payment_method,
            payment_date=payment_date,
            party_type='customer',
            party_id=invoice.customer_id,
            party_name=invoice.customer.name,
            amount=amount,
            reference=reference or invoice.invoice_number,
            bank_account=bank_account,
            status='draft',
        )
        
        # Get accounts using Account Mapping — strict AR resolution, no Revenue fallback
        ar_account = AccountMapping.get_account_or_default('customer_receipt_ar_clear', '1200')
        if not ar_account:
            ar_account = Account.objects.filter(
                account_type=AccountType.ASSET, is_active=True, name__icontains='receivable'
            ).first()
        
        if not ar_account:
            messages.error(request, 'Accounts Receivable account not configured. '
                           'Set up "customer_receipt_ar_clear" in Account Mapping.')
            return redirect('sales:invoice_detail', pk=pk)
        
        if ar_account.account_type == AccountType.INCOME:
            messages.error(request, 'AR clearing account is mapped to a Revenue account. '
                           'Payments must credit Accounts Receivable, not Revenue.')
            return redirect('sales:invoice_detail', pk=pk)
        
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
            return redirect('sales:invoice_detail', pk=pk)
        
        # Create journal entry: Dr Bank, Cr AR
        journal = JournalEntry.objects.create(
            date=payment_date,
            reference=payment.payment_number,
            description=f"Payment Receipt: {invoice.invoice_number} - {invoice.customer.name}",
            entry_type='standard',
            source_module='payment',
        )
        
        # Debit Bank/Cash
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_gl_account,
            description=f"Payment from {invoice.customer.name}",
            debit=amount,
            credit=Decimal('0.00'),
        )
        
        # Credit Accounts Receivable
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f"AR Clearing - {invoice.invoice_number}",
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
            
            # Update invoice
            invoice.paid_amount += amount
            if invoice.paid_amount >= invoice.total_amount:
                invoice.status = 'paid'
            else:
                invoice.status = 'partial'
            invoice.save()
            
            messages.success(request, f'Payment of AED {amount:,.2f} received. Receipt: {payment.payment_number}')
        except Exception as e:
            journal.delete()
            payment.delete()
            messages.error(request, f'Error posting payment: {e}')
        
        return redirect('sales:invoice_detail', pk=pk)
    
    # GET - Show payment form
    bank_accounts = BankAccount.objects.filter(is_active=True)
    context = {
        'title': f'Receive Payment - {invoice.invoice_number}',
        'invoice': invoice,
        'bank_accounts': bank_accounts,
        'today': date.today().strftime('%Y-%m-%d'),
    }
    return render(request, 'sales/invoice_receive_payment.html', context)
