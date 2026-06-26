"""
Settings app URL configuration.
"""
from django.urls import path
from . import views
from . import views_ceo

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
    path('stripe/ai-checkout/', views.stripe_ai_checkout, name='stripe_ai_checkout'),
    path('stripe/ai-intent/', views.stripe_ai_payment_intent, name='stripe_ai_payment_intent'),
    path('stripe/ai-confirm/', views.stripe_ai_confirm_payment, name='stripe_ai_confirm_payment'),
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('companies/', views.CompanyListView.as_view(), name='company_list'),
    path('companies/create/', views.CompanyCreateView.as_view(), name='company_create'),
    path('companies/<int:pk>/edit/', views.CompanyUpdateView.as_view(), name='company_edit'),
    
    # Audit Log
    path('audit-log/', views.AuditLogListView.as_view(), name='audit_log'),
    
    # Approval Configuration
    path('approval-configuration/', views.ApprovalConfigurationView.as_view(), name='approval_configuration'),
    path('crm-kanban/', views.CrmKanbanSettingsView.as_view(), name='crm_kanban'),
    path(
        'sub-group-expense-types/',
        views.SubGroupExpenseTypeSettingsView.as_view(),
        name='sub_group_expense_types',
    ),
    path('ceo/', views_ceo.CeoDashboardView.as_view(), name='ceo_dashboard'),
    path('ceo/ask/', views_ceo.ceo_ask_business, name='ceo_ask'),
]





