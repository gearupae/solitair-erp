"""Oracle mock URL configuration."""

from django.urls import path

from . import views

app_name = 'oracle_mock'

urlpatterns = [
    path('production-orders/', views.production_orders_list, name='production_orders'),
    path('items/', views.items_list, name='items'),
    path('material-consumption/', views.material_consumption_post, name='material_consumption'),
    path('wip-valuation/', views.wip_valuation_post, name='wip_valuation'),
    path('dispatch-confirm/', views.dispatch_confirm_post, name='dispatch_confirm'),
]
