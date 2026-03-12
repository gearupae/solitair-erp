"""
Service Request URL configuration.
"""
from django.urls import path
from . import views

app_name = 'service_request'

urlpatterns = [
    path('', views.ServiceRequestListView.as_view(), name='sr_list'),
    path('create/', views.ServiceRequestCreateView.as_view(), name='sr_create'),
    path('<int:pk>/', views.ServiceRequestDetailView.as_view(), name='sr_detail'),
    path('<int:pk>/edit/', views.ServiceRequestUpdateView.as_view(), name='sr_edit'),
    path('<int:pk>/delete/', views.sr_delete, name='sr_delete'),
    path('<int:pk>/submit/', views.sr_submit, name='sr_submit'),
    path('<int:pk>/approve/', views.sr_approve, name='sr_approve'),
    path('<int:pk>/reject/', views.sr_reject, name='sr_reject'),
    path('<int:pk>/return/', views.sr_return, name='sr_return'),
    path('<int:pk>/convert/', views.sr_convert, name='sr_convert'),
    path('<int:pk>/items/', views.sr_items_json, name='sr_items_json'),
]
