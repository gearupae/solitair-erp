"""
Sales URL configuration.
"""
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'sales'

urlpatterns = [
    # Estimates (formerly quotations)
    path('estimates/', views.EstimateListView.as_view(), name='estimate_list'),
    path('estimates/items/sample.csv', views.estimate_items_sample_csv, name='estimate_items_sample_csv'),
    path('estimates/create/', views.EstimateCreateView.as_view(), name='estimate_create'),
    path('estimates/<int:pk>/', views.EstimateDetailView.as_view(), name='estimate_detail'),
    path('estimates/<int:pk>/edit/', views.EstimateUpdateView.as_view(), name='estimate_edit'),
    path('estimates/<int:pk>/approve-edit/', views.estimate_approve_edit, name='estimate_approve_edit'),
    path('estimates/<int:pk>/reject-edit/', views.estimate_reject_edit, name='estimate_reject_edit'),
    path('estimates/<int:pk>/duplicate/', views.estimate_duplicate, name='estimate_duplicate'),
    path('estimates/<int:pk>/delete/', views.estimate_delete, name='estimate_delete'),
    path('estimates/<int:pk>/convert/', views.estimate_convert_to_invoice, name='estimate_convert'),
    path('estimates/<int:pk>/convert-project/', views.estimate_convert_to_project, name='estimate_convert_project'),
    path('estimates/<int:pk>/status/<str:status>/', views.estimate_update_status, name='estimate_status'),
    path('estimates/<int:pk>/set-status/', views.estimate_set_status, name='estimate_set_status'),
    path('estimates/<int:pk>/pdf/', views.estimate_pdf, name='estimate_pdf'),
    path('estimates/<int:pk>/pdf/proforma/', views.estimate_proforma_pdf, name='estimate_proforma_pdf'),
    path('estimates/<int:pk>/send-email/', views.estimate_send_email, name='estimate_send_email'),
    path('api/inventory-item/<int:pk>/', views.inventory_item_json, name='inventory_item_json'),

    # Legacy /quotations/ URLs → estimates (permanent redirect)
    path('quotations/', RedirectView.as_view(pattern_name='sales:estimate_list', permanent=True)),
    path('quotations/create/', RedirectView.as_view(pattern_name='sales:estimate_create', permanent=True)),
    path('quotations/<int:pk>/', RedirectView.as_view(pattern_name='sales:estimate_detail', permanent=True)),
    path('quotations/<int:pk>/edit/', RedirectView.as_view(pattern_name='sales:estimate_edit', permanent=True)),
    path('quotations/<int:pk>/delete/', RedirectView.as_view(pattern_name='sales:estimate_delete', permanent=True)),
    path('quotations/<int:pk>/convert/', RedirectView.as_view(pattern_name='sales:estimate_convert', permanent=True)),
    path('quotations/<int:pk>/status/<str:status>/', RedirectView.as_view(pattern_name='sales:estimate_status', permanent=True)),
    path('quotations/<int:pk>/pdf/', RedirectView.as_view(pattern_name='sales:estimate_pdf', permanent=True)),
    path('quotations/<int:pk>/pdf/proforma/', RedirectView.as_view(pattern_name='sales:estimate_proforma_pdf', permanent=True)),
    
    # Invoices
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/create/', views.InvoiceCreateView.as_view(), name='invoice_create'),
    path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:pk>/edit/', views.InvoiceUpdateView.as_view(), name='invoice_edit'),
    path('invoices/<int:pk>/delete/', views.invoice_delete, name='invoice_delete'),
    path('invoices/<int:pk>/post/', views.invoice_post, name='invoice_post'),
    path('invoices/<int:pk>/status/<str:status>/', views.invoice_update_status, name='invoice_status'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('invoices/<int:pk>/receive-payment/', views.invoice_receive_payment, name='invoice_receive_payment'),
]
