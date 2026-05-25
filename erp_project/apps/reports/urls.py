from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_index, name='index'),
    path('leads/', views.lead_report, name='lead_report'),
    path('sales/', views.sales_report, name='sales_report'),
    path('projects/internal/', views.project_report_internal, name='project_report_internal'),
    path('projects/customer/', views.project_report_customer, name='project_report_customer'),
    path('projects/period/', views.project_report_period, name='project_report_period'),
]
