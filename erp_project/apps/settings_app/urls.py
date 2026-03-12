"""
Settings app URL configuration.
"""
from django.urls import path
from . import views

app_name = 'settings'

urlpatterns = [
    # User Management
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/toggle/', views.toggle_user_status, name='user_toggle'),
    
    # Role Management
    path('roles/', views.RoleListView.as_view(), name='role_list'),
    path('roles/create/', views.RoleCreateView.as_view(), name='role_create'),
    path('roles/<int:pk>/edit/', views.RoleUpdateView.as_view(), name='role_edit'),
    path('roles/<int:pk>/permissions/', views.RolePermissionView.as_view(), name='role_permissions'),
    
    # Company Settings
    path('company/', views.CompanySettingsView.as_view(), name='company'),
    
    # Audit Log
    path('audit-log/', views.AuditLogListView.as_view(), name='audit_log'),
    
    # Approval Configuration
    path('approval-configuration/', views.ApprovalConfigurationView.as_view(), name='approval_configuration'),
]





