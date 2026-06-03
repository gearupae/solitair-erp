"""
Sales Views - Estimates and Invoices
Invoices post to accounting module as single source of truth.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse, reverse_lazy
from django.db import transaction
from django.db.models import Q, Sum, Prefetch, Count
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from datetime import date
from decimal import Decimal, InvalidOperation
from collections import defaultdict
import json

from .models import Estimate, EstimateItem, EstimateProformaInvoice, EstimateRevisionSnapshot, Invoice, InvoiceItem
from .forms import EstimateForm, EstimateItemFormSet, InvoiceForm, InvoiceItemFormSet
from .estimate_csv import get_default_estimate_csv_tax_code
from apps.crm.models import Customer
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.notification_utils import notify_if_new_assignee
from apps.core.utils import PermissionChecker
from apps.settings_app.models import CompanySettings

from .estimate_pdf_render import render_estimate_quotation_pdf_bytes
from .estimate_change_detection import estimate_form_has_changes
from .estimate_edit_flow import apply_after_estimate_save, EstimateEditApplyResult
from .estimate_revision_snapshot import maybe_snapshot_before_revision


def _pdf_media_absolute_url(request, file_field, *, for_weasyprint=False):
    """
    URL for images in quotation PDF templates.
    Browser preview needs http(s) URLs; WeasyPrint can use local file:// paths.
    """
    if not file_field:
        return ''
    url = file_field.url
    if url.startswith(('http://', 'https://')):
        return url
    if not for_weasyprint:
        return request.build_absolute_uri(url)

    import os
    from pathlib import Path

    try:
        path = file_field.path
        if path and os.path.isfile(path):
            return Path(path).resolve().as_uri()
    except (ValueError, NotImplementedError):
        pass
    return request.build_absolute_uri(url)


def _estimate_save_success_message(
    estimate,
    *,
    has_changes: bool,
    result: EstimateEditApplyResult | None,
    rev_before: int,
) -> str:
    if not has_changes:
        return 'No changes were made; the estimate was not sent for re-approval.'
    msg = f'Estimate {estimate.display_estimate_number} updated successfully.'
    if result and result.resubmitted_for_approval:
        msg += ' Sent for approval again.'
        if result.revision_bumped and estimate.revision_label:
            msg += f' Revision {estimate.revision_label}.'
    elif result and result.edit_pending:
        msg += ' Changes are queued for approval (see Settings → Approval configuration).'
        if (estimate.revision_count or 0) > rev_before and estimate.revision_label:
            msg += f' Resubmitted as revision {estimate.revision_label}.'
    return msg

def _inventory_item_estimate_json(item):
    """Serialize inventory item bounds as effective AED amounts for estimate line validation."""
    return {
        'id': item.id,
        'item_code': item.item_code,
        'name': item.name,
        'selling_price': item.selling_price,
        'minimum_selling_price_value': item.minimum_selling_price,
        'minimum_selling_price_type': item.minimum_selling_price_type,
        'maximum_selling_price_value': item.maximum_selling_price,
        'maximum_selling_price_type': item.maximum_selling_price_type,
        'quote_maximum_rate': item.get_quote_maximum_rate(item.selling_price),
        'quote_minimum_rate': item.get_quote_minimum_rate(item.selling_price),
        'tax_code_id': item.tax_code_id,
    }


def _inventory_items_for_estimate_json(limit=2000):
    from apps.inventory.models import Item

    return [
        _inventory_item_estimate_json(item)
        for item in Item.objects.filter(is_active=True, status='active').order_by('item_code', 'pk')[:limit]
    ]


def _estimate_form_inventory_groups_context():
    """
    Item groups with active items for estimate line-item bulk add + group name datalist.
    """
    from apps.inventory.models import ItemGroup, ItemGroupMembership

    groups = []
    for g in ItemGroup.objects.select_related('base_group').order_by('name'):
        memberships = (
            ItemGroupMembership.objects.filter(
                group=g,
                item__is_active=True,
                item__status='active',
            )
            .select_related('item')
            .order_by('sort_order', 'item__item_code', 'pk')
        )
        if not memberships.exists():
            continue
        groups.append({
            'name': g.name,
            'base_group': g.base_group.name if g.base_group_id else '',
            'items': [
                {
                    **_inventory_item_estimate_json(m.item),
                    'default_quantity': float(m.default_quantity or 1),
                }
                for m in memberships
            ],
        })

    return {
        'inventory_groups_json': json.dumps(groups, cls=DjangoJSONEncoder),
        'inventory_group_names': [entry['name'] for entry in groups],
    }


def _estimate_text_templates_context():
    """Active client note / terms templates for the estimate form dropdowns."""
    from apps.settings_app.models import EstimateTextTemplate

    client_notes = list(
        EstimateTextTemplate.objects.filter(
            template_type=EstimateTextTemplate.CLIENT_NOTE,
            is_active=True,
        )
        .order_by('sort_order', 'name')
        .values('id', 'name', 'body', 'is_default')
    )
    terms = list(
        EstimateTextTemplate.objects.filter(
            template_type=EstimateTextTemplate.TERMS,
            is_active=True,
        )
        .order_by('sort_order', 'name')
        .values('id', 'name', 'body', 'is_default')
    )
    return {
        'estimate_client_note_templates_json': json.dumps(client_notes, cls=DjangoJSONEncoder),
        'estimate_terms_templates_json': json.dumps(terms, cls=DjangoJSONEncoder),
    }


def _estimate_default_signatures_context():
    """Company default signature previews for the estimate form."""
    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    return {
        'company_default_authorized_signature_url': (
            cs.estimate_default_authorized_signature.url
            if cs.estimate_default_authorized_signature else ''
        ),
        'company_default_customer_signature_url': (
            cs.estimate_default_customer_signature.url
            if cs.estimate_default_customer_signature else ''
        ),
    }


def apply_company_default_estimate_signatures(estimate, request_files=None):
    """Copy company default signature images when the estimate has none uploaded."""
    import os

    from django.core.files.base import ContentFile

    from apps.settings_app.models import CompanySettings

    cs = CompanySettings.get_settings()
    request_files = request_files or {}
    updates = []

    for est_field, cs_field, upload_key in (
        ('authorized_signature', 'estimate_default_authorized_signature', 'authorized_signature'),
        ('customer_signature', 'estimate_default_customer_signature', 'customer_signature'),
    ):
        if getattr(estimate, est_field):
            continue
        if request_files.get(upload_key):
            continue
        source = getattr(cs, cs_field, None)
        if not source:
            continue
        with source.open('rb') as src:
            content = src.read()
        filename = os.path.basename(source.name)
        dest = getattr(estimate, est_field)
        dest.save(filename, ContentFile(content), save=False)
        updates.append(est_field)

    if updates:
        estimate.save(update_fields=updates)


@login_required
def estimate_items_sample_csv(request):
    """Download CSV template for estimate line items (inventory item_code + pricing fields)."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'create')):
        return HttpResponseForbidden('Permission denied.')
    from .estimate_csv import sample_csv_content

    response = HttpResponse(sample_csv_content(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="estimate_line_items_sample.csv"'
    return response


def user_can_convert_estimate_to_project(user, estimate):
    """Whether the user may convert this estimate to a project (button + POST)."""
    from .approval_rules import user_can_convert_estimate_follow_on

    return user_can_convert_estimate_follow_on(user, estimate)


ESTIMATE_LIST_SORT_FIELDS = {
    'estimate_number': 'estimate_number',
    'customer': 'customer__company',
    'date': 'date',
    'valid': 'valid_until',
    'status': 'status',
    'amount': 'total_amount',
}


def _estimate_list_sort_querystring(request_get, field):
    """Next sort state for list links (toggles asc/desc on same column, drops page)."""
    params = request_get.copy()
    params.pop('page', None)
    if field not in ESTIMATE_LIST_SORT_FIELDS:
        field = 'date'
    current = params.get('sort', 'date')
    if current not in ESTIMATE_LIST_SORT_FIELDS:
        current = 'date'
    order = (params.get('order') or 'desc').lower()
    if order not in ('asc', 'desc'):
        order = 'desc'
    if current == field:
        params['sort'] = field
        params['order'] = 'asc' if order == 'desc' else 'desc'
    else:
        params['sort'] = field
        params['order'] = 'desc'
    return params.urlencode()


def attach_customer_quotation_won_counts(estimates):
    """
    Set customer_qw_count on each estimate: other quotation-won rows for the same customer.
    """
    items = list(estimates)
    if not items:
        return items

    customer_ids = {e.customer_id for e in items if e.customer_id}
    totals = {}
    if customer_ids:
        totals = dict(
            Estimate.objects.filter(
                is_active=True,
                customer_id__in=customer_ids,
                status='quotation_won',
            )
            .values('customer_id')
            .annotate(c=Count('id'))
            .values_list('customer_id', 'c')
        )

    for estimate in items:
        customer_id = estimate.customer_id
        if not customer_id:
            estimate.customer_qw_count = 0
            continue
        count = totals.get(customer_id, 0)
        if estimate.status == 'quotation_won':
            count = max(0, count - 1)
        estimate.customer_qw_count = count

    return items


def attach_customer_quotation_lost_counts(estimates):
    """Set customer_ql_count: other quotation-lost rows for the same customer."""
    items = list(estimates)
    if not items:
        return items

    customer_ids = {e.customer_id for e in items if e.customer_id}
    totals = {}
    if customer_ids:
        totals = dict(
            Estimate.objects.filter(
                is_active=True,
                customer_id__in=customer_ids,
                status='quotation_lost',
            )
            .values('customer_id')
            .annotate(c=Count('id'))
            .values_list('customer_id', 'c')
        )

    for estimate in items:
        customer_id = estimate.customer_id
        if not customer_id:
            estimate.customer_ql_count = 0
            continue
        count = totals.get(customer_id, 0)
        if estimate.status == 'quotation_lost':
            count = max(0, count - 1)
        estimate.customer_ql_count = count

    return items


def _scope_estimate_form_fields(form, user):
    from apps.core.visibility import filter_customers_for_user
    from apps.crm.models import Customer

    form.fields['customer'].queryset = filter_customers_for_user(
        Customer.objects.filter(is_active=True), user
    )
    return form


# ============ ESTIMATE VIEWS ============

class EstimateListView(PermissionRequiredMixin, ListView):
    """List all estimates."""
    model = Estimate
    template_name = 'sales/estimate_list.html'
    context_object_name = 'estimates'
    module_name = 'sales'
    permission_type = 'view'
    paginate_by = 25

    def get_paginate_by(self, queryset):
        from .approval_rules import user_is_estimate_approver_portal

        if user_is_estimate_approver_portal(self.request.user):
            return self.paginate_by
        # Match tasks (`view=kanban`); legacy `view=board` still works.
        v = (self.request.GET.get('view') or '').strip().lower()
        if v in ('kanban', 'board'):
            return None
        return self.paginate_by

    def _get_list_sort(self):
        sort_key = self.request.GET.get('sort') or 'date'
        if sort_key not in ESTIMATE_LIST_SORT_FIELDS:
            sort_key = 'date'
        order = (self.request.GET.get('order') or 'desc').lower()
        if order not in ('asc', 'desc'):
            order = 'desc'
        return sort_key, order
    
    def get_queryset(self):
        from .approval_rules import user_is_estimate_approver_portal

        queryset = Estimate.objects.filter(is_active=True).select_related(
            'customer',
            'assigned_to',
            'created_by',
        ).prefetch_related(
            Prefetch(
                'proforma_invoices',
                queryset=EstimateProformaInvoice.objects.order_by('-created_at'),
            ),
            Prefetch(
                'invoices',
                queryset=Invoice.objects.exclude(status='cancelled').order_by('-created_at'),
            ),
        )

        from apps.core.visibility import filter_estimates_for_user

        queryset = filter_estimates_for_user(queryset, self.request.user)

        is_portal = user_is_estimate_approver_portal(self.request.user)
        if is_portal:
            tab = (self.request.GET.get('tab') or 'pending').strip().lower()
            if tab == 'approved':
                queryset = queryset.filter(status__in=['approved', 'quotation_won'])
            else:
                queryset = queryset.filter(status='sent')
        else:
            status = self.request.GET.get('status')
            if status:
                queryset = queryset.filter(status=status)

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(estimate_number__icontains=search) |
                Q(customer__name__icontains=search)
            )

        v = (self.request.GET.get('view') or '').strip().lower()
        if is_portal or v in ('kanban', 'board'):
            return queryset.order_by('-date', '-pk')

        sort_key, order = self._get_list_sort()
        field = ESTIMATE_LIST_SORT_FIELDS[sort_key]
        prefix = '' if order == 'asc' else '-'
        return queryset.order_by(f'{prefix}{field}', f'{prefix}pk')
    
    def get_context_data(self, **kwargs):
        from .approval_rules import user_is_estimate_approver_portal

        context = super().get_context_data(**kwargs)
        is_portal = user_is_estimate_approver_portal(self.request.user)
        approver_tab = (self.request.GET.get('tab') or 'pending').strip().lower()
        if approver_tab not in ('pending', 'approved'):
            approver_tab = 'pending'
        context['is_approver_portal'] = is_portal
        context['approver_tab'] = approver_tab
        context['approver_tab_readonly'] = is_portal and approver_tab == 'approved'

        sort_key, order_dir = self._get_list_sort()
        context['sort_field'] = sort_key
        context['sort_order'] = order_dir
        context['sort_links'] = {
            k: _estimate_list_sort_querystring(self.request.GET, k)
            for k in ESTIMATE_LIST_SORT_FIELDS
        }
        context['title'] = 'Estimates'
        context['customers'] = Customer.objects.filter(is_active=True)
        context['status_choices'] = Estimate.STATUS_CHOICES
        context['can_create'] = (
            not is_portal
            and (
                self.request.user.is_superuser
                or PermissionChecker.has_permission(self.request.user, 'sales', 'create')
            )
        )
        context['can_edit'] = (
            not is_portal
            and (
                self.request.user.is_superuser
                or PermissionChecker.has_permission(self.request.user, 'sales', 'edit')
            )
        )
        context['can_delete'] = (
            not is_portal
            and (
                self.request.user.is_superuser
                or PermissionChecker.has_permission(self.request.user, 'sales', 'delete')
            )
        )
        context['can_approve_status'] = is_portal and approver_tab == 'pending'
        context['today'] = date.today().isoformat()

        raw_view = (self.request.GET.get('view') or '').strip().lower()
        context['view_mode'] = 'list' if is_portal else ('kanban' if raw_view in ('kanban', 'board') else 'list')
        q = self.request.GET.copy()
        q.pop('view', None)
        list_q = q.copy()
        kanban_q = q.copy()
        kanban_q['view'] = 'kanban'
        context['estimate_list_url_list'] = '?' + list_q.urlencode()
        context['estimate_list_url_kanban'] = '?' + kanban_q.urlencode()

        from .approval_rules import user_can_convert_estimate_follow_on

        user = self.request.user
        for est in context.get('estimates', []):
            est.can_convert_follow_on = user_can_convert_estimate_follow_on(user, est)

        base_qs = Estimate.objects.filter(is_active=True)
        if is_portal:
            context['pending_count'] = base_qs.filter(status='sent').count()
            context['approved_tab_count'] = base_qs.filter(
                status__in=['approved', 'quotation_won'],
            ).count()
            context['total_estimates'] = (
                context['pending_count'] if approver_tab == 'pending' else context['approved_tab_count']
            )
            tab_qs = self.get_queryset()
            context['total_amount'] = tab_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['approved_amount'] = context['total_amount'] if approver_tab == 'approved' else 0
        else:
            estimates = self.get_queryset()
            context['total_estimates'] = estimates.count()
            context['total_amount'] = estimates.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['approved_amount'] = estimates.filter(
                status__in=['approved', 'quotation_won'],
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['pending_count'] = estimates.filter(status__in=['draft', 'sent']).count()
            context['approved_tab_count'] = 0

        q_tab = self.request.GET.copy()
        q_tab.pop('tab', None)
        pending_q = q_tab.copy()
        pending_q['tab'] = 'pending'
        approved_q = q_tab.copy()
        approved_q['tab'] = 'approved'
        context['approver_tab_url_pending'] = '?' + pending_q.urlencode()
        context['approver_tab_url_approved'] = '?' + approved_q.urlencode()

        estimates = self.get_queryset()
        if context['view_mode'] == 'kanban':
            bucket_statuses = frozenset(
                {
                    'draft',
                    'sent',
                    'approved',
                    'rejected',
                    'under_negotiation',
                    'quotation_won',
                    'quotation_lost',
                }
            )
            by_status = defaultdict(list)
            for est in estimates:
                st = est.status if est.status in bucket_statuses else 'draft'
                by_status[st].append(est)
            context['estimates_board_draft'] = list(by_status['draft'])
            context['estimates_board_sent'] = list(by_status['sent'])
            context['estimates_board_approved'] = list(by_status['approved'])
            context['estimates_board_lost'] = list(by_status['rejected'])
            context['estimates_board_negotiation'] = list(by_status['under_negotiation'])
            context['estimates_board_quot_won'] = list(by_status['quotation_won'])
            context['estimates_board_quot_lost'] = list(by_status['quotation_lost'])
        else:
            context['estimates_board_draft'] = []
            context['estimates_board_sent'] = []
            context['estimates_board_approved'] = []
            context['estimates_board_lost'] = []
            context['estimates_board_negotiation'] = []
            context['estimates_board_quot_won'] = []
            context['estimates_board_quot_lost'] = []

        from .approval_rules import allowed_status_choices_for_estimate

        page_estimates = context.get('estimates') or []
        if context['view_mode'] != 'kanban':
            attach_customer_quotation_won_counts(page_estimates)
            attach_customer_quotation_lost_counts(page_estimates)
        for est in page_estimates:
            est.allowed_status_choices = allowed_status_choices_for_estimate(
                est, self.request.user
            )

        return context


class EstimateCreateView(CreatePermissionMixin, CreateView):
    """Create a new estimate."""
    model = Estimate
    form_class = EstimateForm
    template_name = 'sales/estimate_form.html'
    success_url = reverse_lazy('sales:estimate_list')
    module_name = 'sales'

    def get_initial(self):
        from apps.settings_app.models import EstimateTextTemplate
        initial = super().get_initial()
        initial['date'] = date.today()
        initial['assigned_to'] = self.request.user.pk
        u = self.request.user
        initial['prepared_by'] = (u.get_full_name() or '').strip() or u.username
        client_note = EstimateTextTemplate.get_default_body(EstimateTextTemplate.CLIENT_NOTE)
        if client_note:
            initial['client_note'] = client_note
        terms = EstimateTextTemplate.get_default_body(EstimateTextTemplate.TERMS)
        if terms:
            initial['terms_and_conditions'] = terms
        return initial

    def get_form(self, form_class=None):
        return _scope_estimate_form_fields(super().get_form(form_class), self.request.user)
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        from apps.inventory.models import Item
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Estimate'
        context['today'] = date.today().isoformat()
        # Tax Codes for VAT selection (SAP/Oracle Standard)
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = get_default_estimate_csv_tax_code()
        rows = _inventory_items_for_estimate_json()
        context['inventory_items_json'] = json.dumps(rows, cls=DjangoJSONEncoder)
        context['estimate_items_sample_csv_url'] = reverse('sales:estimate_items_sample_csv')
        context['inventory_items_export_csv_url'] = reverse('inventory:item_export_csv')
        context.update(_estimate_form_inventory_groups_context())
        context.update(_estimate_text_templates_context())
        context.update(_estimate_default_signatures_context())
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
                apply_company_default_estimate_signatures(self.object, request.FILES)
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
        apply_company_default_estimate_signatures(self.object, self.request.FILES)
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

    def dispatch(self, request, *args, **kwargs):
        from apps.core.visibility import filter_estimates_for_user

        est = get_object_or_404(
            filter_estimates_for_user(
                Estimate.objects.filter(pk=kwargs['pk'], is_active=True),
                request.user,
            )
        )
        if not est.allows_edit_by(request.user):
            messages.error(
                request,
                'You cannot edit this estimate. Estimates marked as Quot Won can only be changed by an administrator.',
            )
            return redirect('sales:estimate_detail', pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        return _scope_estimate_form_fields(super().get_form(form_class), self.request.user)

    def get_context_data(self, **kwargs):
        from apps.finance.models import TaxCode
        from apps.inventory.models import Item
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Estimate: {self.object.estimate_number}'
        context['today'] = date.today().isoformat()
        context['tax_codes'] = TaxCode.objects.filter(is_active=True).order_by('code')
        context['default_tax_code'] = get_default_estimate_csv_tax_code()
        rows = _inventory_items_for_estimate_json()
        context['inventory_items_json'] = json.dumps(rows, cls=DjangoJSONEncoder)
        context['estimate_items_sample_csv_url'] = reverse('sales:estimate_items_sample_csv')
        context['inventory_items_export_csv_url'] = reverse('inventory:item_export_csv')
        context.update(_estimate_form_inventory_groups_context())
        context.update(_estimate_text_templates_context())
        context.update(_estimate_default_signatures_context())
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
                pre_status = self.object.status
                rev_before = self.object.revision_count or 0
                maybe_snapshot_before_revision(
                    request, self.object, pre_status=pre_status, has_changes=True,
                )
                self.object = form.save()
                bulk_create_estimate_items(self.object, rows, replace_existing=True)
                self.object.calculate_totals()
                self.object.refresh_from_db()
                result = apply_after_estimate_save(
                    request,
                    self.object,
                    pre_status=pre_status,
                )
                self.object.refresh_from_db()
                detail_url = redirect('sales:estimate_detail', pk=self.object.pk)
                messages.success(
                    request,
                    _estimate_save_success_message(
                        self.object,
                        has_changes=True,
                        result=result,
                        rev_before=rev_before,
                    ),
                )
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
                return detail_url
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
        has_changes = estimate_form_has_changes(form, items_formset)
        old_assignee_id = self.object.assigned_to_id
        pre_status = self.object.status
        rev_before = self.object.revision_count or 0
        if has_changes:
            maybe_snapshot_before_revision(
                self.request, self.object, pre_status=pre_status, has_changes=True,
            )
        self.object = form.save()
        items_formset.instance = self.object
        items_formset.save()
        self.object.calculate_totals()
        self.object.refresh_from_db()

        result = None
        if has_changes:
            result = apply_after_estimate_save(
                self.request,
                self.object,
                pre_status=pre_status,
            )
            self.object.refresh_from_db()

        messages.success(
            self.request,
            _estimate_save_success_message(
                self.object,
                has_changes=has_changes,
                result=result,
                rev_before=rev_before,
            ),
        )
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
        qs = Estimate.objects.filter(is_active=True).select_related(
            'customer', 'assigned_to', 'project', 'created_by', 'updated_by',
        ).prefetch_related(
            Prefetch('items', queryset=items_qs),
            Prefetch('proforma_invoices', queryset=EstimateProformaInvoice.objects.select_related('created_by')),
            Prefetch(
                'invoices',
                queryset=Invoice.objects.exclude(status='cancelled').order_by('-created_at'),
            ),
            Prefetch(
                'revision_snapshots',
                queryset=EstimateRevisionSnapshot.objects.select_related('created_by').order_by('-revision_number', '-created_at'),
            ),
        )
        from apps.core.visibility import filter_estimates_for_user

        return filter_estimates_for_user(qs, self.request.user)

    def dispatch(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        est = Estimate.objects.filter(pk=pk, is_active=True).first()
        if est:
            from apps.core.visibility import user_can_access_estimate

            if not user_can_access_estimate(request.user, est):
                messages.error(request, 'You do not have permission to view this estimate.')
                return redirect('sales:estimate_list')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        from apps.purchase.email_outbound import outgoing_mail_hint

        context = super().get_context_data(**kwargs)
        context['title'] = f'Estimate: {self.object.estimate_number}'
        from .approval_rules import (
            get_estimate_status_actions,
            user_can_approve_estimate_edit,
            user_can_approve_estimate_status,
            user_can_convert_estimate_follow_on,
        )

        context['can_edit'] = self.object.allows_edit_by(self.request.user)
        context['can_convert_estimate_follow_on'] = user_can_convert_estimate_follow_on(
            self.request.user, self.object
        )
        context['can_approve_estimate_status'] = user_can_approve_estimate_status(
            self.request.user, self.object
        )
        context['estimate_status_actions'] = get_estimate_status_actions(
            self.object, self.request.user
        )
        context['can_approve_estimate_edit'] = (
            user_can_approve_estimate_edit(self.request.user, self.object)
            and self.object.edit_approval_status == 'pending'
        )
        context['can_reject_estimate_edit'] = context['can_approve_estimate_edit']
        co = CompanySettings.get_settings()
        context['estimate_to_project_prompt_include_lines'] = co.estimate_to_project_prompt_include_lines

        context['estimate_email_hint'] = outgoing_mail_hint(co)
        context['can_send_estimate_email'] = (
            self.request.user.is_superuser
            or PermissionChecker.has_permission(self.request.user, 'sales', 'edit')
        ) and self.object.is_active
        context['estimate_email_send_url'] = reverse(
            'sales:estimate_send_email', args=[self.object.pk]
        )
        context['estimate_email_default_subject'] = (
            f'Estimate — {self.object.estimate_number}'
        )
        cust = self.object.customer
        who = cust.company.strip() if (cust.company or '').strip() else cust.name
        context['estimate_email_default_body'] = (
            f'Dear {who},\n\n'
            f'Please find attached our estimate document ({self.object.estimate_number}) for your reference.\n\n'
            f'Kind regards,\n{co.company_name}'
        )
        to_addr = ''
        if (cust.email or '').strip():
            to_addr = cust.email.strip()
        context['estimate_email_default_to'] = to_addr
        context['can_create_proforma'] = self.object.status == 'quotation_won'
        context['proforma_invoices'] = list(
            self.object.proforma_invoices.select_related('created_by').all()[:20]
        )
        from .estimate_pdf_groups import build_pdf_item_groups
        context['item_groups'] = build_pdf_item_groups(self.object)
        context['revision_snapshots'] = list(self.object.revision_snapshots.all())
        return context


@login_required
def estimate_approve_edit(request, pk):
    """Clear pending edit-review flag (Settings → Approval configuration — Estimate)."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    estimate = get_object_or_404(Estimate, pk=pk, is_active=True)
    from .approval_rules import user_can_approve_estimate_edit

    if not user_can_approve_estimate_edit(request.user, estimate):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_detail', pk=pk)
    if estimate.edit_approval_status != 'pending':
        messages.warning(request, 'This estimate does not have a pending edit approval.')
        return redirect('sales:estimate_detail', pk=pk)

    submitter = estimate.edit_approval_submitted_by
    estimate.edit_approval_status = 'none'
    estimate.edit_approval_submitted_at = None
    estimate.edit_approval_submitted_by_id = None
    estimate.save(
        update_fields=[
            'edit_approval_status',
            'edit_approval_submitted_at',
            'edit_approval_submitted_by',
            'updated_at',
        ]
    )
    from apps.settings_app.models import ApprovalAuditLog
    from .estimate_approval_notifications import notify_submitter_estimate_edit_approved

    ApprovalAuditLog.objects.create(
        module='estimate',
        reference=estimate.estimate_number,
        approver=request.user,
        action='approve',
        comment='Estimate edit acknowledged',
    )
    if submitter:
        notify_submitter_estimate_edit_approved(
            estimate, approver=request.user, submitter=submitter
        )
    messages.success(request, f'{estimate.estimate_number}: edit changes approved.')
    return redirect('sales:estimate_detail', pk=pk)


@login_required
def estimate_reject_edit(request, pk):
    """Mark pending edit review as rejected; editor can correct and save again."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    estimate = get_object_or_404(Estimate, pk=pk, is_active=True)
    from .approval_rules import user_can_approve_estimate_edit

    if not user_can_approve_estimate_edit(request.user, estimate):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_detail', pk=pk)
    if estimate.edit_approval_status != 'pending':
        messages.warning(request, 'This estimate does not have a pending edit approval.')
        return redirect('sales:estimate_detail', pk=pk)
    comment = (request.POST.get('comment') or '').strip()
    estimate.edit_approval_status = 'rejected'
    estimate.save(
        update_fields=['edit_approval_status', 'updated_at']
    )
    from apps.settings_app.models import ApprovalAuditLog
    from .estimate_approval_notifications import notify_submitter_estimate_edit_rejected

    ApprovalAuditLog.objects.create(
        module='estimate',
        reference=estimate.estimate_number,
        approver=request.user,
        action='reject',
        comment=comment[:2000],
    )
    notify_submitter_estimate_edit_rejected(
        estimate, approver=request.user, comment=comment
    )
    messages.success(request, 'Edit marked as rejected; the assigned user has been notified.')
    return redirect('sales:estimate_detail', pk=pk)


@login_required
def estimate_duplicate(request, pk):
    """Create a copy of an estimate as a new draft (new number, lines copied, no linked project)."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'create')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_list')

    source = get_object_or_404(Estimate.objects.select_related('customer'), pk=pk, is_active=True)
    items_qs = list(source.items.order_by('sort_order', 'id'))

    with transaction.atomic():
        dest = Estimate(
            customer=source.customer,
            assigned_to=source.assigned_to,
            prepared_by=source.prepared_by,
            type_of_occupancy=source.type_of_occupancy,
            type_of_work=source.type_of_work,
            scope_of_work=source.scope_of_work,
            date=source.date,
            valid_until=source.valid_until,
            status='draft',
            notes=source.notes,
            client_note=source.client_note,
            terms_and_conditions=source.terms_and_conditions,
            discount_type=source.discount_type,
            discount_value=source.discount_value,
            show_rates_on_pdf=source.show_rates_on_pdf,
            show_group_totals_on_pdf=source.show_group_totals_on_pdf,
            show_brand_name_on_pdf=source.show_brand_name_on_pdf,
            # Fresh draft; avoids two estimates pinned to same project/invoices ambiguity
            project=None,
        )
        dest.save()

        for it in items_qs:
            EstimateItem.objects.create(
                estimate=dest,
                group_name=it.group_name,
                group_qty_multiplier=it.group_qty_multiplier,
                sort_order=it.sort_order,
                inventory_item=it.inventory_item,
                description=it.description,
                quantity=it.quantity,
                unit_price=it.unit_price,
                profit_type=it.profit_type,
                profit_value=it.profit_value,
                tax_code=it.tax_code,
                is_vat_inclusive=it.is_vat_inclusive,
            )

        dest.calculate_totals()

    notify_if_new_assignee(
        dest.assigned_to,
        request.user,
        f'Duplicated estimate assigned: {dest.estimate_number}',
        f'Copy of {source.estimate_number} — {dest.customer.name}' if dest.customer else dest.estimate_number,
        reverse('sales:estimate_detail', kwargs={'pk': dest.pk}),
    )
    messages.success(
        request,
        f'Duplicated {source.estimate_number} → {dest.estimate_number} (draft).',
    )
    return redirect('sales:estimate_edit', pk=dest.pk)


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
    
    valid_statuses = [c[0] for c in Estimate.STATUS_CHOICES]
    if status not in valid_statuses:
        messages.error(request, 'Invalid status.')
        return redirect('sales:estimate_detail', pk=pk)

    if status in ('approved', 'rejected'):
        from .approval_rules import user_can_approve_estimate_status

        if not user_can_approve_estimate_status(request.user, estimate):
            messages.error(request, 'Only the configured estimate approver can approve or reject this estimate.')
            return redirect('sales:estimate_detail', pk=pk)

    from .approval_rules import estimate_status_change_allowed

    if not estimate_status_change_allowed(
        estimate.status, status, user=request.user, estimate=estimate
    ):
        if status in ('quotation_won', 'quotation_lost'):
            from .approval_rules import user_can_mark_estimate_won_lost

            if estimate.status not in ('approved', 'under_negotiation'):
                messages.error(
                    request,
                    'Mark estimate won or lost only when the estimate is approved or under negotiation.',
                )
            elif not user_can_mark_estimate_won_lost(request.user, estimate):
                messages.error(
                    request,
                    'Only the salesperson assigned to this estimate can mark it won or lost.',
                )
            else:
                messages.error(request, 'That status change is not allowed.')
        elif status == 'draft' and estimate.status == 'quotation_won':
            messages.error(request, 'A won quotation cannot be reverted to draft.')
        else:
            messages.error(request, 'That status change is not allowed.')
        return redirect('sales:estimate_detail', pk=pk)
    
    old_status = estimate.status
    rejection_reason = (request.POST.get('rejection_reason') or '').strip()

    from .estimate_status_change import (
        after_estimate_status_saved,
        apply_estimate_status_fields,
        validate_status_rejection_reason,
    )

    reason_error = validate_status_rejection_reason(status, old_status, rejection_reason)
    if reason_error:
        messages.error(request, reason_error)
        return redirect('sales:estimate_detail', pk=pk)

    update_fields = apply_estimate_status_fields(
        estimate,
        new_status=status,
        old_status=old_status,
        user=request.user,
        rejection_reason=rejection_reason,
    )
    estimate.save(update_fields=update_fields)
    after_estimate_status_saved(
        estimate,
        new_status=status,
        old_status=old_status,
        user=request.user,
        rejection_reason=rejection_reason,
    )

    status_display = dict(Estimate.STATUS_CHOICES).get(status, status)
    messages.success(request, f'Estimate {estimate.estimate_number} status updated to {status_display}.')
    
    return redirect('sales:estimate_detail', pk=pk)


@login_required
def estimate_convert_to_invoice(request, pk):
    """Convert an approved or quotation-won estimate to invoice."""
    estimate = get_object_or_404(Estimate, pk=pk)

    from .approval_rules import user_can_convert_estimate_follow_on

    if not user_can_convert_estimate_follow_on(request.user, estimate):
        messages.error(
            request,
            'Only the assigned salesperson or the user who created this estimate can convert it to an invoice.',
        )
        return redirect('sales:estimate_detail', pk=pk)

    if not estimate.allows_follow_on_conversion:
        messages.error(request, 'Only approved or quotation-won estimates can be converted to an invoice.')
        return redirect('sales:estimate_detail', pk=pk)

    existing = estimate.primary_invoice
    if existing:
        messages.warning(
            request,
            f'This estimate already has invoice {existing.invoice_number}. '
            f'Record payments on the invoice, not the estimate.',
        )
        return redirect('sales:invoice_detail', pk=existing.pk)

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


@login_required
def estimate_convert_to_project(request, pk):
    """Create a project from an approved or quotation-won estimate; optionally copy estimate lines."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    estimate = get_object_or_404(
        Estimate.objects.filter(is_active=True).select_related('customer'),
        pk=pk,
    )

    if not user_can_convert_estimate_to_project(request.user, estimate):
        messages.error(
            request,
            'Only the assigned salesperson or the user who created this estimate can convert it to a project.',
        )
        return redirect('sales:estimate_detail', pk=pk)

    if not estimate.allows_follow_on_conversion:
        messages.error(request, 'Only approved or quotation-won estimates can be converted to a project.')
        return redirect('sales:estimate_detail', pk=pk)

    if estimate.project_id:
        messages.error(request, 'This estimate is already linked to a project.')
        return redirect('sales:estimate_detail', pk=pk)

    from .estimate_to_project import create_project_from_estimate

    company = CompanySettings.get_settings()
    if company.estimate_to_project_prompt_include_lines:
        raw = (request.POST.get('include_items') or '').strip().lower()
        include_items = raw in ('1', 'true', 'yes', 'on')
    else:
        include_items = False

    project = create_project_from_estimate(estimate=estimate, include_items=include_items)
    messages.success(
        request,
        f'Project {project.project_code} created from estimate {estimate.estimate_number}.',
    )
    return redirect('projects:project_detail', pk=project.pk)


def _build_estimate_pdf_context(request, estimate, *, proforma_invoice=None, for_weasyprint=False):
    """
    Shared context for proposal and proforma invoice HTML (print/PDF).
    Caller adds document_heading, document_number, print_button_label, page_title.
    """
    from apps.settings_app.models import CompanySettings
    from .estimate_pdf_groups import build_pdf_item_groups
    from .proforma_calculation import resolve_proforma_vat_rate_percent

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
        pdf_total = (
            proforma_invoice.total_amount
            if proforma_invoice is not None
            else estimate.total_amount
        )
        amount_whole = int(pdf_total)
        amount_decimal = int((pdf_total - amount_whole) * 100)
        amount_words = number_to_words(amount_whole)
        if amount_decimal > 0:
            amount_words += f" and {amount_decimal}/100"
        amount_words += " Dirhams Only"
    except Exception:
        amount_words = ""

    vat_summary = {}
    if proforma_invoice is not None:
        if proforma_invoice.line_subtotal > 0 and proforma_invoice.vat_amount > 0:
            rate = float(
                (proforma_invoice.vat_amount / proforma_invoice.line_subtotal * Decimal('100')).quantize(
                    Decimal('0.01')
                )
            )
        elif proforma_invoice.line_subtotal > 0:
            rate = float(resolve_proforma_vat_rate_percent(estimate))
        else:
            rate = 0.0
        vat_summary[rate] = {
            'taxable': float(proforma_invoice.line_subtotal),
            'vat': float(proforma_invoice.vat_amount),
        }
    else:
        vat_summary = estimate.build_vat_summary()

    media_kw = {'for_weasyprint': for_weasyprint}
    logo_absolute_url = _pdf_media_absolute_url(request, company.logo, **media_kw)

    authorized_sig = estimate.authorized_signature or company.estimate_default_authorized_signature
    customer_sig = estimate.customer_signature or company.estimate_default_customer_signature
    authorized_signature_url = _pdf_media_absolute_url(request, authorized_sig, **media_kw)
    customer_signature_url = _pdf_media_absolute_url(request, customer_sig, **media_kw)

    pdf_image_1_url = _pdf_media_absolute_url(request, company.estimate_pdf_stamp_image, **media_kw)
    pdf_image_2_url = _pdf_media_absolute_url(request, company.estimate_pdf_footer_image, **media_kw)

    return {
        'estimate': estimate,
        'proforma_invoice': proforma_invoice,
        'company': company,
        'logo_absolute_url': logo_absolute_url,
        'authorized_signature_url': authorized_signature_url,
        'customer_signature_url': customer_signature_url,
        'pdf_image_1_url': pdf_image_1_url,
        'pdf_image_2_url': pdf_image_2_url,
        'amount_words': amount_words,
        'vat_summary': vat_summary,
        'pdf_item_groups': build_pdf_item_groups(estimate),
        'is_pdf': True,
    }


@login_required
def estimate_pdf(request, pk):
    """
    Customer-facing quotation PDF (HTML for print / WeasyPrint): heading QUOTATION, quotation wording on document.
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
        'document_heading': 'QUOTATION',
        'document_number': estimate.display_estimate_number,
        'page_title': f'Quotation — {estimate.display_estimate_number}',
        'print_button_label': 'Print quotation',
        'show_pdf_status': True,
        'pdf_variant': 'quotation',
        'pdf_details_heading': 'Quotation details',
        'pdf_date_label': 'Quotation date',
    })
    return render(request, 'sales/estimate_pdf.html', context)


@login_required
def estimate_pdf_download(request, pk):
    """Download quotation as a PDF file (WeasyPrint)."""
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

    from apps.core.visibility import user_can_access_estimate

    if not user_can_access_estimate(request.user, estimate):
        messages.error(request, 'You do not have permission to view this estimate.')
        return redirect('sales:estimate_list')

    try:
        pdf_bytes, err = render_estimate_quotation_pdf_bytes(request, estimate)
    except Exception as exc:
        messages.error(request, f'Could not generate PDF: {exc}')
        return redirect('sales:estimate_pdf', pk=estimate.pk)

    if not pdf_bytes:
        messages.error(request, err or 'Could not generate PDF.')
        return redirect('sales:estimate_pdf', pk=estimate.pk)

    safe_name = ''.join(
        c for c in estimate.display_estimate_number if c.isalnum() or c in ('-', '_')
    ) or str(estimate.pk)
    from io import BytesIO

    from django.http import FileResponse

    filename = f'Quotation_{safe_name}.pdf'
    return FileResponse(
        BytesIO(pdf_bytes),
        as_attachment=True,
        filename=filename,
        content_type='application/pdf',
    )


def _get_estimate_revision_snapshot(request, pk, snapshot_id):
    """Load estimate + revision snapshot with view permission checks."""
    estimate = get_object_or_404(Estimate.objects.filter(is_active=True), pk=pk)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'view')):
        messages.error(request, 'Permission denied.')
        return None, None
    from apps.core.visibility import user_can_access_estimate

    if not user_can_access_estimate(request.user, estimate):
        messages.error(request, 'You do not have permission to view this estimate.')
        return None, None

    snapshot = get_object_or_404(
        EstimateRevisionSnapshot.objects.filter(estimate=estimate),
        pk=snapshot_id,
    )
    return estimate, snapshot


@login_required
def estimate_revision_detail(request, pk, snapshot_id):
    """Read-only view of a saved revision (line items and totals from snapshot JSON)."""
    estimate, snapshot = _get_estimate_revision_snapshot(request, pk, snapshot_id)
    if snapshot is None:
        return redirect('sales:estimate_list')

    from .revision_snapshot_render import revision_snapshot_detail_context

    context = {
        'estimate': estimate,
        'snapshot': snapshot,
        **revision_snapshot_detail_context(snapshot),
    }
    return render(request, 'sales/estimate_revision_snapshot.html', context)


@login_required
def estimate_revision_pdf(request, pk, snapshot_id):
    """View PDF for a revision; generates from snapshot data if not yet stored."""
    estimate, snapshot = _get_estimate_revision_snapshot(request, pk, snapshot_id)
    if snapshot is None:
        return redirect('sales:estimate_list')

    from .revision_snapshot_render import ensure_revision_snapshot_pdf

    if not ensure_revision_snapshot_pdf(request, snapshot):
        messages.warning(
            request,
            'Could not generate PDF for this revision. Open View for the saved details.',
        )
        return redirect('sales:estimate_revision_detail', pk=estimate.pk, snapshot_id=snapshot.pk)

    from django.http import FileResponse

    snapshot.refresh_from_db()
    return FileResponse(
        snapshot.pdf_file.open('rb'),
        content_type='application/pdf',
        as_attachment=False,
        filename=snapshot.pdf_file.name.rsplit('/', 1)[-1],
    )


@login_required
def estimate_proforma_pdf(request, pk):
    """Legacy full-estimate proforma; won quotations use partial proforma flow instead."""
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

    if estimate.status == 'quotation_won':
        messages.info(
            request,
            'Use Create Proforma Invoice on a won quotation to bill a percentage or fixed amount.',
        )
        return redirect('sales:estimate_detail', pk=pk)

    proforma_number = estimate.display_proforma_number
    context = _build_estimate_pdf_context(request, estimate)
    context.update({
        'document_heading': 'PROFORMA INVOICE',
        'document_number': proforma_number,
        'page_title': f'Proforma invoice — {proforma_number}',
        'print_button_label': 'Print proforma invoice',
        'show_pdf_status': False,
        'pdf_variant': 'proforma',
        'pdf_details_heading': 'Proforma invoice details',
        'pdf_date_label': 'Date',
    })
    return render(request, 'sales/estimate_pdf.html', context)


@login_required
@require_POST
def estimate_proforma_create(request, pk):
    """Create a partial proforma invoice from a won quotation (AJAX from modal)."""
    estimate = get_object_or_404(Estimate.objects.filter(is_active=True), pk=pk)

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'view')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    if estimate.status != 'quotation_won':
        return JsonResponse(
            {'ok': False, 'error': 'Proforma invoices can only be created for won quotations.'},
            status=400,
        )

    estimate.calculate_totals()
    estimate.refresh_from_db()

    from .proforma_form import apply_proforma_form_data

    proforma = EstimateProformaInvoice(
        estimate=estimate,
        proforma_number=EstimateProformaInvoice.allocate_number(estimate),
        created_by=request.user,
    )
    try:
        apply_proforma_form_data(proforma, estimate, request.POST)
    except ValueError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect('sales:estimate_detail', pk=pk)

    try:
        proforma.save()
    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': f'Could not save proforma: {exc}'}, status=500)
        messages.error(request, f'Could not save proforma: {exc}')
        return redirect('sales:estimate_detail', pk=pk)

    pdf_url = reverse('sales:estimate_proforma_invoice_pdf', kwargs={'pk': pk, 'proforma_pk': proforma.pk})
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'pdf_url': pdf_url, 'proforma_number': proforma.proforma_number})
    return redirect('sales:estimate_proforma_invoice_pdf', pk=pk, proforma_pk=proforma.pk)


@login_required
def estimate_proforma_edit(request, pk, proforma_pk):
    """Edit an existing proforma invoice; save redirects to PDF."""
    estimate = get_object_or_404(Estimate.objects.filter(is_active=True), pk=pk)
    proforma = get_object_or_404(EstimateProformaInvoice, pk=proforma_pk, estimate=estimate)

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_detail', pk=pk)

    if estimate.status != 'quotation_won':
        messages.error(request, 'Proforma invoices apply to won quotations only.')
        return redirect('sales:estimate_detail', pk=pk)

    if request.method == 'POST':
        estimate.calculate_totals()
        estimate.refresh_from_db()
        from .proforma_form import apply_proforma_form_data

        try:
            apply_proforma_form_data(proforma, estimate, request.POST)
            proforma.save()
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Proforma {proforma.proforma_number} updated.')
            return redirect('sales:estimate_proforma_invoice_pdf', pk=pk, proforma_pk=proforma.pk)

    from .proforma_calculation import proforma_billing_limits

    billing_limits = proforma_billing_limits(estimate, exclude_proforma_pk=proforma.pk)
    return render(request, 'sales/proforma_invoice_edit.html', {
        'title': f'Edit {proforma.proforma_number}',
        'estimate': estimate,
        'proforma': proforma,
        'billing_limits': billing_limits,
    })


@login_required
def estimate_proforma_invoice_pdf(request, pk, proforma_pk):
    """Print/PDF for a partial proforma invoice created from a won quotation."""
    items_qs = EstimateItem.objects.select_related('inventory_item', 'tax_code').order_by('sort_order', 'id')
    estimate = get_object_or_404(
        Estimate.objects.select_related('customer', 'assigned_to', 'project').prefetch_related(
            Prefetch('items', queryset=items_qs)
        ),
        pk=pk,
    )
    proforma = get_object_or_404(EstimateProformaInvoice, pk=proforma_pk, estimate=estimate)

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'sales', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_list')

    context = _build_estimate_pdf_context(request, estimate, proforma_invoice=proforma)
    context.update({
        'document_heading': 'PROFORMA INVOICE',
        'document_number': proforma.proforma_number,
        'page_title': f'Proforma invoice — {proforma.proforma_number}',
        'print_button_label': 'Print proforma invoice',
        'show_pdf_status': False,
        'pdf_variant': 'proforma',
        'pdf_details_heading': 'Proforma invoice details',
        'pdf_date_label': 'Date',
        'proforma_single_line': True,
        'proforma_can_edit': (
            request.user.is_superuser
            or PermissionChecker.has_permission(request.user, 'sales', 'edit')
        ),
        'proforma_edit_url': reverse(
            'sales:estimate_proforma_edit', kwargs={'pk': pk, 'proforma_pk': proforma_pk}
        ),
    })
    return render(request, 'sales/estimate_pdf.html', context)


@login_required
@require_POST
def estimate_send_email(request, pk):
    """Email estimate: JSON API; attaches quotation PDF (same document as Estimate → PDF)."""

    from apps.purchase.email_outbound import (
        company_outgoing_from_email,
        get_smtp_connection_or_default,
        validate_cc_addresses,
        validate_to_addresses,
    )

    items_qs = EstimateItem.objects.select_related('inventory_item', 'tax_code').order_by('sort_order', 'id')
    estimate = get_object_or_404(
        Estimate.objects.filter(is_active=True)
        .select_related('customer', 'assigned_to', 'project')
        .prefetch_related(Prefetch('items', queryset=items_qs)),
        pk=pk,
    )

    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'sales', 'edit')
    ):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

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
    pdf, pdf_err = render_estimate_quotation_pdf_bytes(request, estimate)
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
    safe_name = ''.join(
        c for c in estimate.display_estimate_number if c.isalnum() or c in ('-', '_')
    ) or str(estimate.pk)
    msg.attach(f'Quotation_{safe_name}.pdf', pdf, 'application/pdf')

    try:
        msg.send(fail_silently=False)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Could not send email: {exc}'}, status=502)

    return JsonResponse({'ok': True, 'message': 'Email sent.'})


@login_required
def estimate_set_status(request, pk):
    """POST: update estimate status from list (inline). Fields: status, next (optional relative URL)."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    estimate = get_object_or_404(Estimate, pk=pk)

    status = request.POST.get('status')
    valid_statuses = [c[0] for c in Estimate.STATUS_CHOICES]
    if status not in valid_statuses:
        messages.error(request, 'Invalid status.')
        return redirect('sales:estimate_list')

    from .approval_rules import user_can_approve_estimate_status

    can_change_status = (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'sales', 'edit')
    )
    if status in ('approved', 'rejected') and user_can_approve_estimate_status(request.user, estimate):
        can_change_status = True

    if not can_change_status:
        messages.error(request, 'Permission denied.')
        return redirect('sales:estimate_list')

    if status in ('approved', 'rejected'):
        if not user_can_approve_estimate_status(request.user, estimate):
            messages.error(request, 'Only the configured estimate approver can approve or reject this estimate.')
            next_url = request.POST.get('next', '').strip()
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect('sales:estimate_detail', pk=pk)

    from .approval_rules import estimate_status_change_allowed

    if not estimate_status_change_allowed(
        estimate.status, status, user=request.user, estimate=estimate
    ):
        if status in ('quotation_won', 'quotation_lost'):
            from .approval_rules import user_can_mark_estimate_won_lost

            if estimate.status not in ('approved', 'under_negotiation'):
                messages.error(
                    request,
                    'Mark estimate won or lost only when the estimate is approved or under negotiation.',
                )
            elif not user_can_mark_estimate_won_lost(request.user, estimate):
                messages.error(
                    request,
                    'Only the salesperson assigned to this estimate can mark it won or lost.',
                )
            else:
                messages.error(request, 'That status change is not allowed.')
        elif status == 'draft' and estimate.status == 'quotation_won':
            messages.error(request, 'A won quotation cannot be reverted to draft.')
        else:
            messages.error(request, 'That status change is not allowed.')
        next_url = request.POST.get('next', '').strip()
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect('sales:estimate_detail', pk=pk)

    old_status = estimate.status
    rejection_reason = (request.POST.get('rejection_reason') or '').strip()

    from .estimate_status_change import (
        after_estimate_status_saved,
        apply_estimate_status_fields,
        validate_status_rejection_reason,
    )

    reason_error = validate_status_rejection_reason(status, old_status, rejection_reason)
    if reason_error:
        messages.error(request, reason_error)
        next_url = request.POST.get('next', '').strip()
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect('sales:estimate_detail', pk=pk)

    update_fields = apply_estimate_status_fields(
        estimate,
        new_status=status,
        old_status=old_status,
        user=request.user,
        rejection_reason=rejection_reason,
    )
    estimate.save(update_fields=update_fields)
    after_estimate_status_saved(
        estimate,
        new_status=status,
        old_status=old_status,
        user=request.user,
        rejection_reason=rejection_reason,
    )

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
        'minimum_selling_price': str(item.get_effective_minimum_selling_price()),
        'maximum_selling_price': str(item.get_effective_maximum_selling_price()),
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
        context['default_tax_code'] = get_default_estimate_csv_tax_code()
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
        context['default_tax_code'] = get_default_estimate_csv_tax_code()
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
