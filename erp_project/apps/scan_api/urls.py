from django.urls import path

from . import views

app_name = 'scan_api'

urlpatterns = [
    path('auth/login/', views.api_login, name='api_login'),
    path('auth/logout/', views.api_logout, name='api_logout'),
    path('auth/me/', views.api_me, name='api_me'),
    path('stock-take/sessions/', views.api_stock_take_sessions, name='api_stock_take_sessions'),
    path('stock-take/sessions/<int:pk>/', views.api_stock_take_session_detail, name='api_stock_take_session_detail'),
    path('stock-take/sessions/<int:pk>/scan/', views.api_stock_take_scan, name='api_stock_take_scan'),
]
