from django.urls import path

from . import views
from . import ai_finance_views

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
    # AI Finance
    path('ai-finance/', ai_finance_views.AiFinanceIndexView.as_view(), name='ai_finance_index'),
    path('ai-finance/cash-flow/', ai_finance_views.CashFlowForecastView.as_view(), name='ai_finance_cash_flow'),
    path('ai-finance/revenue/', ai_finance_views.RevenueForecastView.as_view(), name='ai_finance_revenue'),
    path('ai-finance/expense/', ai_finance_views.ExpenseForecastView.as_view(), name='ai_finance_expense'),
    path('ai-finance/receivables/', ai_finance_views.ReceivablesForecastView.as_view(), name='ai_finance_receivables'),
    path('ai-finance/anomaly/', ai_finance_views.AnomalyDetectionView.as_view(), name='ai_finance_anomaly'),
    path('api/ai-finance/cash-flow-forecast/', ai_finance_views.CashFlowForecastApiView.as_view(), name='api_ai_finance_cash_flow'),
    path('api/ai-finance/revenue-forecast/', ai_finance_views.RevenueForecastApiView.as_view(), name='api_ai_finance_revenue'),
    path('api/ai-finance/expense-forecast/', ai_finance_views.ExpenseForecastApiView.as_view(), name='api_ai_finance_expense'),
    path('api/ai-finance/receivables-forecast/', ai_finance_views.ReceivablesForecastApiView.as_view(), name='api_ai_finance_receivables'),
    path('api/ai-finance/anomaly-detection/', ai_finance_views.AnomalyDetectionApiView.as_view(), name='api_ai_finance_anomaly'),
]
