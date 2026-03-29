from django.urls import path

from . import views

app_name = 'contracts'

urlpatterns = [
    path('', views.ContractListView.as_view(), name='contract_list'),
    path('<int:pk>/edit/', views.ContractUpdateView.as_view(), name='contract_edit'),
    path('<int:pk>/pdf/', views.contract_pdf, name='contract_pdf'),
    path('<int:pk>/inline-update/', views.contract_inline_update, name='contract_inline_update'),
    path('<int:pk>/delete/', views.contract_delete, name='contract_delete'),
]
