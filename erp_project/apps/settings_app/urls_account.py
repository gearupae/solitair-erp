"""User-facing account URLs (not admin settings)."""
from django.urls import path

from . import views_account

app_name = 'account'

urlpatterns = [
    path('', views_account.UserSettingsView.as_view(), name='settings'),
    path('profile/', views_account.MyProfileView.as_view(), name='my_profile'),
    path('modules/', views_account.ModuleRequestView.as_view(), name='module_requests'),
    path('modules/request/', views_account.submit_module_request, name='module_request_submit'),
]
