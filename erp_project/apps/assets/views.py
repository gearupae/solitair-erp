from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.db.models import Sum, Q
from django.core.exceptions import ValidationError
from datetime import date
from decimal import Decimal

from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from .models import AssetCategory, FixedAsset, AssetDepreciation
from .forms import AssetCategoryForm, FixedAssetForm, DisposalForm


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
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Asset: {self.object.asset_number}'
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'assets', 'edit')
        context['depreciation_records'] = self.object.depreciation_records.all()[:12]
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
    """Run depreciation for all active assets."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('assets:asset_list')
    
    if request.method == 'POST':
        depreciation_date_str = request.POST.get('depreciation_date')
        try:
            from datetime import datetime
            depreciation_date = datetime.strptime(depreciation_date_str, '%Y-%m-%d').date()
        except:
            depreciation_date = date.today().replace(day=1)
        
        active_assets = FixedAsset.objects.filter(is_active=True, status='active')
        success_count = 0
        error_count = 0
        
        for asset in active_assets:
            try:
                asset.run_depreciation(depreciation_date, user=request.user)
                success_count += 1
            except Exception as e:
                error_count += 1
        
        if success_count > 0:
            messages.success(request, f'Depreciation run completed. {success_count} assets depreciated.')
        if error_count > 0:
            messages.warning(request, f'{error_count} assets had errors.')
        
        return redirect('assets:asset_list')
    
    context = {
        'title': 'Run Depreciation',
        'active_assets': FixedAsset.objects.filter(is_active=True, status='active').count(),
        'today': date.today().strftime('%Y-%m-%d'),
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
    """Depreciation Schedule Report."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'assets', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    
    # Get date range with robust parsing
    try:
        from_str = request.GET.get('from_date', '')
        to_str = request.GET.get('to_date', '')
        from_date = date.fromisoformat(from_str) if from_str else date(date.today().year, 1, 1)
        to_date = date.fromisoformat(to_str) if to_str else date.today()
    except (ValueError, TypeError):
        from_date = date(date.today().year, 1, 1)
        to_date = date.today()
    
    depreciation_records = AssetDepreciation.objects.filter(
        depreciation_date__gte=from_date,
        depreciation_date__lte=to_date
    ).select_related('asset', 'asset__category', 'journal_entry').order_by('depreciation_date')
    
    totals = depreciation_records.aggregate(
        total_depreciation=Sum('depreciation_amount')
    )
    
    context = {
        'title': 'Depreciation Report',
        'depreciation_records': depreciation_records,
        'totals': totals,
        'from_date': from_date,
        'to_date': to_date,
    }
    return render(request, 'assets/depreciation_report.html', context)
