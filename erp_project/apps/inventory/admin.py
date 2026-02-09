from django.contrib import admin
from .models import Category, Warehouse, Item, Stock, StockMovement


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'parent', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    readonly_fields = ['code']


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'contact_person', 'phone', 'status']
    list_filter = ['status', 'is_active']
    search_fields = ['name', 'code']
    readonly_fields = ['code']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['item_code', 'name', 'category', 'item_type', 'purchase_price', 'selling_price', 'status']
    list_filter = ['item_type', 'status', 'category', 'is_active']
    search_fields = ['item_code', 'name']
    readonly_fields = ['item_code']


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





