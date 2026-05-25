from django.contrib import admin
from .models import Category, Warehouse, StorageLocation, Item, ItemGroup, ItemSerialNumber, Stock, StockMovement


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'parent', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    readonly_fields = ['code']


@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'description']


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'contact_person', 'phone', 'status']
    list_filter = ['status', 'is_active']
    search_fields = ['name', 'code']
    readonly_fields = ['code']


@admin.register(ItemGroup)
class ItemGroupAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = [
        'item_code', 'name', 'category', 'item_groups_display', 'item_type',
        'purchase_price', 'selling_price', 'status',
    ]
    list_filter = ['item_type', 'status', 'category', 'is_active']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category').prefetch_related('item_groups')

    @staticmethod
    def item_groups_display(obj):
        return ', '.join(obj.item_groups.values_list('name', flat=True)[:12])

    item_groups_display.short_description = 'Groups'
    search_fields = ['item_code', 'name']
    readonly_fields = ['item_code']


@admin.register(ItemSerialNumber)
class ItemSerialNumberAdmin(admin.ModelAdmin):
    list_display = ['model_number', 'item', 'status', 'warehouse', 'date_received', 'assigned_project']
    list_filter = ['status', 'warehouse']
    search_fields = ['model_number', 'item__item_code', 'item__name']
    raw_id_fields = ['item', 'receipt_line', 'warehouse', 'assigned_project', 'delivered_by']


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['item', 'warehouse', 'quantity']
    list_filter = ['warehouse']
    search_fields = ['item__name', 'item__item_code']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['item', 'warehouse', 'movement_type', 'quantity', 'reference', 'movement_date']
    list_filter = ['movement_type', 'warehouse', 'movement_date']
    search_fields = ['item__name', 'reference']





