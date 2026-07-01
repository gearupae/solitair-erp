import logging
from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import F, Sum, Q, Value
from django.db.models.functions import Greatest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView

from apps.core.mixins import (
    PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin,
)
from apps.core.utils import PermissionChecker
from .models import (
    AssetCategory, FixedAsset, AssetDepreciation, DepreciationBatchRun,
    EquipmentAllocation, EquipmentMaintenanceLog,
)
from .forms import (
    AssetCategoryForm, FixedAssetForm, DisposalForm,
    AssetOperationalForm, EquipmentAllocationForm, EquipmentReturnForm,
    EquipmentTransferForm, EquipmentMaintenanceForm,
)
from . import equipment_services

logger = logging.getLogger(__name__)


# ============ ASSET CATEGORIES ============

class AssetCategoryListView(PermissionRequiredMixin, ListView):
    model = AssetCategory
    template_name = 'assets/category_list.html'
    context_object_name = 'categories'
    module_name = 'assets'
    permission_type = 'view'
    
    def get_queryset(self):
        return AssetCategory.objects.filter(is_active=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Asset Categories'
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'assets', 'create')
        return context


class AssetCategoryCreateView(CreatePermissionMixin, CreateView):
    model = AssetCategory
    form_class = AssetCategoryForm
    template_name = 'assets/category_form.html'
    success_url = reverse_lazy('assets:category_list')
    module_name = 'assets'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Add Asset Category'
        return context


class AssetCategoryUpdateView(UpdatePermissionMixin, UpdateView):
    model = AssetCategory
    form_class = AssetCategoryForm
    template_name = 'assets/category_form.html'
    success_url = reverse_lazy('assets:category_list')
    module_name = 'assets'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Category: {self.object.name}'
        return context


# ============ FIXED ASSETS ============

class FixedAssetListView(PermissionRequiredMixin, ListView):
    model = FixedAsset
    template_name = 'assets/asset_list.html'
    context_object_name = 'assets'
    module_name = 'assets'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = FixedAsset.objects.filter(is_active=True).select_related('category', 'vendor')
        
        # Filters
        status = self.request.GET.get('status')
        category = self.request.GET.get('category')
        
        if status:
            queryset = queryset.filter(status=status)
        if category:
            queryset = queryset.filter(category_id=category)
        
        return queryset

    def get(self, request, *args, **kwargs):
        if request.GET.get('format') == 'excel':
            return self._export_excel()
        return super().get(request, *args, **kwargs)

    def _export_excel(self):
        from apps.finance.excel_exports import export_asset_register
        from apps.finance.models import Account, JournalEntryLine
        from django.db.models.functions import Coalesce

        qs = self.get_queryset().order_by('asset_number')
        today = date.today()

        asset_data = []
        for a in qs:
            asset_data.append({
                'asset_number': a.asset_number,
                'name': a.name,
                'category': a.category.name if a.category else '',
                'status': a.get_status_display(),
                'acquisition_date': a.acquisition_date,
                'cost': a.acquisition_cost,
                'accum_depreciation': a.accumulated_depreciation,
                'book_value': a.book_value,
                'method': a.get_depreciation_method_display(),
                'useful_life': a.useful_life_years,
                'has_journal': a.acquisition_journal_id is not None,
            })

        fa_cats = ['fixed_furniture', 'fixed_it', 'fixed_vehicles', 'fixed_other']
        fa_gl = Account.objects.filter(account_type='asset', is_active=True, account_category__in=fa_cats)
        ad_gl = Account.objects.filter(account_type='asset', is_active=True, account_category='accum_depreciation')

        fa_agg = JournalEntryLine.objects.filter(
            account__in=fa_gl, journal_entry__status='posted'
        ).exclude(journal_entry__reference__startswith='TEST-CF-').aggregate(
            d=Coalesce(Sum('debit'), Decimal('0')), c=Coalesce(Sum('credit'), Decimal('0'))
        )
        ad_agg = JournalEntryLine.objects.filter(
            account__in=ad_gl, journal_entry__status='posted'
        ).exclude(journal_entry__reference__startswith='TEST-CF-').aggregate(
            d=Coalesce(Sum('debit'), Decimal('0')), c=Coalesce(Sum('credit'), Decimal('0'))
        )

        reg_cost = sum(a['cost'] for a in asset_data)
        reg_accum = sum(a['accum_depreciation'] for a in asset_data)
        gl_cost = fa_agg['d'] - fa_agg['c']
        gl_accum = ad_agg['c'] - ad_agg['d']

        reconciliation = {
            'register_cost': reg_cost,
            'gl_cost': gl_cost,
            'register_accum': reg_accum,
            'gl_accum': gl_accum,
            'register_nbv': reg_cost - reg_accum,
            'gl_nbv': gl_cost - gl_accum,
        }

        return export_asset_register(asset_data, reconciliation, today.isoformat())
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Fixed Assets'
        context['categories'] = AssetCategory.objects.filter(is_active=True)
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'assets', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'assets', 'edit')
        
        # Summary metrics
        assets = FixedAsset.objects.filter(is_active=True)
        context['total_assets'] = assets.count()
        context['total_cost'] = assets.aggregate(total=Sum('acquisition_cost'))['total'] or Decimal('0.00')
        context['total_book_value'] = assets.aggregate(total=Sum('book_value'))['total'] or Decimal('0.00')
        context['active_assets'] = assets.filter(status='active').count()
        
        return context


class FixedAssetDetailView(PermissionRequiredMixin, DetailView):
    model = FixedAsset
    template_name = 'assets/asset_detail.html'
    context_object_name = 'asset'
    module_name = 'assets'
    permission_type = 'view'
    
    def get_queryset(self):
        return FixedAsset.objects.filter(is_active=True).select_related(
            'category', 'vendor', 'custodian', 'acquisition_journal', 'disposal_journal'
        ).prefetch_related(
            'allocations__project',
            'movement_logs',
            'maintenance_logs',
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Asset: {self.object.asset_number}'
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'assets', 'edit')
        context['depreciation_records'] = self.object.depreciation_records.all()[:12]
        context.update(equipment_services.asset_allocation_context(self.object))
        context['operational_form'] = AssetOperationalForm(instance=self.object)
        context['allocation_form'] = EquipmentAllocationForm()
        context['return_form'] = EquipmentReturnForm()
        if context.get('active_allocation'):
            context['transfer_form'] = EquipmentTransferForm(
                exclude_project=context['active_allocation'].project,
            )
        else:
            context['transfer_form'] = EquipmentTransferForm()
        context['maintenance_form'] = EquipmentMaintenanceForm()
        return context

class FixedAssetCreateView(CreatePermissionMixin, CreateView):
    model = FixedAsset
    form_class = FixedAssetForm
    template_name = 'assets/asset_form.html'
    module_name = 'assets'
    
    def get_success_url(self):
        return reverse_lazy('assets:asset_detail', kwargs={'pk': self.object.pk})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Add Fixed Asset'
        return context


class FixedAssetUpdateView(UpdatePermissionMixin, UpdateView):
    model = FixedAsset
    form_class = FixedAssetForm
    template_name = 'assets/asset_form.html'
    module_name = 'assets'
    
    def get_queryset(self):
        return FixedAsset.objects.filter(is_active=True, status='draft')
    
    def get_success_url(self):
        return reverse_lazy('assets:asset_detail', kwargs={'pk': self.object.pk})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Asset: {self.object.asset_number}'
        return context


@login_required
def asset_activate(request, pk):
    """Activate asset and post acquisition journal."""
    asset = get_object_or_404(FixedAsset, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=pk)
    
    try:
        journal = asset.activate(user=request.user)
        messages.success(request, f'Asset activated. Acquisition journal: {journal.entry_number}')
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f'Error activating asset: {e}')
    
    return redirect('assets:asset_detail', pk=pk)


@login_required
def asset_depreciate(request, pk):
    """Run depreciation for a single asset."""
    asset = get_object_or_404(FixedAsset, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=pk)
    
    depreciation_date = date.today().replace(day=1)  # First of current month
    
    try:
        journal = asset.run_depreciation(depreciation_date, user=request.user)
        messages.success(request, f'Depreciation recorded. Journal: {journal.entry_number}')
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f'Error running depreciation: {e}')
    
    return redirect('assets:asset_detail', pk=pk)


@login_required
def asset_dispose(request, pk):
    """Dispose of an asset."""
    asset = get_object_or_404(FixedAsset, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=pk)
    
    if request.method == 'POST':
        form = DisposalForm(request.POST)
        if form.is_valid():
            try:
                journal = asset.dispose(
                    disposal_date=form.cleaned_data['disposal_date'],
                    disposal_amount=form.cleaned_data['disposal_amount'],
                    reason=form.cleaned_data['reason'],
                    user=request.user
                )
                messages.success(request, f'Asset disposed. Journal: {journal.entry_number}')
                return redirect('assets:asset_detail', pk=pk)
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'Error disposing asset: {e}')
    else:
        form = DisposalForm(initial={'disposal_date': date.today()})
    
    context = {
        'title': f'Dispose Asset: {asset.asset_number}',
        'asset': asset,
        'form': form,
    }
    return render(request, 'assets/asset_dispose.html', context)


@login_required
def run_depreciation(request):
    """Run depreciation for all active assets with full audit trail."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_list')

    active_assets = FixedAsset.objects.filter(
        is_active=True, status='active'
    ).select_related('category')
    results = None
    batch_run = None

    if request.method == 'POST':
        depreciation_date_str = request.POST.get('depreciation_date', '')
        try:
            depreciation_date = datetime.strptime(
                depreciation_date_str, '%Y-%m-%d'
            ).date()
        except (ValueError, TypeError):
            depreciation_date = date.today().replace(day=1)

        period = depreciation_date.strftime('%Y-%m')

        existing_batch = DepreciationBatchRun.objects.filter(
            period=period,
            status__in=['completed', 'completed_with_errors'],
        ).first()
        if existing_batch:
            messages.warning(
                request,
                f'Depreciation was already run for {period} '
                f'(Batch: {existing_batch.batch_number}). '
                f'Reverse the previous run before re-running.'
            )
        else:
            batch_run = DepreciationBatchRun.objects.create(
                depreciation_date=depreciation_date,
                run_by=request.user,
                total_assets=active_assets.count(),
            )

            results = []
            success_count = 0
            error_count = 0
            skip_count = 0
            total_depreciation = Decimal('0.00')
            error_details = {}

            for asset in active_assets:
                validation_errors = asset.validate_for_depreciation(depreciation_date)

                if validation_errors:
                    is_skip = any(
                        'already depreciated' in e.lower()
                        or 'fully depreciated' in e.lower()
                        for e in validation_errors
                    )
                    status = 'skipped' if is_skip else 'error'
                    msg = '; '.join(validation_errors)
                    results.append({
                        'asset': asset,
                        'status': status,
                        'message': msg,
                    })
                    if is_skip:
                        skip_count += 1
                    else:
                        error_count += 1
                        error_details[asset.asset_number] = msg
                    continue

                try:
                    journal = asset.run_depreciation(
                        depreciation_date,
                        user=request.user,
                        batch_run=batch_run,
                    )
                    dep_record = AssetDepreciation.objects.filter(
                        asset=asset, period=period
                    ).first()
                    amount = dep_record.depreciation_amount if dep_record else Decimal('0.00')
                    total_depreciation += amount
                    results.append({
                        'asset': asset,
                        'status': 'success',
                        'amount': amount,
                        'journal': journal.entry_number,
                        'message': f'Depreciated AED {amount:,.2f}',
                    })
                    success_count += 1
                except Exception as e:
                    msg = str(e)
                    logger.exception(
                        "Depreciation failed for %s: %s",
                        asset.asset_number, msg,
                    )
                    results.append({
                        'asset': asset,
                        'status': 'error',
                        'message': msg,
                    })
                    error_count += 1
                    error_details[asset.asset_number] = msg

            batch_run.success_count = success_count
            batch_run.error_count = error_count
            batch_run.skip_count = skip_count
            batch_run.total_depreciation = total_depreciation
            batch_run.error_details = error_details
            if error_count > 0 and success_count > 0:
                batch_run.status = 'completed_with_errors'
            elif error_count > 0:
                batch_run.status = 'failed'
            else:
                batch_run.status = 'completed'
            batch_run.save()

            if success_count > 0:
                messages.success(
                    request,
                    f'Depreciation completed: {success_count} assets '
                    f'(AED {total_depreciation:,.2f}).'
                )
            if skip_count > 0:
                messages.info(
                    request,
                    f'{skip_count} assets skipped '
                    f'(already depreciated or fully depreciated).'
                )
            if error_count > 0:
                messages.warning(
                    request,
                    f'{error_count} assets had errors. See details below.'
                )

    recent_batches = DepreciationBatchRun.objects.all()[:5]

    context = {
        'title': 'Run Depreciation',
        'active_assets': active_assets.count(),
        'today': date.today().strftime('%Y-%m-%d'),
        'results': results,
        'batch_run': batch_run,
        'recent_batches': recent_batches,
    }
    return render(request, 'assets/run_depreciation.html', context)


# ============ REPORTS ============

@login_required
def asset_register_report(request):
    """Asset Register Report."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    
    assets = FixedAsset.objects.filter(is_active=True).select_related('category', 'vendor')
    
    # Filters
    status = request.GET.get('status')
    category = request.GET.get('category')
    
    if status:
        assets = assets.filter(status=status)
    if category:
        assets = assets.filter(category_id=category)
    
    # Totals
    totals = assets.aggregate(
        total_cost=Sum('acquisition_cost'),
        total_depreciation=Sum('accumulated_depreciation'),
        total_book_value=Sum('book_value')
    )
    
    context = {
        'title': 'Fixed Asset Register',
        'assets': assets,
        'categories': AssetCategory.objects.filter(is_active=True),
        'totals': totals,
        'selected_status': status,
        'selected_category': category,
    }
    return render(request, 'assets/register_report.html', context)


@login_required
def depreciation_report(request):
    """Depreciation Schedule Report - filters by depreciation_date (posting date)."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')

    try:
        from_str = request.GET.get('from_date', '').strip()
        to_str = request.GET.get('to_date', '').strip()
        from_date = date.fromisoformat(from_str) if from_str else date(date.today().year, 1, 1)
        to_date = date.fromisoformat(to_str) if to_str else date.today()
    except (ValueError, TypeError):
        from_date = date(date.today().year, 1, 1)
        to_date = date.today()

    if from_date > to_date:
        from_date, to_date = to_date, from_date

    category_id = request.GET.get('category', '').strip()

    depreciation_records = AssetDepreciation.objects.filter(
        depreciation_date__gte=from_date,
        depreciation_date__lte=to_date,
    ).select_related(
        'asset', 'asset__category', 'journal_entry',
    ).annotate(
        computed_book_value=Greatest(
            F('asset__acquisition_cost') - F('accumulated_depreciation'),
            Value(Decimal('0.00')),
        ),
    ).order_by('depreciation_date', 'asset__asset_number')

    if category_id:
        depreciation_records = depreciation_records.filter(
            asset__category_id=category_id
        )

    depreciation_records = depreciation_records.filter(
        Q(journal_entry__isnull=True) | Q(journal_entry__status='posted')
    )

    totals = depreciation_records.aggregate(
        total_depreciation=Sum('depreciation_amount'),
        total_cost=Sum('asset__acquisition_cost'),
        total_accumulated=Sum('accumulated_depreciation'),
    )
    if totals.get('total_depreciation') is None:
        totals['total_depreciation'] = Decimal('0.00')
    if totals.get('total_cost') is None:
        totals['total_cost'] = Decimal('0.00')
    if totals.get('total_accumulated') is None:
        totals['total_accumulated'] = Decimal('0.00')
    totals['total_book_value'] = max(
        totals['total_cost'] - totals['total_accumulated'],
        Decimal('0.00'),
    )
    result_count = depreciation_records.count()
    logger.info(
        "Depreciation Report Query: from_date=%s to_date=%s result_count=%s total=%s",
        from_date, to_date, result_count,
        totals.get('total_depreciation'),
    )

    if request.GET.get('format') == 'excel':
        from apps.finance.excel_exports import export_depreciation_report
        records_data = []
        for rec in depreciation_records:
            nbv = max(rec.asset.acquisition_cost - rec.accumulated_depreciation, Decimal('0'))
            records_data.append({
                'date': rec.depreciation_date,
                'asset_number': rec.asset.asset_number,
                'asset_name': rec.asset.name,
                'category': rec.asset.category.name if rec.asset.category else '',
                'cost': rec.asset.acquisition_cost,
                'depreciation_amount': rec.depreciation_amount,
                'accumulated_depreciation': rec.accumulated_depreciation,
                'book_value': nbv,
                'journal_ref': rec.journal_entry.entry_number if rec.journal_entry else '-',
            })
        return export_depreciation_report(records_data, totals, from_date.isoformat(), to_date.isoformat())

    context = {
        'title': 'Depreciation Report',
        'depreciation_records': depreciation_records,
        'totals': totals,
        'from_date': from_date,
        'to_date': to_date,
        'categories': AssetCategory.objects.filter(is_active=True),
        'selected_category': category_id,
    }
    return render(request, 'assets/depreciation_report.html', context)


def _require_assets_edit(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'assets', 'edit')


@login_required
def asset_operational_update(request, pk):
    asset = get_object_or_404(FixedAsset, pk=pk, is_active=True)
    if not _require_assets_edit(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=pk)

    form = AssetOperationalForm(request.POST, instance=asset)
    if form.is_valid():
        form.save()
        messages.success(request, 'Operational settings updated.')
    else:
        messages.error(request, 'Could not update operational settings.')
    return redirect('assets:asset_detail', pk=pk)


@login_required
def asset_allocate(request, pk):
    asset = get_object_or_404(FixedAsset, pk=pk, is_active=True)
    if not _require_assets_edit(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=pk)

    form = EquipmentAllocationForm(request.POST)
    if form.is_valid():
        try:
            allocation = equipment_services.allocate_asset_to_project(
                asset,
                form.cleaned_data['project'],
                start_date=form.cleaned_data['start_date'],
                expected_end_date=form.cleaned_data.get('expected_end_date'),
                user=request.user,
                notes=form.cleaned_data.get('notes', ''),
            )
            messages.success(
                request,
                f'Allocated to {allocation.project.project_code} at AED {allocation.rate_per_hour}/hr.',
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        messages.error(request, 'Invalid allocation form.')
    return redirect('assets:asset_detail', pk=pk)


@login_required
def equipment_allocation_return(request, pk):
    allocation = get_object_or_404(
        EquipmentAllocation.objects.select_related('asset', 'project'),
        pk=pk,
        is_active=True,
    )
    if not _require_assets_edit(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=allocation.asset_id)

    form = EquipmentReturnForm(request.POST)
    if form.is_valid():
        try:
            equipment_services.return_allocation(
                allocation,
                return_date=form.cleaned_data['return_date'],
                hours_used=form.cleaned_data.get('hours_used'),
                user=request.user,
                warehouse_location=form.cleaned_data.get('warehouse_location', ''),
            )
            cost = allocation.display_cost()
            messages.success(request, f'Returned to warehouse. Usage cost: AED {cost}.')
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        messages.error(request, 'Invalid return form.')
    return redirect('assets:asset_detail', pk=allocation.asset_id)


@login_required
def equipment_allocation_transfer(request, pk):
    allocation = get_object_or_404(
        EquipmentAllocation.objects.select_related('asset', 'project'),
        pk=pk,
        is_active=True,
        status='active',
    )
    if not _require_assets_edit(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=allocation.asset_id)

    form = EquipmentTransferForm(request.POST, exclude_project=allocation.project)
    if form.is_valid():
        try:
            new_alloc = equipment_services.transfer_allocation(
                allocation,
                form.cleaned_data['target_project'],
                transfer_date=form.cleaned_data['transfer_date'],
                user=request.user,
                notes=form.cleaned_data.get('notes', ''),
            )
            messages.success(
                request,
                f'Transferred to {new_alloc.project.project_code}.',
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        messages.error(request, 'Invalid transfer form.')
    return redirect('assets:asset_detail', pk=allocation.asset_id)


@login_required
def asset_flag_maintenance(request, pk):
    asset = get_object_or_404(FixedAsset, pk=pk, is_active=True)
    if not _require_assets_edit(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=pk)

    form = EquipmentMaintenanceForm(request.POST)
    if form.is_valid():
        try:
            equipment_services.flag_maintenance(
                asset,
                reason=form.cleaned_data['reason'],
                user=request.user,
            )
            messages.warning(request, 'Equipment flagged for maintenance.')
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    else:
        messages.error(request, 'Please provide a maintenance reason.')
    return redirect('assets:asset_detail', pk=pk)


@login_required
def asset_clear_maintenance(request, pk, log_pk):
    asset = get_object_or_404(FixedAsset, pk=pk, is_active=True)
    log = get_object_or_404(EquipmentMaintenanceLog, pk=log_pk, asset=asset, is_active=True)
    if not _require_assets_edit(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_detail', pk=pk)

    try:
        equipment_services.clear_maintenance(log, user=request.user)
        messages.success(request, 'Maintenance cleared — equipment available again.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
    return redirect('assets:asset_detail', pk=pk)
