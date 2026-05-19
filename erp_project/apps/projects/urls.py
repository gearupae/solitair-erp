from django.urls import path
from . import views

app_name = 'projects'

urlpatterns = [
    # Public (no auth) — must be before <int:pk> routes
    path('public-upload/', views.public_project_upload, name='public_upload'),
    # Projects
    path('', views.ProjectListView.as_view(), name='project_list'),
    path('create/', views.ProjectCreateView.as_view(), name='project_create'),
    path('tasks/', views.TaskListView.as_view(), name='task_list'),
    path('<int:pk>/report/pdf/', views.project_report_pdf, name='project_report_pdf'),
    path('<int:project_pk>/gatepass/<int:pk>/delete/', views.project_gatepass_delete, name='project_gatepass_delete'),
    path('<int:pk>/approve-edit/', views.project_approve_edit, name='project_approve_edit'),
    path('<int:pk>/reject-edit/', views.project_reject_edit, name='project_reject_edit'),
    path('<int:pk>/', views.ProjectDetailView.as_view(), name='project_detail'),
    path('<int:pk>/edit/', views.ProjectUpdateView.as_view(), name='project_edit'),
    
    # Tasks
    path('tasks/<int:pk>/set-status/', views.task_set_status, name='task_set_status'),
    path('tasks/<int:pk>/status/<str:status>/', views.task_update_status, name='task_status'),
    
    # Project Expenses
    path('expenses/', views.ProjectExpenseListView.as_view(), name='expense_list'),
    path('expenses/create/', views.ProjectExpenseCreateView.as_view(), name='expense_create'),
    path('expenses/<int:pk>/', views.ProjectExpenseDetailView.as_view(), name='expense_detail'),
    path('expenses/<int:pk>/edit/', views.ProjectExpenseUpdateView.as_view(), name='expense_edit'),
    path('expenses/<int:pk>/approve/', views.expense_approve, name='expense_approve'),
    path('expenses/<int:pk>/reject/', views.expense_reject, name='expense_reject'),
    path('expenses/<int:pk>/post/', views.expense_post_to_accounting, name='expense_post'),
]


