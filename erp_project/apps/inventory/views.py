"""
Inventory Views - Categories, Warehouses, Items, Stock
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy
from django.db.models import Q, Sum, F, Value, DecimalField, Count, Avg, Prefetch
from django.db import models as db_models
from django.db.models.functions import Coalesce
from django.db import transaction
from django.http import HttpResponse
from decimal import Decimal

from .models import Category, Warehouse, Item, Stock, StockMovement, ConsumableRequest, ConsumableRequestItem, ConsumableRequestAttachment, ConditionLog
from .forms import (
    CategoryForm, WarehouseForm, ItemForm, StockAdjustmentForm,
    ConsumableRequestForm, ConsumableRequestItemFormSet,
    ConsumableRequestApproveForm, ConsumableRequestRejectForm,
    StockTransferForm, ItemConditionForm,
)
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker


# ============ CATEGORY VIEWS ============

class CategoryListView(PermissionRequiredMixin, ListView):
    model = Category
    template_name = 'inventory/category_list.html'
    context_object_name = 'categories'
    module_name = 'inventory'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = Category.objects.filter(is_active=True)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(code__icontains=search)
            )
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Categories'
        context['form'] = CategoryForm()
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'delete')
        return context
    
    def post(self, request, *args, **kwargs):
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'create')):
            messages.error(request, 'Permission denied.')
            return redirect('inventory:category_list')
        
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'Category {category.name} created.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        return redirect('inventory:category_list')


class CategoryUpdateView(UpdatePermissionMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'inventory/category_form.html'
    success_url = reverse_lazy('inventory:category_list')
    module_name = 'inventory'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Category: {self.object.name}'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Category {form.instance.name} updated.')
        return super().form_valid(form)


@login_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'delete'):
        category.is_active = False
        category.save()
        messages.success(request, f'Category {category.name} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('inventory:category_list')


# ============ WAREHOUSE VIEWS ============

class WarehouseListView(PermissionRequiredMixin, ListView):
    model = Warehouse
    template_name = 'inventory/warehouse_list.html'
    context_object_name = 'warehouses'
    module_name = 'inventory'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = Warehouse.objects.filter(is_active=True)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(code__icontains=search)
            )
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Warehouses'
        context['form'] = WarehouseForm()
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'delete')
        return context
    
    def post(self, request, *args, **kwargs):
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'create')):
            messages.error(request, 'Permission denied.')
            return redirect('inventory:warehouse_list')
        
        form = WarehouseForm(request.POST)
        if form.is_valid():
            warehouse = form.save()
            messages.success(request, f'Warehouse {warehouse.name} created.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        return redirect('inventory:warehouse_list')


class WarehouseUpdateView(UpdatePermissionMixin, UpdateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = 'inventory/warehouse_form.html'
    success_url = reverse_lazy('inventory:warehouse_list')
    module_name = 'inventory'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Warehouse: {self.object.name}'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Warehouse {form.instance.name} updated.')
        return super().form_valid(form)


@login_required
def warehouse_delete(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'delete'):
        warehouse.is_active = False
        warehouse.save()
        messages.success(request, f'Warehouse {warehouse.name} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('inventory:warehouse_list')


# ============ ITEM VIEWS ============

class ItemListView(PermissionRequiredMixin, ListView):
    model = Item
    template_name = 'inventory/item_list.html'
    context_object_name = 'items'
    module_name = 'inventory'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        # Annotate total_stock at database level to ensure fresh data
        queryset = Item.objects.filter(is_active=True).select_related('category').prefetch_related(
            Prefetch(
                'stock_records',
                queryset=Stock.objects.filter(
                    warehouse__is_active=True,
                    quantity__gt=0
                ).select_related('warehouse'),
                to_attr='active_stock_records'
            )
        ).annotate(
            total_stock_calc=Coalesce(
                Sum(
                    'stock_records__quantity',
                    filter=Q(stock_records__warehouse__is_active=True)
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2)
            )
        )
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(item_code__icontains=search) |
                Q(name__icontains=search)
            )
        
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category_id=category)
        
        item_type = self.request.GET.get('item_type')
        if item_type:
            queryset = queryset.filter(item_type=item_type)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Items'
        context['categories'] = Category.objects.filter(is_active=True)
        context['type_choices'] = Item.TYPE_CHOICES
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'edit')
        context['can_delete'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'delete')
        
        # Stats
        items = self.get_queryset()
        context['total_items'] = items.count()
        # Use annotation for low stock check
        context['low_stock_count'] = sum(
            1 for item in items 
            if item.item_type == 'product' 
            and (item.total_stock_calc or Decimal('0.00')) < item.minimum_stock
        )
        
        return context


class ItemCreateView(CreatePermissionMixin, CreateView):
    model = Item
    form_class = ItemForm
    template_name = 'inventory/item_form.html'
    success_url = reverse_lazy('inventory:item_list')
    module_name = 'inventory'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Item'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Item {form.instance.name} created.')
        return super().form_valid(form)


class ItemUpdateView(UpdatePermissionMixin, UpdateView):
    model = Item
    form_class = ItemForm
    template_name = 'inventory/item_form.html'
    success_url = reverse_lazy('inventory:item_list')
    module_name = 'inventory'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Item: {self.object.name}'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Item {form.instance.name} updated.')
        return super().form_valid(form)


class ItemDetailView(PermissionRequiredMixin, DetailView):
    model = Item
    template_name = 'inventory/item_detail.html'
    context_object_name = 'item'
    module_name = 'inventory'
    permission_type = 'view'
    
    def get_queryset(self):
        # Annotate total_stock at database level to ensure fresh data
        return Item.objects.annotate(
            total_stock_calc=Coalesce(
                Sum(
                    'stock_records__quantity',
                    filter=Q(stock_records__warehouse__is_active=True)
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2)
            )
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Item: {self.object.name}'
        context['stock_records'] = Stock.objects.filter(
            item=self.object,
            warehouse__is_active=True
        ).select_related('warehouse')
        context['movements'] = StockMovement.objects.filter(
            item=self.object
        ).select_related('warehouse', 'to_warehouse')[:50]
        context['condition_logs'] = ConditionLog.objects.filter(
            item=self.object
        ).select_related('changed_by')[:20]
        context['condition_form'] = ItemConditionForm(initial={
            'condition_status': self.object.condition_status
        })
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'edit')
        # Transfer form
        context['transfer_form'] = StockTransferForm(initial={'item': self.object.pk})
        context['warehouses'] = Warehouse.objects.filter(is_active=True, status='active')
        return context


@login_required
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'delete'):
        item.is_active = False
        item.save()
        messages.success(request, f'Item {item.name} deleted.')
    else:
        messages.error(request, 'Permission denied.')
    return redirect('inventory:item_list')


# ============ STOCK VIEWS ============

class StockListView(PermissionRequiredMixin, ListView):
    model = Stock
    template_name = 'inventory/stock_list.html'
    context_object_name = 'stocks'
    module_name = 'inventory'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Stock.objects.filter(
            item__is_active=True,
            warehouse__is_active=True
        ).select_related('item', 'warehouse')
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(item__name__icontains=search) |
                Q(item__item_code__icontains=search)
            )
        
        warehouse = self.request.GET.get('warehouse')
        if warehouse:
            queryset = queryset.filter(warehouse_id=warehouse)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Stock Levels'
        context['warehouses'] = Warehouse.objects.filter(is_active=True, status='active')
        context['can_adjust'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'edit')
        return context


@login_required
def stock_adjustment(request):
    """Stock adjustment view."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:stock_list')
    
    if request.method == 'POST':
        form = StockAdjustmentForm(request.POST)
        if form.is_valid():
            item = form.cleaned_data['item']
            warehouse = form.cleaned_data['warehouse']
            quantity = Decimal(str(form.cleaned_data['quantity']))
            movement_type = form.cleaned_data['movement_type']
            adjustment_reason = form.cleaned_data.get('adjustment_reason', '')
            reference = form.cleaned_data['reference']
            notes = form.cleaned_data['notes']

            try:
                with transaction.atomic():
                    from datetime import date as dt_date

                    if movement_type in ('out', 'adjustment_minus'):
                        stock_record = Stock.objects.filter(item=item, warehouse=warehouse).first()
                        available = stock_record.quantity if stock_record else Decimal('0.00')
                        if available < quantity:
                            messages.error(request, f'Insufficient stock. Available: {available}, Requested: {quantity}')
                            items = Item.objects.filter(is_active=True).order_by('name')
                            warehouses = Warehouse.objects.filter(is_active=True, status='active').order_by('name')
                            return render(request, 'inventory/stock_adjustment.html', {
                                'title': 'Stock Adjustment',
                                'form': form,
                                'items': items,
                                'warehouses': warehouses,
                            })

                    old_quantity = Stock.objects.filter(
                        item=item, warehouse=warehouse
                    ).values_list('quantity', flat=True).first() or Decimal('0.00')

                    movement = StockMovement.objects.create(
                        item=item,
                        warehouse=warehouse,
                        movement_type=movement_type,
                        adjustment_reason=adjustment_reason,
                        source='manual',
                        quantity=quantity,
                        unit_cost=item.purchase_price or Decimal('0.00'),
                        reference=reference,
                        notes=notes,
                        movement_date=dt_date.today(),
                        created_by=request.user,
                    )

                    # Atomic: update quantity + post GL together
                    movement.execute(user=request.user)

                    new_quantity = Stock.objects.filter(
                        item=item, warehouse=warehouse
                    ).values_list('quantity', flat=True).first() or Decimal('0.00')

                    messages.success(request, f'Stock adjusted for {item.name} at {warehouse.name}. Quantity: {old_quantity} → {new_quantity}')
                    return redirect('inventory:stock_list')
                    
            except Exception as e:
                messages.error(request, f'Error updating stock: {str(e)}')
                items = Item.objects.filter(is_active=True).order_by('name')
                warehouses = Warehouse.objects.filter(is_active=True, status='active').order_by('name')
                return render(request, 'inventory/stock_adjustment.html', {
                    'title': 'Stock Adjustment',
                    'form': form,
                    'items': items,
                    'warehouses': warehouses,
                })
    else:
        form = StockAdjustmentForm()
    
    # Get items and warehouses for template context
    items = Item.objects.filter(is_active=True).order_by('name')
    warehouses = Warehouse.objects.filter(is_active=True, status='active').order_by('name')
    
    return render(request, 'inventory/stock_adjustment.html', {
        'title': 'Stock Adjustment',
        'form': form,
        'items': items,
        'warehouses': warehouses,
    })


class MovementListView(PermissionRequiredMixin, ListView):
    model = StockMovement
    template_name = 'inventory/movement_list.html'
    context_object_name = 'movements'
    module_name = 'inventory'
    permission_type = 'view'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = StockMovement.objects.filter(
            item__is_active=True
        ).select_related('item', 'warehouse', 'journal_entry')
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(item__name__icontains=search) |
                Q(reference__icontains=search) |
                Q(movement_number__icontains=search)
            )
        
        movement_type = self.request.GET.get('type')
        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)
        
        posted = self.request.GET.get('posted')
        if posted == '1':
            queryset = queryset.filter(posted=True)
        elif posted == '0':
            queryset = queryset.filter(posted=False)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Stock Movements'
        context['type_choices'] = StockMovement.MOVEMENT_TYPE_CHOICES
        context['can_post'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'inventory', 'edit')
        
        # Calculate metrics
        all_movements = StockMovement.objects.filter(item__is_active=True)
        context['total_movements'] = all_movements.count()
        context['posted_movements'] = all_movements.filter(posted=True).count()
        context['unposted_movements'] = all_movements.filter(posted=False, total_cost__gt=0).count()
        context['total_value'] = all_movements.filter(posted=True).aggregate(Sum('total_cost'))['total_cost__sum'] or Decimal('0.00')
        
        return context


@login_required
def movement_post_to_accounting(request, pk):
    """Post a stock movement to accounting."""
    movement = get_object_or_404(StockMovement, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:movement_list')
    
    if movement.posted:
        messages.warning(request, f'Movement {movement.movement_number} already posted to accounting.')
        return redirect('inventory:movement_list')
    
    if movement.total_cost <= 0:
        messages.error(request, f'Movement {movement.movement_number} has no cost value. Update cost before posting.')
        return redirect('inventory:movement_list')
    
    try:
        movement.post_to_accounting(user=request.user)
        messages.success(request, f'Movement {movement.movement_number} posted to accounting. Journal Entry: {movement.journal_entry.entry_number}')
    except Exception as e:
        messages.error(request, f'Error posting to accounting: {str(e)}')
    
    return redirect('inventory:movement_list')


@login_required
def movement_export_excel(request):
    """Export stock movements to a formatted Excel file."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from io import BytesIO

    queryset = StockMovement.objects.filter(
        item__is_active=True
    ).select_related('item', 'warehouse', 'to_warehouse', 'journal_entry')

    search = request.GET.get('search')
    if search:
        queryset = queryset.filter(
            Q(item__name__icontains=search) |
            Q(reference__icontains=search) |
            Q(movement_number__icontains=search)
        )

    movement_type = request.GET.get('type')
    if movement_type:
        queryset = queryset.filter(movement_type=movement_type)

    posted = request.GET.get('posted')
    if posted == '1':
        queryset = queryset.filter(posted=True)
    elif posted == '0':
        queryset = queryset.filter(posted=False)

    movements = queryset.order_by('-movement_date', '-id')

    wb = Workbook()
    ws = wb.active
    ws.title = 'Stock Movements'

    headers = [
        'Movement #', 'Date', 'Item Code', 'Item Name', 'Warehouse',
        'Type', 'Source', 'Quantity', 'Unit Cost', 'Total Cost',
        'Reference', 'To Warehouse', 'Adjustment Reason',
        'GL Status', 'Journal #', 'Notes',
    ]
    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin'),
    )

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = thin_border

    type_display = dict(StockMovement.MOVEMENT_TYPE_CHOICES)
    source_display = dict(StockMovement.SOURCE_CHOICES)
    reason_display = dict(StockMovement.ADJUSTMENT_REASON_CHOICES)

    posted_fill = PatternFill(start_color='D1FAE5', end_color='D1FAE5', fill_type='solid')
    pending_fill = PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')
    number_fmt = '#,##0.00'

    for row_idx, m in enumerate(movements, 2):
        row_data = [
            m.movement_number,
            m.movement_date,
            m.item.item_code,
            m.item.name,
            m.warehouse.name,
            type_display.get(m.movement_type, m.movement_type),
            source_display.get(m.source, m.source),
            float(m.quantity),
            float(m.unit_cost),
            float(m.total_cost),
            m.reference,
            m.to_warehouse.name if m.to_warehouse else '',
            reason_display.get(m.adjustment_reason, m.adjustment_reason) if m.adjustment_reason else '',
            'Posted' if m.posted else ('Pending' if m.total_cost > 0 else 'No Cost'),
            m.journal_entry.entry_number if m.journal_entry else '',
            m.notes,
        ]
        row_fill = posted_fill if m.posted else (pending_fill if m.total_cost > 0 else None)
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            if row_fill:
                cell.fill = row_fill
            if col_idx in (8, 9, 10):
                cell.number_format = number_fmt
                cell.alignment = Alignment(horizontal='right')
            if col_idx == 2:
                cell.number_format = 'DD/MM/YYYY'

    col_widths = [18, 14, 14, 28, 20, 16, 16, 12, 14, 16, 22, 20, 22, 12, 18, 30]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Summary sheet
    ws_summary = wb.create_sheet('Summary')
    ws_summary.sheet_properties.tabColor = '10B981'
    summary_header_fill = PatternFill(start_color='10B981', end_color='10B981', fill_type='solid')

    summary_title = ws_summary.cell(row=1, column=1, value='Stock Movement Summary')
    summary_title.font = Font(bold=True, size=14)
    ws_summary.merge_cells('A1:D1')

    all_movements = StockMovement.objects.filter(item__is_active=True)
    summary_data = [
        ('Total Movements', all_movements.count()),
        ('Posted to GL', all_movements.filter(posted=True).count()),
        ('Pending Posting', all_movements.filter(posted=False, total_cost__gt=0).count()),
        ('Total Posted Value', float(all_movements.filter(posted=True).aggregate(Sum('total_cost'))['total_cost__sum'] or 0)),
        ('', ''),
        ('By Type', ''),
    ]
    for choice_val, choice_label in StockMovement.MOVEMENT_TYPE_CHOICES:
        count = all_movements.filter(movement_type=choice_val).count()
        value = float(all_movements.filter(movement_type=choice_val).aggregate(Sum('total_cost'))['total_cost__sum'] or 0)
        summary_data.append((f'  {choice_label}', f'{count} movements — {value:,.2f} value'))

    for row_idx, (label, value) in enumerate(summary_data, 3):
        ws_summary.cell(row=row_idx, column=1, value=label).font = Font(bold=True)
        ws_summary.cell(row=row_idx, column=2, value=value)
    ws_summary.column_dimensions['A'].width = 24
    ws_summary.column_dimensions['B'].width = 36

    ws.auto_filter.ref = f'A1:{get_column_letter(len(headers))}1'
    ws.freeze_panes = 'A2'

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="stock_movements_export.xlsx"'
    return response


@login_required
def movement_detail(request, pk):
    """View stock movement detail."""
    movement = get_object_or_404(
        StockMovement.objects.select_related('item', 'warehouse', 'to_warehouse', 'journal_entry'),
        pk=pk
    )
    
    context = {
        'title': f'Movement: {movement.movement_number}',
        'movement': movement,
        'can_post': not movement.posted and movement.total_cost > 0 and (
            request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')
        ),
    }
    
    if movement.journal_entry:
        context['journal_lines'] = movement.journal_entry.lines.all().select_related('account')
    
    return render(request, 'inventory/movement_detail.html', context)


# ============ STOCK TRANSFER VIEW ============

@login_required
def stock_transfer(request):
    """Manual stock transfer between warehouses."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:movement_list')
    
    if request.method == 'POST':
        form = StockTransferForm(request.POST)
        if form.is_valid():
            item = form.cleaned_data['item']
            from_warehouse = form.cleaned_data['from_warehouse']
            to_warehouse = form.cleaned_data['to_warehouse']
            quantity = form.cleaned_data['quantity']
            reference = form.cleaned_data['reference']
            notes = form.cleaned_data['notes']
            
            try:
                with transaction.atomic():
                    from datetime import date
                    movement = StockMovement.objects.create(
                        item=item,
                        warehouse=from_warehouse,
                        to_warehouse=to_warehouse,
                        movement_type='transfer',
                        source='manual',
                        quantity=quantity,
                        unit_cost=item.purchase_price or Decimal('0.00'),
                        reference=reference or f'Manual transfer to {to_warehouse.name}',
                        notes=notes,
                        movement_date=date.today(),
                        created_by=request.user,
                    )

                    # Atomic: update quantity + post GL together
                    movement.execute(user=request.user)

                    messages.success(
                        request,
                        f'Successfully transferred {quantity} {item.unit} of {item.name} '
                        f'from {from_warehouse.name} to {to_warehouse.name}. '
                        f'Movement: {movement.movement_number}'
                    )
                    return redirect('inventory:movement_detail', pk=movement.pk)
                    
            except Exception as e:
                messages.error(request, f'Transfer failed: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f'{form.fields[field].label or field}: {error}')
    else:
        initial = {}
        item_id = request.GET.get('item')
        if item_id:
            initial['item'] = item_id
        form = StockTransferForm(initial=initial)
    
    return render(request, 'inventory/stock_transfer.html', {
        'title': 'Manual Stock Transfer',
        'form': form,
    })


@login_required
def item_change_condition(request, pk):
    """Change an item's condition status (in_store, in_use, repair, damaged)."""
    item = get_object_or_404(Item, pk=pk)
    
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:item_detail', pk=pk)
    
    if request.method == 'POST':
        form = ItemConditionForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data['condition_status']
            notes = form.cleaned_data['condition_notes']
            old_display = item.get_condition_status_display()
            
            item.change_condition(new_status, notes, user=request.user)
            
            new_display = item.get_condition_status_display()
            messages.success(
                request,
                f'Item condition updated: {old_display} → {new_display}'
            )
        else:
            messages.error(request, 'Invalid form data.')
    
    return redirect('inventory:item_detail', pk=pk)


# ============ CONSUMABLE REQUEST VIEWS ============

class ConsumableRequestListView(PermissionRequiredMixin, ListView):
    """
    List view for consumable requests.
    - Nurses see their own requests
    - Admin/Inventory see all requests
    """
    model = ConsumableRequest
    template_name = 'inventory/consumable_request_list.html'
    context_object_name = 'requests'
    module_name = 'inventory'
    permission_type = 'view'
    paginate_by = 25
    
    def get_queryset(self):
        user = self.request.user
        queryset = ConsumableRequest.objects.filter(is_active=True).select_related(
            'item', 'requested_by', 'warehouse', 'approved_by', 'dispensed_by', 'department'
        ).prefetch_related('items')
        
        # Non-admins only see their own requests
        if not user.is_superuser and not PermissionChecker.has_permission(user, 'inventory', 'edit'):
            queryset = queryset.filter(requested_by=user)
        
        # Filters
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(request_number__icontains=search) |
                Q(item__name__icontains=search) |
                Q(items__item__name__icontains=search) |
                Q(requested_by__first_name__icontains=search) |
                Q(requested_by__last_name__icontains=search)
            ).distinct()
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        is_admin = user.is_superuser or PermissionChecker.has_permission(user, 'inventory', 'edit')
        
        context['title'] = 'Consumable Requests'
        context['status_choices'] = ConsumableRequest.STATUS_CHOICES
        context['is_admin'] = is_admin
        
        # Stats (for admins)
        if is_admin:
            all_requests = ConsumableRequest.objects.filter(is_active=True)
            context['pending_count'] = all_requests.filter(status='pending').count()
            context['approved_count'] = all_requests.filter(status='approved').count()
            context['dispensed_count'] = all_requests.filter(status='dispensed').count()
        
        return context


@login_required
def consumable_request_create(request):
    """
    Full-page form for creating consumable requests with multiple line items.
    """
    from datetime import date
    
    if request.method == 'POST':
        form = ConsumableRequestForm(request.POST)
        items_formset = ConsumableRequestItemFormSet(request.POST)
        if form.is_valid() and items_formset.is_valid():
            consumable_request = form.save(commit=False)
            consumable_request.requested_by = request.user
            consumable_request.save()
            items_formset.instance = consumable_request
            items_formset.save()
            consumable_request.recalculate_total()
            # Save attachments
            for f in request.FILES.getlist('attachments'):
                ConsumableRequestAttachment.objects.create(
                    consumable_request=consumable_request,
                    file=f,
                    filename=f.name,
                    uploaded_by=request.user
                )
            messages.success(request, f'Request {consumable_request.request_number} submitted!')
            return redirect('inventory:consumable_request_list')
    else:
        form = ConsumableRequestForm()
        items_formset = ConsumableRequestItemFormSet()
    
    return render(request, 'inventory/consumable_request_form.html', {
        'title': 'Request Consumables',
        'form': form,
        'items_formset': items_formset,
        'today': date.today().isoformat(),
    })


@login_required
def consumable_request_detail(request, pk):
    """View request details."""
    consumable_request = get_object_or_404(
        ConsumableRequest.objects.select_related(
            'item', 'requested_by', 'warehouse', 'approved_by', 'dispensed_by', 'stock_movement', 'department'
        ).prefetch_related('items', 'items__item', 'attachments'),
        pk=pk
    )
    
    user = request.user
    is_admin = user.is_superuser or PermissionChecker.has_permission(user, 'inventory', 'edit')
    
    # Non-admins can only view their own requests
    if not is_admin and consumable_request.requested_by != user:
        messages.error(request, 'Permission denied.')
        return redirect('inventory:consumable_request_list')
    
    context = {
        'title': f'Request: {consumable_request.request_number}',
        'request_obj': consumable_request,
        'is_admin': is_admin,
    }
    
    # For admin: show approve/dispense forms
    if is_admin and consumable_request.status in ['pending', 'approved']:
        context['approve_form'] = ConsumableRequestApproveForm(
            consumable_request=consumable_request
        )
        context['reject_form'] = ConsumableRequestRejectForm()
    
    return render(request, 'inventory/consumable_request_detail.html', context)


@login_required
def consumable_request_approve(request, pk):
    """Admin approves a request."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:consumable_request_list')
    
    consumable_request = get_object_or_404(ConsumableRequest, pk=pk)
    
    if consumable_request.status != 'pending':
        messages.warning(request, f'Request {consumable_request.request_number} is not pending.')
        return redirect('inventory:consumable_request_detail', pk=pk)
    
    if request.method == 'POST':
        form = ConsumableRequestApproveForm(
            request.POST,
            consumable_request=consumable_request
        )
        if form.is_valid():
            try:
                warehouse = form.cleaned_data['warehouse']
                admin_notes = form.cleaned_data.get('admin_notes', '')
                consumable_request.admin_notes = admin_notes
                consumable_request.approve(request.user, warehouse)
                messages.success(request, f'Request {consumable_request.request_number} approved.')
            except Exception as e:
                messages.error(request, f'Error approving request: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    
    return redirect('inventory:consumable_request_detail', pk=pk)


@login_required
def consumable_request_dispense(request, pk):
    """Admin dispenses the consumable (reduces stock)."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:consumable_request_list')
    
    consumable_request = get_object_or_404(ConsumableRequest, pk=pk)
    
    if consumable_request.status not in ['pending', 'approved']:
        messages.warning(request, f'Request {consumable_request.request_number} cannot be dispensed.')
        return redirect('inventory:consumable_request_detail', pk=pk)
    
    if request.method == 'POST':
        form = ConsumableRequestApproveForm(
            request.POST,
            consumable_request=consumable_request
        )
        if form.is_valid():
            try:
                warehouse = form.cleaned_data['warehouse']
                consumable_request.dispense(request.user, warehouse)
                items_dispensed = consumable_request.get_items_for_dispense()
                msg = f'Request {consumable_request.request_number} dispensed.'
                if items_dispensed:
                    msg += f' Stock reduced for {len(items_dispensed)} item(s).'
                messages.success(request, msg)
            except Exception as e:
                messages.error(request, f'Error dispensing: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    
    return redirect('inventory:consumable_request_detail', pk=pk)


@login_required
def consumable_request_reject(request, pk):
    """Admin rejects a request."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'edit')):
        messages.error(request, 'Permission denied.')
        return redirect('inventory:consumable_request_list')
    
    consumable_request = get_object_or_404(ConsumableRequest, pk=pk)
    
    if consumable_request.status not in ['pending', 'approved']:
        messages.warning(request, f'Request {consumable_request.request_number} cannot be rejected.')
        return redirect('inventory:consumable_request_detail', pk=pk)
    
    if request.method == 'POST':
        form = ConsumableRequestRejectForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            consumable_request.reject(request.user, reason)
            messages.success(request, f'Request {consumable_request.request_number} rejected.')
        else:
            messages.error(request, 'Please provide a rejection reason.')
    
    return redirect('inventory:consumable_request_detail', pk=pk)


# ============ CONSUMABLE REPORTS ============

@login_required
def consumable_dashboard(request):
    """
    Dashboard for consumables showing:
    - Total requests this month
    - Total quantity consumed
    - Total cost
    - Low stock alerts
    """
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    
    from django.utils import timezone
    from datetime import timedelta
    
    today = timezone.localdate()
    month_start = today.replace(day=1)
    
    # This month's requests
    month_requests = ConsumableRequest.objects.filter(
        is_active=True,
        request_date__gte=month_start
    )
    
    # Stats
    total_requests = month_requests.count()
    dispensed_requests = month_requests.filter(status='dispensed')
    total_quantity = dispensed_requests.aggregate(Sum('quantity'))['quantity__sum'] or Decimal('0')
    total_cost = dispensed_requests.aggregate(Sum('total_cost'))['total_cost__sum'] or Decimal('0')
    
    # Low stock consumables
    low_stock_items = []
    consumable_items = Item.objects.filter(
        is_active=True,
        item_type='product',
        status='active'
    )
    for item in consumable_items:
        total_stock = item.total_stock
        if total_stock < item.minimum_stock:
            low_stock_items.append({
                'item': item,
                'current_stock': total_stock,
                'minimum_stock': item.minimum_stock,
                'shortfall': item.minimum_stock - total_stock
            })
    
    # Recent requests
    recent_requests = ConsumableRequest.objects.filter(
        is_active=True
    ).select_related('item', 'requested_by').order_by('-created_at')[:10]
    
    # Top requested items this month
    top_items = dispensed_requests.values('item__name').annotate(
        total_qty=Sum('quantity'),
        total_cost=Sum('total_cost')
    ).order_by('-total_qty')[:5]
    
    context = {
        'title': 'Consumables Dashboard',
        'total_requests': total_requests,
        'pending_requests': month_requests.filter(status='pending').count(),
        'total_quantity': total_quantity,
        'total_cost': total_cost,
        'low_stock_items': low_stock_items,
        'low_stock_count': len(low_stock_items),
        'recent_requests': recent_requests,
        'top_items': top_items,
        'month_name': today.strftime('%B %Y'),
    }
    
    return render(request, 'inventory/consumable_dashboard.html', context)


@login_required
def consumable_monthly_request_report(request):
    """Monthly Request Report - per nurse & total."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    
    from django.utils import timezone
    from datetime import date
    
    # Get month from query params
    year = int(request.GET.get('year', timezone.localdate().year))
    month = int(request.GET.get('month', timezone.localdate().month))
    
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)
    
    # Requests for the month
    requests = ConsumableRequest.objects.filter(
        is_active=True,
        request_date__gte=month_start,
        request_date__lt=month_end
    ).select_related('item', 'requested_by')
    
    # Group by nurse
    nurse_summary = requests.values(
        'requested_by__id',
        'requested_by__first_name',
        'requested_by__last_name',
        'requested_by__username'
    ).annotate(
        total_requests=Count('id'),
        total_quantity=Sum('quantity'),
        total_cost=Sum('total_cost'),
        pending=Count('id', filter=Q(status='pending')),
        approved=Count('id', filter=Q(status='approved')),
        dispensed=Count('id', filter=Q(status='dispensed')),
        rejected=Count('id', filter=Q(status='rejected')),
    ).order_by('-total_requests')
    
    # Totals
    totals = requests.aggregate(
        total_requests=Count('id'),
        total_quantity=Sum('quantity'),
        total_cost=Sum('total_cost'),
    )
    
    context = {
        'title': f'Monthly Request Report - {month_start.strftime("%B %Y")}',
        'nurse_summary': nurse_summary,
        'totals': totals,
        'year': year,
        'month': month,
        'month_name': month_start.strftime('%B %Y'),
        'years': range(2024, timezone.localdate().year + 2),
        'months': [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
    }
    
    return render(request, 'inventory/consumable_monthly_request_report.html', context)


@login_required
def consumable_monthly_consumption_report(request):
    """Monthly Consumption Report - item-wise quantity used with analytics."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    
    from django.utils import timezone
    from datetime import date
    from dateutil.relativedelta import relativedelta
    
    # Get month from query params
    year = int(request.GET.get('year', timezone.localdate().year))
    month = int(request.GET.get('month', timezone.localdate().month))
    
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)
    
    # Only dispensed requests count as consumption
    consumption = ConsumableRequest.objects.filter(
        is_active=True,
        status='dispensed',
        request_date__gte=month_start,
        request_date__lt=month_end
    ).values(
        'item__id',
        'item__item_code',
        'item__name',
        'item__unit'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_cost=Sum('total_cost'),
        request_count=Count('id')
    ).order_by('-total_quantity')
    
    # Totals
    totals = ConsumableRequest.objects.filter(
        is_active=True,
        status='dispensed',
        request_date__gte=month_start,
        request_date__lt=month_end
    ).aggregate(
        total_quantity=Sum('quantity'),
        total_cost=Sum('total_cost'),
        total_requests=Count('id'),
    )
    
    # ===== CHART DATA =====
    
    # 1. Top 10 Most Consumed Items (for forecast)
    top_items = list(consumption[:10])
    top_items_labels = [c['item__name'][:20] for c in top_items]
    top_items_data = [float(c['total_quantity'] or 0) for c in top_items]
    
    # 2. Consumption by User (who orders more/less)
    user_consumption = ConsumableRequest.objects.filter(
        is_active=True,
        status='dispensed',
        request_date__gte=month_start,
        request_date__lt=month_end
    ).values(
        'requested_by__username',
        'requested_by__first_name',
        'requested_by__last_name'
    ).annotate(
        total_requests=Count('id'),
        total_quantity=Sum('quantity'),
        total_cost=Sum('total_cost')
    ).order_by('-total_requests')[:10]
    
    user_labels = [f"{u['requested_by__first_name'] or ''} {u['requested_by__last_name'] or ''}".strip() or u['requested_by__username'] for u in user_consumption]
    user_data = [u['total_requests'] for u in user_consumption]
    
    # 3. Monthly Cost Trend (last 6 months)
    monthly_costs = []
    monthly_labels = []
    for i in range(5, -1, -1):
        m_date = month_start - relativedelta(months=i)
        m_end = m_date + relativedelta(months=1)
        cost = ConsumableRequest.objects.filter(
            is_active=True,
            status='dispensed',
            request_date__gte=m_date,
            request_date__lt=m_end
        ).aggregate(total=Sum('total_cost'))['total'] or 0
        monthly_costs.append(float(cost))
        monthly_labels.append(m_date.strftime('%b %Y'))
    
    # 4. Items needing refill (high consumption vs current stock)
    from apps.inventory.models import Stock
    refill_items = []
    for item_data in consumption[:20]:
        item_id = item_data['item__id']
        monthly_consumption = float(item_data['total_quantity'] or 0)
        current_stock = Stock.objects.filter(item_id=item_id).aggregate(total=Sum('quantity'))['total'] or 0
        # If current stock < 2 months of consumption, flag for refill
        if current_stock < (monthly_consumption * 2):
            refill_items.append({
                'name': item_data['item__name'],
                'monthly_consumption': monthly_consumption,
                'current_stock': float(current_stock),
                'months_left': round(float(current_stock) / monthly_consumption, 1) if monthly_consumption > 0 else 0
            })
    
    # 5. Inactive/Rarely Used Items (items with no consumption in last 3 months)
    three_months_ago = month_start - relativedelta(months=3)
    consumed_item_ids = ConsumableRequest.objects.filter(
        is_active=True,
        status='dispensed',
        request_date__gte=three_months_ago
    ).values_list('item_id', flat=True).distinct()
    
    inactive_items = Item.objects.filter(
        is_active=True,
        item_type='product',
        category__name__icontains='medical'
    ).exclude(id__in=consumed_item_ids).values('name', 'item_code')[:10]
    
    # 6. Cost breakdown by item (pie chart)
    cost_breakdown = list(consumption[:8])
    cost_labels = [c['item__name'][:15] for c in cost_breakdown]
    cost_data = [float(c['total_cost'] or 0) for c in cost_breakdown]
    
    context = {
        'title': f'Consumption Analytics - {month_start.strftime("%B %Y")}',
        'consumption': consumption,
        'totals': totals,
        'year': year,
        'month': month,
        'month_name': month_start.strftime('%B %Y'),
        'years': range(2024, timezone.localdate().year + 2),
        'months': [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        # Chart data
        'top_items_labels': top_items_labels,
        'top_items_data': top_items_data,
        'user_labels': user_labels,
        'user_data': user_data,
        'monthly_labels': monthly_labels,
        'monthly_costs': monthly_costs,
        'refill_items': refill_items,
        'inactive_items': inactive_items,
        'cost_labels': cost_labels,
        'cost_data': cost_data,
        'user_consumption': user_consumption,
    }
    
    return render(request, 'inventory/consumable_monthly_consumption_report.html', context)


@login_required
def consumable_monthly_cost_report(request):
    """Monthly Financial Cost Report - total consumable cost."""
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'inventory', 'view')):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    
    from django.utils import timezone
    from datetime import date
    
    # Get month from query params
    year = int(request.GET.get('year', timezone.localdate().year))
    month = int(request.GET.get('month', timezone.localdate().month))
    
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)
    
    # Cost breakdown by item
    cost_breakdown = ConsumableRequest.objects.filter(
        is_active=True,
        status='dispensed',
        request_date__gte=month_start,
        request_date__lt=month_end
    ).values(
        'item__id',
        'item__item_code',
        'item__name',
        'item__category__name'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_cost=Sum('total_cost'),
        avg_unit_cost=Avg('unit_cost')
    ).order_by('-total_cost')
    
    # Daily cost trend
    daily_costs = ConsumableRequest.objects.filter(
        is_active=True,
        status='dispensed',
        request_date__gte=month_start,
        request_date__lt=month_end
    ).values('request_date').annotate(
        daily_cost=Sum('total_cost'),
        daily_qty=Sum('quantity')
    ).order_by('request_date')
    
    # Totals
    totals = ConsumableRequest.objects.filter(
        is_active=True,
        status='dispensed',
        request_date__gte=month_start,
        request_date__lt=month_end
    ).aggregate(
        total_cost=Sum('total_cost'),
        total_quantity=Sum('quantity'),
        total_requests=Count('id'),
    )
    
    context = {
        'title': f'Monthly Cost Report - {month_start.strftime("%B %Y")}',
        'cost_breakdown': cost_breakdown,
        'daily_costs': list(daily_costs),
        'totals': totals,
        'year': year,
        'month': month,
        'month_name': month_start.strftime('%B %Y'),
        'years': range(2024, timezone.localdate().year + 2),
        'months': [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
    }
    
    return render(request, 'inventory/consumable_monthly_cost_report.html', context)

