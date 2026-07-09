"""
Contracts — list, create, metrics, charts.
"""
from datetime import timedelta

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import DetailView, ListView, UpdateView

from apps.core.mixins import PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.crm.models import Customer

from .forms import ContractDocumentExpiryFormSet, ContractForm
from .models import Contract, ContractAttachment, ContractDocumentExpiry, ContractType
from .ppm_schedule import parse_visit_dates_from_post, sync_contract_visits, visit_dates_for_contract


def _ppm_visit_dates_context(contract=None, request=None, planned=None):
    if request and request.method == 'POST':
        if planned is None:
            try:
                planned = int(request.POST.get('planned_visits', 0))
            except (TypeError, ValueError):
                planned = 0
        posted = [
            (request.POST.get(f'ppm_visit_date_{i}') or '').strip()
            for i in range(1, (planned or 0) + 1)
        ]
        if any(posted):
            return posted
    if not contract or not contract.pk:
        return []
    return [d.isoformat() for d in visit_dates_for_contract(contract)]


def _maybe_sync_ppm_schedule(contract, request, visit_dates=None) -> None:
    result = sync_contract_visits(contract, visit_dates)
    parts = []
    if result['ppm_created']:
        parts.append(f'{result["ppm_created"]} PPM inspection{"s" if result["ppm_created"] != 1 else ""} created')
    if result['ops_created']:
        parts.append(
            f'{result["ops_created"]} operations draft{"s" if result["ops_created"] != 1 else ""} created (pending, unassigned)'
        )
    if result['ppm_updated'] or result['ops_updated']:
        parts.append('existing visit schedules updated')
    if parts:
        messages.info(request, '; '.join(parts) + '.')


def _renewal_initial_dates(source: Contract):
    """Suggest the next AMC period after the source contract ends."""
    today = timezone.now().date()
    duration = source.end_date - source.start_date
    if duration.days < 0:
        duration = timedelta(days=365)
    start = source.end_date + timedelta(days=1)
    if start < today:
        start = today
    end = start + duration
    return start, end


def _contract_form_kwargs(request, instance=None, initial=None):
    kwargs = {'user': request.user}
    if instance is not None:
        kwargs['instance'] = instance
    if initial is not None:
        kwargs['initial'] = initial
    return kwargs


def _strip_new_type_names(request):
    return [x.strip() for x in request.POST.getlist('new_type_name') if x.strip()]


def _persist_contract_types_and_attachments(request, contract, selected_types_queryset, extra_names):
    type_ids = list(selected_types_queryset.values_list('pk', flat=True))
    for name in extra_names:
        ct, _ = ContractType.objects.get_or_create(name=name[:120])
        type_ids.append(ct.pk)
    contract.contract_types.set(type_ids)
    for f in request.FILES.getlist('attachments'):
        ContractAttachment.objects.create(
            contract=contract,
            file=f,
            original_name=getattr(f, 'name', '')[:255],
        )


class ContractListView(PermissionRequiredMixin, ListView):
    model = Contract
    template_name = 'contracts/contract_list.html'
    context_object_name = 'contracts'
    module_name = 'contracts'
    permission_type = 'view'
    paginate_by = 25

    def get_queryset(self):
        qs = Contract.objects.filter(is_active=True).select_related(
            'customer', 'salesperson'
        ).prefetch_related(
            'contract_types'
        )
        search = self.request.GET.get('search')
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(contract_number__icontains=search)
                | Q(customer__name__icontains=search)
                | Q(customer__company__icontains=search)
            )
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        horizon = today + timedelta(days=30)

        all_c = Contract.objects.filter(is_active=True)

        ctx['metric_active'] = all_c.filter(start_date__lte=today, end_date__gte=today).count()
        ctx['metric_expired'] = all_c.filter(end_date__lt=today).count()
        ctx['metric_expiring'] = all_c.filter(end_date__gte=today, end_date__lte=horizon).count()
        ctx['metric_recent'] = all_c.filter(created_at__date__gte=week_ago).count()

        type_rows = []
        for ct in ContractType.objects.filter(is_active=True).order_by('name'):
            linked = ct.contracts.filter(is_active=True)
            total = linked.aggregate(s=Sum('contract_value'))['s'] or 0
            type_rows.append(
                {
                    'name': ct.name,
                    'count': linked.count(),
                    'value': float(total),
                }
            )
        ctx['type_chart_data'] = type_rows
        ctx['today'] = today

        document_expiries = (
            ContractDocumentExpiry.objects.filter(
                is_active=True,
                contract__is_active=True,
            )
            .select_related('contract', 'contract__customer')
            .order_by('expiry_date', 'document_name')
        )
        ctx['document_expiries'] = document_expiries
        ctx['metric_doc_expired'] = document_expiries.filter(expiry_date__lt=today).count()
        ctx['metric_doc_due_soon'] = sum(1 for doc in document_expiries if doc.reminder_due() and not doc.is_expired)

        ctx['title'] = 'Contracts'
        ctx['form'] = ContractForm(**_contract_form_kwargs(self.request))
        ctx['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'contracts', 'create'
        )
        ctx['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'contracts', 'delete'
        )
        ctx['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'contracts', 'edit'
        )
        ctx['customers_for_inline'] = Customer.objects.filter(is_active=True).order_by('name', 'company')
        ctx['contract_types_for_inline'] = ContractType.objects.filter(is_active=True).order_by('name')
        ctx['contract_status_choices'] = Contract.STATUS_CHOICES
        ctx['ppm_visit_dates'] = []
        return ctx

    def post(self, request, *args, **kwargs):
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'contracts', 'create')):
            messages.error(request, 'You do not have permission to create contracts.')
            return redirect('contracts:contract_list')

        form = ContractForm(request.POST, request.FILES, **_contract_form_kwargs(request))
        extra_names = _strip_new_type_names(request)

        if not form.is_valid():
            self.object_list = self.get_queryset()
            context = self.get_context_data()
            context['form'] = form
            context['ppm_visit_dates'] = _ppm_visit_dates_context(request=request)
            return self.render_to_response(context)

        visit_dates, visit_errors = parse_visit_dates_from_post(
            request.POST,
            form.cleaned_data['planned_visits'],
            form.cleaned_data['start_date'],
            form.cleaned_data['end_date'],
        )
        if visit_errors:
            for err in visit_errors:
                form.add_error(None, err)
            self.object_list = self.get_queryset()
            context = self.get_context_data()
            context['form'] = form
            context['ppm_visit_dates'] = _ppm_visit_dates_context(
                request=request,
                planned=form.cleaned_data['planned_visits'],
            )
            return self.render_to_response(context)

        selected = form.cleaned_data['contract_types']
        if not selected.exists() and not extra_names:
            messages.error(request, 'Select at least one contract type or add a new type in the fields below.')
            self.object_list = self.get_queryset()
            context = self.get_context_data()
            context['form'] = form
            return self.render_to_response(context)

        contract = form.save(commit=False)
        contract.save()
        _persist_contract_types_and_attachments(request, contract, selected, extra_names)
        _maybe_sync_ppm_schedule(contract, request, visit_dates)

        messages.success(request, f'Contract {contract.contract_number} created.')
        return redirect('contracts:contract_detail', pk=contract.pk)


class ContractDetailView(PermissionRequiredMixin, DetailView):
    model = Contract
    template_name = 'contracts/contract_detail.html'
    context_object_name = 'contract'
    module_name = 'contracts'
    permission_type = 'view'

    def get_queryset(self):
        return (
            Contract.objects.filter(is_active=True)
            .select_related('customer', 'salesperson', 'source_estimate', 'project', 'created_by', 'updated_by')
            .prefetch_related('contract_types', 'attachments', 'document_expiries')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.now().date()
        ctx['today'] = today
        ctx['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'contracts', 'edit'
        )
        ctx['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'contracts', 'delete'
        )
        ctx['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'contracts', 'create'
        )
        ctx['document_expiries'] = self.object.document_expiries.filter(is_active=True).order_by(
            'expiry_date', 'document_name'
        )
        ctx['contract_expiring_within_30'] = self.object.is_expiring_within(30)
        ctx['ppm_inspection_count'] = self.object.inspections.filter(
            link_type='amc', is_active=True
        ).count()
        ctx['planned_visit_dates'] = visit_dates_for_contract(self.object)
        if 'doc_formset' in kwargs:
            ctx['doc_formset'] = kwargs['doc_formset']
        elif ctx['can_edit']:
            ctx['doc_formset'] = ContractDocumentExpiryFormSet(instance=self.object)
        return ctx

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') != 'save_document_expiries':
            return HttpResponseNotAllowed(['GET'])

        self.object = self.get_object()
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'contracts', 'edit')):
            messages.error(request, 'Permission denied.')
            return redirect('contracts:contract_detail', pk=self.object.pk)

        formset = ContractDocumentExpiryFormSet(request.POST, instance=self.object)
        if formset.is_valid():
            formset.save()
            messages.success(request, 'Document expiry reminders updated.')
            return redirect('contracts:contract_detail', pk=self.object.pk)

        messages.error(request, 'Please correct the document expiry errors below.')
        context = self.get_context_data(doc_formset=formset)
        return self.render_to_response(context)


class ContractUpdateView(UpdatePermissionMixin, UpdateView):
    model = Contract
    form_class = ContractForm
    template_name = 'contracts/contract_form.html'
    module_name = 'contracts'

    def get_queryset(self):
        return Contract.objects.filter(is_active=True).select_related(
            'customer', 'salesperson', 'source_estimate', 'project'
        ).prefetch_related('contract_types')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse_lazy('contracts:contract_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit contract — {self.object.contract_number}'
        ctx['is_edit'] = True
        ctx['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'contracts', 'create'
        )
        if self.request.POST:
            ctx['doc_formset'] = ContractDocumentExpiryFormSet(self.request.POST, instance=self.object)
        else:
            ctx['doc_formset'] = ContractDocumentExpiryFormSet(instance=self.object)
        ctx['ppm_visit_dates'] = _ppm_visit_dates_context(self.object, self.request)
        return ctx

    def form_valid(self, form):
        extra_names = _strip_new_type_names(self.request)
        selected = form.cleaned_data['contract_types']
        if not selected.exists() and not extra_names:
            form.add_error(None, 'Select at least one contract type or add a new type.')
            return self.form_invalid(form)

        doc_formset = ContractDocumentExpiryFormSet(self.request.POST, instance=self.object)
        if not doc_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form, doc_formset=doc_formset))

        visit_dates, visit_errors = parse_visit_dates_from_post(
            self.request.POST,
            form.cleaned_data['planned_visits'],
            form.cleaned_data['start_date'],
            form.cleaned_data['end_date'],
        )
        if visit_errors:
            for err in visit_errors:
                form.add_error(None, err)
            return self.render_to_response(self.get_context_data(form=form, doc_formset=doc_formset))

        contract = form.save(commit=False)
        contract.save()
        _persist_contract_types_and_attachments(self.request, contract, selected, extra_names)
        doc_formset.instance = contract
        doc_formset.save()
        _maybe_sync_ppm_schedule(contract, self.request, visit_dates)
        messages.success(self.request, f'Contract {contract.contract_number} updated.')
        return redirect(self.get_success_url())


@login_required
def contract_renew(request, pk):
    """Create a renewed AMC contract from an existing one."""
    source = get_object_or_404(
        Contract.objects.filter(is_active=True).select_related('customer', 'salesperson').prefetch_related(
            'contract_types'
        ),
        pk=pk,
    )
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'contracts', 'create')):
        messages.error(request, 'You do not have permission to renew contracts.')
        return redirect('contracts:contract_detail', pk=source.pk)

    start_date, end_date = _renewal_initial_dates(source)
    initial = {
        'customer': source.customer_id,
        'salesperson': source.salesperson_id or (
            source.customer.assigned_salesperson_id if source.customer_id else None
        ),
        'amc_category': source.amc_category,
        'service_site': source.service_site,
        'name': source.name,
        'contract_value': source.contract_value,
        'planned_visits': source.planned_visits,
        'start_date': start_date,
        'end_date': end_date,
        'status': 'upcoming' if start_date > timezone.now().date() else 'active',
        'remind_before_days': source.remind_before_days or 30,
        'description': source.description,
        'terms_and_conditions': source.terms_and_conditions,
        'contract_types': list(source.contract_types.values_list('pk', flat=True)),
    }

    if request.method == 'POST':
        form = ContractForm(request.POST, request.FILES, **_contract_form_kwargs(request, initial=initial))
        extra_names = _strip_new_type_names(request)
        if form.is_valid():
            selected = form.cleaned_data['contract_types']
            if not selected.exists() and not extra_names:
                form.add_error(None, 'Select at least one contract type or add a new type.')
            else:
                visit_dates, visit_errors = parse_visit_dates_from_post(
                    request.POST,
                    form.cleaned_data['planned_visits'],
                    form.cleaned_data['start_date'],
                    form.cleaned_data['end_date'],
                )
                if visit_errors:
                    for err in visit_errors:
                        form.add_error(None, err)
                else:
                    with transaction.atomic():
                        contract = form.save(commit=False)
                        contract.save()
                        _persist_contract_types_and_attachments(request, contract, selected, extra_names)
                    _maybe_sync_ppm_schedule(contract, request, visit_dates)
                    messages.success(
                        request,
                        f'Renewed AMC as {contract.contract_number} (from {source.contract_number}).',
                    )
                    return redirect('contracts:contract_detail', pk=contract.pk)
    else:
        form = ContractForm(**_contract_form_kwargs(request, initial=initial))

    return render(
        request,
        'contracts/contract_renew.html',
        {
            'form': form,
            'source': source,
            'title': f'Renew AMC — {source.contract_number}',
            'ppm_visit_dates': _ppm_visit_dates_context(source, request),
        },
    )


@login_required
def contract_pdf(request, pk):
    """Printable contract (HTML for print), layout aligned with estimate PDF."""
    contract = get_object_or_404(
        Contract.objects.select_related('customer', 'salesperson').prefetch_related('contract_types'),
        pk=pk,
        is_active=True,
    )
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'contracts', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('contracts:contract_list')

    from apps.settings_app.models import CompanySettings

    company = CompanySettings.get_settings()
    logo_absolute_url = ''
    if company.logo:
        logo_absolute_url = request.build_absolute_uri(company.logo.url)

    return render(
        request,
        'contracts/contract_pdf.html',
        {
            'contract': contract,
            'company': company,
            'logo_absolute_url': logo_absolute_url,
            'page_title': f'Contract — {contract.contract_number}',
            'print_button_label': 'Print contract',
        },
    )


@login_required
def contract_delete(request, pk):
    if request.method != 'POST':
        return redirect('contracts:contract_list')
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'contracts', 'delete')):
        messages.error(request, 'Permission denied.')
        return redirect('contracts:contract_list')
    c = get_object_or_404(Contract, pk=pk, is_active=True)
    c.is_active = False
    c.save(update_fields=['is_active'])
    messages.success(request, 'Contract removed.')
    return redirect('contracts:contract_list')


def _safe_next_url(request):
    next_url = request.POST.get('next', '').strip()
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return next_url
    return None


@login_required
def contract_inline_update(request, pk):
    """POST: update one field from the contract list row."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    contract = get_object_or_404(Contract, pk=pk, is_active=True)

    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'contracts', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('contracts:contract_list')

    next_url = _safe_next_url(request)
    status_choices = dict(Contract.STATUS_CHOICES)
    updated = False

    if 'name' in request.POST:
        name = request.POST.get('name', '').strip()[:255]
        if name and name != contract.name:
            contract.name = name
            contract.save(update_fields=['name'])
            updated = True
        elif not name:
            messages.error(request, 'Name cannot be empty.')

    if 'customer' in request.POST:
        raw = request.POST.get('customer', '').strip()
        if raw == '':
            if contract.customer_id is not None:
                contract.customer = None
                contract.save(update_fields=['customer'])
                updated = True
        else:
            try:
                cid = int(raw)
            except (TypeError, ValueError):
                messages.error(request, 'Invalid customer.')
            else:
                cust = Customer.objects.filter(pk=cid, is_active=True).first()
                if cust and contract.customer_id != cid:
                    contract.customer = cust
                    contract.save(update_fields=['customer'])
                    updated = True
                elif not cust:
                    messages.error(request, 'Invalid customer.')

    if 'contract_value' in request.POST:
        raw = request.POST.get('contract_value', '').strip()
        try:
            val = Decimal(raw.replace(',', ''))
        except (InvalidOperation, TypeError, AttributeError):
            messages.error(request, 'Invalid value.')
        else:
            if val < 0:
                messages.error(request, 'Value cannot be negative.')
            elif val != contract.contract_value:
                contract.contract_value = val
                contract.save(update_fields=['contract_value'])
                updated = True

    if 'start_date' in request.POST:
        d = parse_date(request.POST.get('start_date', ''))
        if not d:
            messages.error(request, 'Invalid start date.')
        elif d > contract.end_date:
            messages.error(request, 'Start date must be on or before end date.')
        elif d != contract.start_date:
            contract.start_date = d
            contract.save(update_fields=['start_date'])
            updated = True

    if 'end_date' in request.POST:
        d = parse_date(request.POST.get('end_date', ''))
        if not d:
            messages.error(request, 'Invalid end date.')
        elif d < contract.start_date:
            messages.error(request, 'End date must be on or after start date.')
        elif d != contract.end_date:
            contract.end_date = d
            contract.save(update_fields=['end_date'])
            updated = True

    if request.POST.get('update_contract_types'):
        raw_ids = request.POST.getlist('contract_types')
        ids = []
        for x in raw_ids:
            if str(x).isdigit():
                ids.append(int(x))
        valid = set(ContractType.objects.filter(pk__in=ids, is_active=True).values_list('pk', flat=True))
        ids = [i for i in ids if i in valid]
        current = set(contract.contract_types.values_list('pk', flat=True))
        if set(ids) != current:
            contract.contract_types.set(ids)
            updated = True

    if 'status' in request.POST:
        val = request.POST.get('status', '').strip()
        if val in status_choices and val != contract.status:
            contract.status = val
            contract.save(update_fields=['status'])
            updated = True

    if updated:
        messages.success(request, f'Contract {contract.contract_number} updated.')

    if next_url:
        return redirect(next_url)
    return redirect('contracts:contract_list')
