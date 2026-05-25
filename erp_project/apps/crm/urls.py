"""
CRM URL configuration.
"""
from django.urls import path
from . import views

app_name = 'crm'

urlpatterns = [
    path('public-upload/', views.public_customer_upload, name='public_upload'),
    path('customers/project-options/', views.crm_project_options, name='project_options'),
    path('customers/', views.CustomerListView.as_view(), name='customer_list'),
    path('customers/kanban/move/', views.crm_kanban_move, name='kanban_move'),
    path('customers/<int:pk>/', views.CustomerDetailView.as_view(), name='customer_detail'),
    path('customers/<int:pk>/edit/', views.CustomerUpdateView.as_view(), name='customer_edit'),
    path('customers/<int:pk>/delete/', views.CustomerDeleteView.as_view(), name='customer_delete'),
    path('customers/<int:pk>/convert/', views.convert_to_customer, name='customer_convert'),
    path('customers/<int:pk>/inline-update/', views.customer_inline_update, name='customer_inline_update'),
]





