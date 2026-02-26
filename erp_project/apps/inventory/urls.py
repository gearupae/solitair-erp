"""
Inventory URL configuration.
"""
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # Categories
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    
    # Warehouses
    path('warehouses/', views.WarehouseListView.as_view(), name='warehouse_list'),
    path('warehouses/<int:pk>/edit/', views.WarehouseUpdateView.as_view(), name='warehouse_edit'),
    path('warehouses/<int:pk>/delete/', views.warehouse_delete, name='warehouse_delete'),
    
    # Items
    path('items/', views.ItemListView.as_view(), name='item_list'),
    path('items/create/', views.ItemCreateView.as_view(), name='item_create'),
    path('items/<int:pk>/', views.ItemDetailView.as_view(), name='item_detail'),
    path('items/<int:pk>/edit/', views.ItemUpdateView.as_view(), name='item_edit'),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    
    # Stock
    path('stock/', views.StockListView.as_view(), name='stock_list'),
    path('stock/adjustment/', views.stock_adjustment, name='stock_adjustment'),
    
    # Movements
    path('movements/', views.MovementListView.as_view(), name='movement_list'),
    path('movements/export/', views.movement_export_excel, name='movement_export'),
    path('movements/<int:pk>/', views.movement_detail, name='movement_detail'),
    path('movements/<int:pk>/post/', views.movement_post_to_accounting, name='movement_post'),
    
    # Stock Transfers
    path('transfers/', views.stock_transfer, name='stock_transfer'),
    
    # Item Condition
    path('items/<int:pk>/condition/', views.item_change_condition, name='item_change_condition'),
    
    # Consumable Requests
    path('consumables/', views.ConsumableRequestListView.as_view(), name='consumable_request_list'),
    path('consumables/create/', views.consumable_request_create, name='consumable_request_create'),
    path('consumables/<int:pk>/', views.consumable_request_detail, name='consumable_request_detail'),
    path('consumables/<int:pk>/approve/', views.consumable_request_approve, name='consumable_request_approve'),
    path('consumables/<int:pk>/dispense/', views.consumable_request_dispense, name='consumable_request_dispense'),
    path('consumables/<int:pk>/reject/', views.consumable_request_reject, name='consumable_request_reject'),
    
    # Consumable Dashboard & Reports
    path('consumables/dashboard/', views.consumable_dashboard, name='consumable_dashboard'),
    path('consumables/reports/monthly-requests/', views.consumable_monthly_request_report, name='consumable_monthly_request_report'),
    path('consumables/reports/monthly-consumption/', views.consumable_monthly_consumption_report, name='consumable_monthly_consumption_report'),
    path('consumables/reports/monthly-cost/', views.consumable_monthly_cost_report, name='consumable_monthly_cost_report'),
]


