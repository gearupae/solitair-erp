"""
Purchase Views - Vendors, Purchase Requests, Purchase Orders, Vendor Bills, Expense Claims, Recurring Expenses
All purchase transactions post to accounting module as single source of truth.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView
from django.urls import reverse, reverse_lazy
from django.db.models import Q, Sum, Prefetch
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
from django.utils.dateparse import parse_date
from django.utils import timezone

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json

from django.views.decorators.http import require_POST

from .models import (
    Vendor, PurchaseRequest, PurchaseRequestItem, PurchaseRequestAttachment,
    PurchaseOrder, PurchaseOrderItem, PurchaseOrderReceipt, PurchaseOrderReceiptLine,
    VendorBill, VendorBillItem, VendorBillAttachment,
    ExpenseClaim, ExpenseClaimItem, RecurringExpense, RecurringExpenseLog
)
from .forms import (
    VendorForm, PurchaseRequestForm, PurchaseRequestItemFormSet,
    PurchaseOrderForm, PurchaseOrderItemFormSet,
    VendorBillForm, VendorBillItemFormSet,
    ExpenseClaimForm, ExpenseClaimItemFormSet, ExpenseClaimPaymentForm,
    RecurringExpenseForm
)
from .pr_approval_rules import annotate_pr_approval_actions, user_can_act_on_purchase_request
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker


def _active_inventory_items_data():
    """Active inventory items for PR/PO line dropdowns (embedded in forms)."""
    from apps.inventory.models import Item

    rows = Item.objects.filter(is_active=True, status='active').order_by('name')
    return [
        {
            'id': r.pk,
            'label': str(r),
            'name': r.name,
            'item_code': r.item_code,
            'brand': (r.brand or '').strip(),
            'unit': (r.unit or 'pcs').strip(),
            'purchase_price': str(r.purchase_price),
        }
        for r in rows
    ]


def _pr_brands_for_form_json():
    """Distinct brands from inventory and prior PR/PO lines — for datalist / picker."""
    from apps.inventory.models import Item

    brands = set(
        Item.objects.filter(is_active=True, status='active')
        .exclude(brand='')
        .values_list('brand', flat=True)
    )
    brands.update(
        PurchaseRequestItem.objects.exclude(brand='')
        .values_list('brand', flat=True)
        .distinct()
    )
    brands.update(
        PurchaseOrderItem.objects.exclude(brand='')
        .values_list('brand', flat=True)
        .distinct()
    )
    return sorted(b for b in brands if (b or '').strip())


def _active_inventory_items_json():
    return json.dumps(_active_inventory_items_data())


def _po_terms_templates_context():
    import json
    from django.core.serializers.json import DjangoJSONEncoder
    from apps.settings_app.models import PurchaseOrderTermsTemplate

    templates = list(
        PurchaseOrderTermsTemplate.objects.filter(is_active=True).order_by('sort_order', 'name')
    )
    return {
        'po_terms_templates_json': json.dumps(
            [
                {
                    'id': t.pk,
                    'name': t.name,
                    'body': t.body,
                    'is_default': t.is_default,
                    'is_active': t.is_active,
                    'sort_order': t.sort_order,
                }
                for t in templates
            ],
            cls=DjangoJSONEncoder,
        ),
    }


def _pr_inventory_items_json():
    return _active_inventory_items_json()


def _pr_inventory_stock_notices(pr):
    """PR lines linked to inventory items that already have stock on hand."""
    from apps.inventory.serial_stock import item_available_qty

    notices = []
    for line in pr.items.select_related('inventory_item').all():
        if not line.inventory_item_id:
            continue
        inv = line.inventory_item
        if not inv.is_active or inv.status != 'active':
            continue
        available = item_available_qty(inv)
        if available <= 0:
            continue
        notices.append({
            'name': inv.name,
            'item_code': inv.item_code,
            'requested_qty': line.quantity,
            'available_qty': available,
            'covers_request': available >= line.quantity,
        })
    return notices


def _save_vendor_bill_attachments(request, bill):
    """Persist uploaded files from `attachments` multi-file input."""
    uploaded = request.FILES.getlist('attachments')
    if not uploaded:
        return
    for f in uploaded:
        VendorBillAttachment.objects.create(
            vendor_bill=bill,
            file=f,
            filename=getattr(f, 'name', '') or '',
            uploaded_by=request.user if request.user.is_authenticated else None,
        )


def _can_manage_pr_vendor_attachments(user, pr) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if pr.requested_by_id == user.id:
        return True
    return PermissionChecker.has_permission(user, 'purchase', 'edit')


def _serialize_pr_vendor_attachment(att):
    name = att.filename or ''
    if not name and att.file:
        name = Path(att.file.name).name
    return {
        'id': att.pk,
        'vendor': att.vendor or '',
        'total_price': str(att.total_price) if att.total_price is not None else '',
        'filename': name,
        'file_url': att.file.url if att.file else '',
    }


# ============ VENDOR VIEWS ============

class VendorListView(PermissionRequiredMixin, ListView):
    model = Vendor
    template_name = 'purchase/vendor_list.html'
    context_object_name = 'vendors'
    module_name = 'purchase'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Vendor.objects.filter(is_active=True).order_by('-created_at', '-pk')
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
            return redirect('purchase:vendor_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        return context


class PurchaseDashboardView(PermissionRequiredMixin, TemplateView):
    template_name = 'purchase/dashboard.html'
    module_name = 'purchase'
    permission_type = 'view'

    def get_context_data(self, **kwargs):
        from .purchase_dashboard import build_purchase_dashboard_context

        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Purchase Dashboard'
        ctx.update(build_purchase_dashboard_context(self.request.user))
        return ctx


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
        queryset = PurchaseRequest.objects.filter(is_active=True).select_related(
            'requested_by', 'created_by'
        )
        from apps.core.visibility import filter_purchase_requests_for_user

        queryset = filter_purchase_requests_for_user(queryset, self.request.user)
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
        context['can_convert'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['today'] = date.today().isoformat()
        annotate_pr_approval_actions(self.request.user, context.get('purchase_requests', []))
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
        context['pr_inventory_items_data'] = _active_inventory_items_data()
        context['pr_inventory_items_json'] = json.dumps(context['pr_inventory_items_data'])
        context['pr_brands_json'] = json.dumps(_pr_brands_for_form_json())
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
        context['pr_inventory_items_data'] = _active_inventory_items_data()
        context['pr_inventory_items_json'] = json.dumps(context['pr_inventory_items_data'])
        context['pr_brands_json'] = json.dumps(_pr_brands_for_form_json())
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

    def get_queryset(self):
        qs = (
            PurchaseRequest.objects.filter(is_active=True)
            .select_related('requested_by', 'department', 'created_by')
            .prefetch_related('items__inventory_item', 'attachments')
        )
        from apps.core.visibility import filter_purchase_requests_for_user

        return filter_purchase_requests_for_user(qs, self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'PR: {self.object.pr_number}'
        context['pr_inventory_stock_notices'] = _pr_inventory_stock_notices(self.object)
        context['can_edit'] = (
            (self.request.user.is_superuser or
             PermissionChecker.has_permission(self.request.user, 'purchase', 'edit'))
            and (self.object.status in ['draft', 'returned'] or
                 (self.request.user.is_superuser and self.object.status == 'approved'))
        )
        context['can_submit'] = context['can_edit'] and self.object.status in ['draft', 'returned']
        can_act = user_can_act_on_purchase_request(self.request.user, self.object)
        context['can_approve'] = can_act
        context['can_reject'] = can_act
        context['can_return'] = can_act
        context['can_convert'] = (
            self.request.user.is_superuser or
            PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        ) and self.object.status == 'approved'
        context['can_manage_vendor_quotes'] = _can_manage_pr_vendor_attachments(
            self.request.user, self.object
        )
        context['quote_attachments'] = self.object.attachments.order_by('id')
        context['pr_vendor_upload_url'] = reverse(
            'purchase:pr_vendor_attachment_upload', args=[self.object.pk]
        )
        _ph = 999_999_999
        context['pr_vendor_update_url_pattern'] = reverse(
            'purchase:pr_vendor_attachment_update',
            args=[self.object.pk, _ph],
        ).replace(str(_ph), '__ATT_ID__')
        from apps.inventory.utils import get_openai_api_key, is_ai_available

        context['openai_configured'] = is_ai_available()
        context['pr_vendor_analyze_url'] = reverse(
            'purchase:pr_vendor_quote_analyze', args=[self.object.pk]
        )
        context['pr_vendor_analyze_status_url'] = reverse(
            'purchase:pr_vendor_quote_analyze_status', args=[self.object.pk]
        )
        context['has_quote_attachments'] = self.object.attachments.exists()
        context['show_vendor_quote_ai'] = True
        context['pr_pdf_url'] = reverse('purchase:pr_pdf', args=[self.object.pk])

        import json

        from apps.core.ai_knowledge import is_ai_analysis_auto_run
        from apps.core.models import AiModuleKnowledge
        from apps.purchase.services.vendor_quote_ai import get_cached_pr_quote_analysis
        from apps.core.compliance_service import auto_pr_compliance_on_detail

        context['ai_analysis_auto_run'] = is_ai_analysis_auto_run(AiModuleKnowledge.MODULE_PURCHASE_REQUEST)
        vendor_quote_analysis = None
        if context['has_quote_attachments']:
            vendor_quote_analysis = get_cached_pr_quote_analysis(self.object)
            if vendor_quote_analysis:
                auto_pr_compliance_on_detail(self.request.user, self.object, vendor_quote_analysis)
        context['pr_quote_auto_fetch'] = (
            context['ai_analysis_auto_run']
            and context['has_quote_attachments']
            and not vendor_quote_analysis
        )
        context['vendor_quote_analysis'] = vendor_quote_analysis
        context['vendor_quote_analysis_json'] = (
            json.dumps(vendor_quote_analysis) if vendor_quote_analysis else ''
        )
        return context


@login_required
def pr_pdf(request, pk):
    """Purchase request printable HTML / PDF — same visual style as quotation PDF."""
    from apps.core.visibility import user_can_access_purchase_request
    from .pr_pdf_render import build_pr_pdf_context, render_pr_pdf_bytes

    pr = get_object_or_404(
        PurchaseRequest.objects.filter(is_active=True)
        .select_related('requested_by', 'department', 'created_by')
        .prefetch_related('items'),
        pk=pk,
    )
    if not user_can_access_purchase_request(request.user, pr):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:pr_list')

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:pr_list')

    context = build_pr_pdf_context(request, pr)
    output_format = request.GET.get('format', 'html')
    if output_format == 'pdf':
        pdf, err = render_pr_pdf_bytes(request, pr)
        if pdf is not None:
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="PR_{pr.pr_number}.pdf"'
            return response
        if err:
            messages.info(request, err)
        return render(request, 'purchase/pr_pdf.html', context)

    return render(request, 'purchase/pr_pdf.html', context)


@login_required
@require_POST
def pr_vendor_attachment_upload(request, pk):
    """Upload one or more vendor quote files (PDF / Excel) for a purchase request."""
    pr = get_object_or_404(PurchaseRequest, pk=pk, is_active=True)
    if not _can_manage_pr_vendor_attachments(request.user, pr):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    allowed_ext = {'.pdf', '.xlsx', '.xls'}
    files = request.FILES.getlist('files')
    if not files:
        return JsonResponse({'ok': False, 'error': 'No files uploaded.'}, status=400)
    for f in files:
        ext = Path(f.name).suffix.lower()
        if ext not in allowed_ext:
            return JsonResponse(
                {
                    'ok': False,
                    'error': (
                        f'File type not allowed: {f.name}. '
                        'Use PDF or Excel (.xlsx, .xls).'
                    ),
                },
                status=400,
            )
    created = []
    errors = []
    for f in files:
        try:
            att = PurchaseRequestAttachment.objects.create(
                purchase_request=pr,
                file=f,
                filename=f.name,
                uploaded_by=request.user,
            )
            created.append(att)
        except Exception as exc:
            errors.append(f'{f.name}: {exc}')
    if not created:
        return JsonResponse(
            {
                'ok': False,
                'error': errors[0] if len(errors) == 1 else 'Upload failed for all files.',
                'errors': errors,
            },
            status=400,
        )
    from apps.purchase.services.vendor_quote_ai import cache_attachment_extracted_text, invalidate_pr_quote_analysis

    invalidate_pr_quote_analysis(pr)
    for att in created:
        try:
            cache_attachment_extracted_text(att)
        except Exception:
            pass
    payload = {
        'ok': True,
        'attachments': [_serialize_pr_vendor_attachment(a) for a in created],
    }
    if errors:
        payload['partial'] = True
        payload['errors'] = errors
    return JsonResponse(payload)


@login_required
@require_POST
def pr_vendor_attachment_update(request, pk, attachment_id):
    """Auto-save vendor name and total price for one attachment (JSON body)."""
    ct = (request.content_type or '').split(';')[0].strip().lower()
    if ct != 'application/json':
        return JsonResponse({'ok': False, 'error': 'Expected application/json.'}, status=400)
    pr = get_object_or_404(PurchaseRequest, pk=pk, is_active=True)
    if not _can_manage_pr_vendor_attachments(request.user, pr):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    att = get_object_or_404(PurchaseRequestAttachment, pk=attachment_id, purchase_request=pr)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)
    update_fields = []
    if 'vendor' in data:
        att.vendor = (data.get('vendor') or '')[:500]
        update_fields.append('vendor')
    if 'total_price' in data:
        raw = data.get('total_price')
        if raw is None or raw == '':
            att.total_price = None
        else:
            try:
                att.total_price = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                return JsonResponse({'ok': False, 'error': 'Invalid total price.'}, status=400)
        update_fields.append('total_price')
    if not update_fields:
        return JsonResponse({'ok': False, 'error': 'No fields to update.'}, status=400)
    att.save(update_fields=update_fields)
    payload = _serialize_pr_vendor_attachment(att)
    payload['ok'] = True
    return JsonResponse(payload)


def _user_can_view_pr(user, pr) -> bool:
    if not user.is_authenticated:
        return False
    from apps.core.visibility import filter_purchase_requests_for_user

    return filter_purchase_requests_for_user(
        PurchaseRequest.objects.filter(pk=pr.pk, is_active=True),
        user,
    ).exists()


@login_required
@require_POST
def pr_vendor_quote_analyze(request, pk):
    """Start AI comparison of attached vendor quotation PDFs / Excel files (background)."""
    pr = get_object_or_404(PurchaseRequest, pk=pk, is_active=True)
    if not _user_can_view_pr(request.user, pr):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    force = (request.POST.get('force') or '').lower() in ('1', 'true', 'yes')
    sync = (request.POST.get('sync') or '').lower() in ('1', 'true', 'yes')
    from apps.purchase.services.vendor_quote_ai import (
        analyze_vendor_quotes,
        start_vendor_quote_analysis_async,
    )

    if sync:
        result = analyze_vendor_quotes(pr, force=force)
    else:
        result = start_vendor_quote_analysis_async(pr, force=force)

    if result.get('ok') and result.get('status') == 'complete':
        from apps.core.compliance_service import auto_pr_compliance_on_detail

        auto_pr_compliance_on_detail(request.user, pr, result)

    if result.get('status') == 'running':
        return JsonResponse(result, status=202)
    status = 200 if result.get('ok') else 400
    return JsonResponse(result, status=status)


@login_required
def pr_vendor_quote_analyze_status(request, pk):
    """Poll vendor quote AI analysis progress / result."""
    pr = get_object_or_404(PurchaseRequest, pk=pk, is_active=True)
    if not _user_can_view_pr(request.user, pr):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    from apps.purchase.services.vendor_quote_ai import get_vendor_quote_analysis_status

    result = get_vendor_quote_analysis_status(pr)
    if result.get('status') == 'complete' and result.get('ok'):
        from apps.core.compliance_service import auto_pr_compliance_on_detail

        auto_pr_compliance_on_detail(request.user, pr, result)
    return JsonResponse(result)


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
    if pr.status != 'pending':
        messages.error(request, 'Only pending requests can be approved.')
        return redirect('purchase:pr_detail', pk=pk)
    if not user_can_act_on_purchase_request(request.user, pr):
        messages.error(request, 'Only the configured approver can approve this request.')
        return redirect('purchase:pr_detail', pk=pk)
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
    return redirect('purchase:pr_detail', pk=pk)


@login_required
def pr_reject(request, pk):
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    if not user_can_act_on_purchase_request(request.user, pr):
        messages.error(request, 'Only the configured approver can reject this request.')
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
    if not user_can_act_on_purchase_request(request.user, pr):
        messages.error(request, 'Only the configured approver can reject this request.')
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
            'description': item.formatted_line_display(),
            'brand': item.brand or '',
            'model': item.model or '',
            'item_description': item.description or '',
            'quantity': str(item.quantity),
            'estimated_price': str(item.estimated_price),
            # Use estimated_price as unit_price, and default VAT to 5%
            'unit_price': str(item.estimated_price),
            'vat_rate': '5.00',
            'inventory_item_id': item.inventory_item_id,
        })
    return JsonResponse({'items': items})


@login_required
def po_items_json(request, pk):
    """Return PO items as JSON for AJAX requests."""
    from .po_retention import po_retention_percent_label

    po = get_object_or_404(PurchaseOrder, pk=pk)
    items = []
    for item in po.items.all():
        items.append({
            'description': item.formatted_line_display(),
            'brand': item.brand or '',
            'model': item.model or '',
            'item_description': item.description or '',
            'quantity': str(item.quantity),
            'unit_price': str(item.unit_price),
            'vat_rate': str(item.vat_rate),
            'tax_code_id': item.tax_code_id,
            'inventory_item_id': item.inventory_item_id,
        })
    return JsonResponse({
        'items': items,
        'vendor_id': po.vendor.id if po.vendor else None,
        'project_id': po.project_id,
        'retention_percent': str(int(po.retention_percent)) if po.retention_percent else '',
        'retention_label': po_retention_percent_label(po.retention_percent),
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
        queryset = PurchaseOrder.objects.filter(is_active=True).select_related(
            'vendor', 'created_by', 'purchase_request', 'purchase_request__requested_by'
        )
        from apps.core.visibility import filter_purchase_orders_for_user

        queryset = filter_purchase_orders_for_user(queryset, self.request.user)
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
        context['pending_pos'] = all_pos.filter(status__in=['draft', 'sent', 'confirmed', 'partial_received']).count()
        context['confirmed_pos'] = all_pos.filter(status='confirmed').count()
        
        return context


class PurchaseOrderCreateView(CreatePermissionMixin, CreateView):
    model = PurchaseOrder
    form_class = PurchaseOrderForm
    template_name = 'purchase/po_form.html'
    success_url = reverse_lazy('purchase:po_list')
    module_name = 'purchase'

    def get_initial(self):
        from apps.settings_app.models import PurchaseOrderTermsTemplate

        initial = super().get_initial()
        initial['terms_and_conditions'] = PurchaseOrderTermsTemplate.get_default_body()
        return initial
    
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
        context['po_inventory_items_data'] = _active_inventory_items_data()
        context['po_inventory_items_json'] = json.dumps(context['po_inventory_items_data'])
        context['po_brands_json'] = json.dumps(_pr_brands_for_form_json())
        context.update(_po_terms_templates_context())
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
        context['po_inventory_items_data'] = _active_inventory_items_data()
        context['po_inventory_items_json'] = json.dumps(context['po_inventory_items_data'])
        context['po_brands_json'] = json.dumps(_pr_brands_for_form_json())
        context.update(_po_terms_templates_context())
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

    def get_queryset(self):
        rcpt_qs = (
            PurchaseOrderReceipt.objects.select_related('warehouse', 'created_by')
            .prefetch_related(
                Prefetch(
                    'lines',
                    queryset=PurchaseOrderReceiptLine.objects.select_related(
                        'purchase_order_item',
                        'purchase_order_item__inventory_item',
                    ),
                )
            )
            .order_by('created_at')
        )
        qs = (
            PurchaseOrder.objects.filter(is_active=True)
            .select_related('vendor', 'purchase_request', 'service_request', 'created_by', 'project')
            .prefetch_related(
                Prefetch('goods_receipts', queryset=rcpt_qs),
                'items__inventory_item',
                Prefetch(
                    'bills',
                    queryset=VendorBill.objects.filter(is_active=True).exclude(status='cancelled').order_by('-bill_date', '-pk'),
                ),
            )
        )
        from apps.core.visibility import filter_purchase_orders_for_user

        return filter_purchase_orders_for_user(qs, self.request.user)

    def get_context_data(self, **kwargs):
        from apps.settings_app.models import CompanySettings

        from .email_outbound import outgoing_mail_hint
        from .receiving import purchase_order_can_receive

        context = super().get_context_data(**kwargs)
        context['title'] = f'PO: {self.object.po_number}'
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        company = CompanySettings.get_settings()
        context['po_email_hint'] = outgoing_mail_hint(company)
        context['can_send_po_email'] = (
            self.request.user.is_superuser
            or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        ) and self.object.status != 'cancelled'
        context['po_email_send_url'] = reverse('purchase:po_send_email', args=[self.object.pk])
        context['po_email_default_subject'] = f'Purchase Order {self.object.po_number}'
        vendor_name = self.object.vendor.name if self.object.vendor_id else 'Vendor'
        context['po_email_default_body'] = (
            f'Dear {vendor_name},\n\n'
            f'Please find attached Purchase Order {self.object.po_number} for your reference.\n\n'
            f'Kind regards,\n{company.company_name}'
        )
        ve = ''
        if self.object.vendor_id and (self.object.vendor.email or '').strip():
            ve = self.object.vendor.email.strip()
        context['po_email_default_to'] = ve

        context['can_receive_po'] = (
            context['can_edit'] and purchase_order_can_receive(self.object)
        )
        context['can_confirm_po'] = (
            context['can_edit']
            and self.object.status == 'draft'
            and self.object.items.exists()
        )
        context['po_receive_url'] = reverse('purchase:po_receive', args=[self.object.pk])
        from .po_retention import po_retention_percent_label, vendor_bill_retention_summary_rows
        from .po_retention_forms import PurchaseOrderRetentionForm

        context['po_retention_form'] = PurchaseOrderRetentionForm(purchase_order=self.object)
        context['retention_percent_label'] = po_retention_percent_label(self.object.retention_percent)
        context['po_vendor_bills'] = list(self.object.bills.all())
        bill_summary = vendor_bill_retention_summary_rows(context['po_vendor_bills'])
        context['po_bill_retention_rows'] = bill_summary['rows']
        context['po_total_retention'] = bill_summary['total_retention']
        context['can_create_bill'] = (
            context['can_edit']
            and self.object.status != 'cancelled'
            and self.object.items.exists()
        )
        from apps.inventory.utils import get_openai_api_key, is_ai_available
        from apps.core.ai_knowledge import is_ai_analysis_auto_run
        from apps.core.models import AiModuleKnowledge
        from apps.core.compliance_service import auto_compliance_on_detail, run_po_compliance

        context['openai_configured'] = is_ai_available()
        context['ai_analysis_auto_run'] = is_ai_analysis_auto_run(AiModuleKnowledge.MODULE_PURCHASE_ORDER)
        context['po_ai_evaluate_url'] = reverse('purchase:po_ai_evaluate', args=[self.object.pk])
        evaluation = run_po_compliance(self.object, full_run=False)
        context['ai_compliance_auto_fetch'] = context['ai_analysis_auto_run'] and not evaluation.get('from_cache')
        auto_compliance_on_detail(
            self.request.user,
            'purchase_order',
            evaluation,
            record_label=self.object.po_number,
            link=reverse('purchase:po_detail', args=[self.object.pk]),
        )
        context['po_ai_evaluation'] = evaluation
        return context


@login_required
def po_ai_evaluate(request, pk):
    """AJAX: AI review of PO terms, retention, vendor, items, and VAT."""
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    po = get_object_or_404(
        PurchaseOrder.objects.filter(is_active=True)
        .select_related('vendor', 'project')
        .prefetch_related('items__tax_code', 'items__inventory_item'),
        pk=pk,
    )
    from apps.core.visibility import user_can_access_purchase_order

    if not user_can_access_purchase_order(request.user, po):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'view')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)
    from .po_evaluate_ai import evaluate_purchase_order

    force = request.POST.get('force') == '1'
    try:
        result = evaluate_purchase_order(po, force_refresh=force)
        from apps.core.compliance_service import auto_compliance_on_detail

        auto_compliance_on_detail(
            request.user,
            'purchase_order',
            result,
            record_label=po.po_number,
            link=reverse('purchase:po_detail', args=[po.pk]),
        )
        return JsonResponse({'ok': True, 'evaluation': result})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


@login_required
@require_POST
def po_save_retention(request, pk):
    """Save project + retention % on a purchase order."""
    po = get_object_or_404(PurchaseOrder.objects.filter(is_active=True), pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:po_detail', pk=pk)
    from .po_retention_forms import PurchaseOrderRetentionForm

    form = PurchaseOrderRetentionForm(request.POST, purchase_order=po)
    if form.is_valid():
        form.save(po)
        messages.success(request, 'Project retention updated on this PO.')
    else:
        for _field, errors in form.errors.items():
            for err in errors:
                messages.error(request, err)
    return redirect('purchase:po_detail', pk=pk)


@login_required
def po_retention_json(request, pk):
    from .po_retention import po_retention_percent_label, resolve_purchase_retention_for_po

    po = get_object_or_404(PurchaseOrder.objects.filter(is_active=True), pk=pk)
    pct = resolve_purchase_retention_for_po(po)
    pct_str = str(int(pct)) if pct is not None else ''
    return JsonResponse({
        'ok': True,
        'po_id': po.pk,
        'po_number': po.po_number,
        'project_id': po.project_id,
        'retention_percent': pct_str,
        'retention_label': po_retention_percent_label(pct),
    })


@login_required
def project_purchase_retention_json(request, pk):
    from apps.projects.models import Project
    from .po_retention import po_retention_percent_label, resolve_purchase_retention_for_project

    project = get_object_or_404(Project, pk=pk, is_active=True)
    pct = resolve_purchase_retention_for_project(project)
    pct_str = str(int(pct)) if pct is not None else ''
    return JsonResponse({
        'ok': True,
        'project_id': project.pk,
        'project_name': project.name,
        'retention_percent': pct_str,
        'retention_label': po_retention_percent_label(pct),
    })


@login_required
def po_convert_to_bill(request, pk):
    """Create a draft vendor bill from a purchase order."""
    po = get_object_or_404(
        PurchaseOrder.objects.filter(is_active=True).prefetch_related('items'),
        pk=pk,
    )
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:po_detail', pk=pk)
    if po.status == 'cancelled':
        messages.error(request, 'Cannot create a bill from a cancelled PO.')
        return redirect('purchase:po_detail', pk=pk)
    if not po.items.exists():
        messages.error(request, 'Add line items to the PO before converting to a vendor bill.')
        return redirect('purchase:po_detail', pk=pk)

    from datetime import timedelta

    bill = VendorBill.objects.create(
        vendor=po.vendor,
        purchase_order=po,
        project=po.project,
        retention_percent=po.retention_percent,
        bill_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status='draft',
        goods_received=po.status == 'received',
        notes=f'Created from PO {po.po_number}',
    )
    for item in po.items.all():
        VendorBillItem.objects.create(
            bill=bill,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            tax_code=item.tax_code,
            vat_rate=item.vat_rate,
            is_vat_inclusive=item.is_vat_inclusive,
        )
    bill.calculate_totals()
    messages.success(request, f'Vendor bill {bill.bill_number} created from PO {po.po_number}.')
    return redirect('purchase:bill_edit', pk=bill.pk)


@login_required
@require_POST
def po_confirm(request, pk):
    """Mark a draft PO as confirmed so goods can be received."""
    po = get_object_or_404(PurchaseOrder.objects.filter(is_active=True), pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:po_detail', pk=pk)
    if po.status != 'draft':
        messages.warning(request, f'PO {po.po_number} is already {po.get_status_display().lower()}.')
        return redirect('purchase:po_detail', pk=pk)
    if not po.items.exists():
        messages.error(request, 'Add at least one line item before confirming this PO.')
        return redirect('purchase:po_edit', pk=pk)
    po.status = 'confirmed'
    po.save(update_fields=['status', 'updated_at'])
    messages.success(
        request,
        f'PO {po.po_number} confirmed. You can now receive goods into inventory.',
    )
    return redirect('purchase:po_detail', pk=pk)


def _po_receive_line_rows(po, post_data=None):
    """Build template rows with optional reposted qty/price/model numbers."""
    rows = []
    for line in po.items.all():
        if post_data is not None:
            posted_qty = (post_data.get(f'qty_{line.pk}') or '0').strip()
            posted_price = post_data.get(f'price_{line.pk}')
            if posted_price is None or posted_price == '':
                posted_price = f'{line.unit_price:.2f}'
            posted_models = post_data.getlist(f'model_number_{line.pk}')
        else:
            posted_qty = '0'
            posted_price = f'{line.unit_price:.2f}'
            posted_models = []
        rows.append({
            'line': line,
            'posted_qty': posted_qty,
            'posted_price': posted_price,
            'posted_model_numbers': posted_models,
        })
    return rows


def _po_receive_context(po, warehouses, *, post_data=None, warehouse_pk=None, recv_date=None, notes=''):
    if recv_date is None:
        recv_date = timezone.now().date()
    if warehouse_pk is None:
        first_wh = warehouses.first()
        warehouse_pk = first_wh.pk if first_wh else None
    return {
        'title': f'Receive — {po.po_number}',
        'po': po,
        'warehouses': warehouses,
        'receive_lines': _po_receive_line_rows(po, post_data),
        'posted_warehouse_pk': warehouse_pk,
        'posted_received_on': recv_date.isoformat(),
        'posted_notes': notes or '',
    }


@login_required
def po_receive(request, pk):
    """Goods receipt against PO — partial/full receive, stock in, audit trail."""
    from apps.inventory.models import Warehouse

    from .receiving import purchase_order_can_receive
    from .services.grn_service import post_grn_from_po

    po = get_object_or_404(
        PurchaseOrder.objects.filter(is_active=True).prefetch_related('items__inventory_item'),
        pk=pk,
    )

    can_edit = request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')
    if not can_edit:
        messages.error(request, 'Permission denied.')
        return redirect('purchase:po_detail', pk=pk)

    if not purchase_order_can_receive(po):
        messages.error(request, 'This purchase order cannot receive goods.')
        return redirect('purchase:po_detail', pk=pk)

    warehouses = Warehouse.objects.filter(is_active=True, status='active').order_by('name')

    if request.method == 'POST':
        wid_raw = request.POST.get('warehouse')
        try:
            warehouse_pk = int(wid_raw)
        except (TypeError, ValueError):
            warehouse_pk = None
        recv_date = parse_date(request.POST.get('received_on') or '')
        if not recv_date:
            recv_date = timezone.now().date()
        notes = (request.POST.get('notes') or '').strip()

        payloads = []
        for line in po.items.all():
            payloads.append(
                {
                    'purchase_order_item_id': line.pk,
                    'qty_raw': request.POST.get(f'qty_{line.pk}', ''),
                    'unit_price_raw': request.POST.get(f'price_{line.pk}', ''),
                    'model_numbers': request.POST.getlist(f'model_number_{line.pk}'),
                }
            )

        try:
            grn = post_grn_from_po(
                po.pk,
                warehouse_pk,
                recv_date,
                notes,
                payloads,
                request.user,
                supplier_delivery_note=(request.POST.get('supplier_delivery_note') or '').strip(),
            )
        except ValidationError as exc:
            errs = getattr(exc, 'messages', None)
            if errs:
                for msg in errs:
                    messages.error(request, msg)
            else:
                messages.error(request, str(exc))
            return render(
                request,
                'purchase/po_receive.html',
                _po_receive_context(
                    po,
                    warehouses,
                    post_data=request.POST,
                    warehouse_pk=warehouse_pk,
                    recv_date=recv_date,
                    notes=notes,
                ),
            )

        messages.success(
            request,
            f'Goods received for PO {po.po_number}. GRN {grn.grn_number} posted.',
        )
        return redirect('purchase:grn_detail', pk=grn.pk)

    return render(
        request,
        'purchase/po_receive.html',
        _po_receive_context(po, warehouses),
    )


@login_required
def po_pdf(request, pk):
    """
    Purchase order PDF / printable HTML — same visual design as tax invoice PDF.
    """
    from .po_pdf_render import build_po_pdf_context, render_po_pdf_bytes

    po = get_object_or_404(
        PurchaseOrder.objects.filter(is_active=True)
        .select_related('vendor', 'purchase_request', 'service_request')
        .prefetch_related('items'),
        pk=pk,
    )

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:po_list')

    context = build_po_pdf_context(request, po)

    output_format = request.GET.get('format', 'html')
    if output_format == 'pdf':
        pdf, err = render_po_pdf_bytes(request, po)
        if pdf is not None:
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="PO_{po.po_number}.pdf"'
            return response
        if err:
            messages.info(request, err)
        return render(request, 'purchase/po_pdf.html', context)

    return render(request, 'purchase/po_pdf.html', context)


@login_required
@require_POST
def po_send_email(request, pk):
    """Send purchase order by email with PO PDF attached (SMTP from Company Settings or env)."""
    from apps.settings_app.models import CompanySettings

    from .email_outbound import (
        company_outgoing_from_email,
        get_smtp_connection_or_default,
        validate_cc_addresses,
        validate_to_addresses,
    )
    from .po_pdf_render import render_po_pdf_bytes

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'purchase', 'edit')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    po = get_object_or_404(
        PurchaseOrder.objects.filter(is_active=True)
        .select_related('vendor', 'purchase_request', 'service_request')
        .prefetch_related('items'),
        pk=pk,
    )
    if po.status == 'cancelled':
        return JsonResponse({'ok': False, 'error': 'Cannot email a cancelled purchase order.'}, status=400)

    subject = (request.POST.get('subject') or '').strip()
    body = (request.POST.get('body') or '').strip()
    to_raw = request.POST.get('to', '')
    cc_raw = request.POST.get('cc', '')

    if not subject:
        return JsonResponse({'ok': False, 'error': 'Subject is required.'}, status=400)
    if not body:
        return JsonResponse({'ok': False, 'error': 'Message body is required.'}, status=400)

    try:
        to_list = validate_to_addresses(to_raw)
        cc_list = validate_cc_addresses(cc_raw)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    company = CompanySettings.get_settings()
    pdf, pdf_err = render_po_pdf_bytes(request, po)
    if not pdf:
        return JsonResponse(
            {'ok': False, 'error': pdf_err or 'Could not generate PDF attachment.'},
            status=400,
        )

    from django.core.mail import EmailMessage

    connection = get_smtp_connection_or_default(company)
    from_email = company_outgoing_from_email(company)

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=to_list,
        cc=cc_list,
        connection=connection,
    )
    msg.content_subtype = 'plain'
    safe_name = ''.join(c for c in po.po_number if c.isalnum() or c in ('-', '_')) or str(po.pk)
    msg.attach(f'PO_{safe_name}.pdf', pdf, 'application/pdf')

    try:
        msg.send(fail_silently=False)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Could not send email: {exc}'}, status=502)

    return JsonResponse({'ok': True, 'message': 'Email sent.'})


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
        queryset = VendorBill.objects.filter(is_active=True).select_related('vendor', 'project')
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
        from .po_retention import sync_vendor_bill_retention_links

        retention_amount = form.cleaned_data.get('retention_amount')
        self.object = form.save(commit=False)
        sync_vendor_bill_retention_links(self.object)
        self.object.save()
        items_formset.instance = self.object
        items_formset.save()
        _save_vendor_bill_attachments(self.request, self.object)
        self.object.calculate_totals(retention_amount=retention_amount)
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
        from .po_retention import sync_vendor_bill_retention_links

        retention_amount = form.cleaned_data.get('retention_amount')
        self.object = form.save(commit=False)
        sync_vendor_bill_retention_links(self.object)
        self.object.save()
        items_formset.instance = self.object
        items_formset.save()
        _save_vendor_bill_attachments(self.request, self.object)
        self.object.calculate_totals(retention_amount=retention_amount)
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

    def get_queryset(self):
        return (
            VendorBill.objects.filter(is_active=True)
            .select_related('vendor', 'journal_entry', 'project')
            .prefetch_related('items', 'attachments')
        )

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
        
        return queryset.order_by('-submitted_at', '-created_at', '-claim_date', '-pk')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Expense Claims'
        context['status_choices'] = ExpenseClaim.STATUS_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'edit')
        context['can_approve'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'purchase', 'approve')
        context['public_expense_claim_url'] = reverse('purchase:public_expense_claim')
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


class ExpenseClaimUpdateView(UpdatePermissionMixin, UpdateView):
    """Edit expense claim (draft, or submitted for approvers)."""
    model = ExpenseClaim
    form_class = ExpenseClaimForm
    template_name = 'purchase/expenseclaim_form.html'
    module_name = 'purchase'

    def get_queryset(self):
        return ExpenseClaim.objects.filter(is_active=True)

    def dispatch(self, request, *args, **kwargs):
        claim = self.get_object()
        can_edit = request.user.is_superuser or PermissionChecker.has_permission(
            request.user, 'purchase', 'edit'
        )
        can_approve = request.user.is_superuser or PermissionChecker.has_permission(
            request.user, 'purchase', 'approve'
        )
        if claim.status == 'draft' and can_edit:
            return super().dispatch(request, *args, **kwargs)
        if claim.status == 'submitted' and can_approve:
            return super().dispatch(request, *args, **kwargs)
        messages.error(request, 'This claim cannot be edited.')
        return redirect('purchase:expenseclaim_detail', pk=claim.pk)

    def get_success_url(self):
        return reverse('purchase:expenseclaim_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Expense Claim: {self.object.claim_number}'
        context['today'] = date.today().isoformat()
        context['is_edit'] = True
        if self.request.POST:
            context['items_formset'] = ExpenseClaimItemFormSet(
                self.request.POST, self.request.FILES, instance=self.object
            )
        else:
            context['items_formset'] = ExpenseClaimItemFormSet(instance=self.object)
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        items_formset = context['items_formset']
        if items_formset.is_valid():
            self.object = form.save()
            items_formset.instance = self.object
            items_formset.save()
            self.object.calculate_totals()
            messages.success(self.request, f'Expense Claim {self.object.claim_number} updated.')
            return redirect(self.get_success_url())
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
        context['can_edit'] = (
            (has_permission and self.object.status == 'draft')
            or (can_approve and self.object.status == 'submitted')
        )
        
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
    from django.utils import timezone
    claim.submitted_at = timezone.now()
    claim.save(update_fields=['status', 'submitted_at'])
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
