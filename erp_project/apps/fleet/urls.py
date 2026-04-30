from django.urls import path

from . import views

app_name = 'fleet'

urlpatterns = [
    path('', views.VehicleListView.as_view(), name='vehicle_list'),
    path('add/', views.VehicleCreateView.as_view(), name='vehicle_create'),
    path('<int:pk>/edit/', views.VehicleUpdateView.as_view(), name='vehicle_edit'),
]
