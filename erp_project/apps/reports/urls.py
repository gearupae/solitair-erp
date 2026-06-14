from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_index, name='index'),
    path('leads/', views.lead_report, name='lead_report'),
    path('lead-forecasting/', views.LeadForecastingView.as_view(), name='lead_forecasting'),
    path(
        'lead-forecasting/regenerate-brief/',
        views.lead_forecasting_regenerate_brief,
        name='lead_forecasting_regenerate_brief',
    ),
    path('sales/', views.sales_report, name='sales_report'),
    path('sales-forecasting/', views.SalesForecastingView.as_view(), name='sales_forecasting'),
    path(
        'sales-forecasting/regenerate-brief/',
        views.sales_forecasting_regenerate_brief,
        name='sales_forecasting_regenerate_brief',
    ),
    path('projects/internal/', views.project_report_internal, name='project_report_internal'),
    path('projects/customer/', views.project_report_customer, name='project_report_customer'),
    path('projects/period/', views.project_report_period, name='project_report_period'),
    path('project-forecasting/', views.ProjectForecastingView.as_view(), name='project_forecasting'),
    path(
        'project-forecasting/regenerate-brief/',
        views.project_forecasting_regenerate_brief,
        name='project_forecasting_regenerate_brief',
    ),
]
