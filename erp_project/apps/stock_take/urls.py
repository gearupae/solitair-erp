from django.urls import path

from . import views

app_name = 'stock_take'

urlpatterns = [
    path('camera/<uuid:token>/', views.PublicScanCameraView.as_view(), name='public_camera'),
    path('camera/<uuid:token>/scan/', views.public_record_scan, name='public_record_scan'),
    path('', views.SessionListView.as_view(), name='session_list'),
    path('sessions/new/', views.SessionCreateView.as_view(), name='session_create'),
    path('sessions/<int:pk>/', views.ScanView.as_view(), name='session_scan'),
    path(
        'sessions/<int:pk>/expected-template.xlsx',
        views.ExpectedTemplateDownloadView.as_view(),
        name='expected_template',
    ),
    path('sessions/<int:pk>/upload/', views.session_upload_expected, name='session_upload'),
    path('sessions/<int:pk>/scan/', views.record_scan, name='record_scan'),
    path('sessions/<int:pk>/complete/', views.session_complete, name='session_complete'),
    path('sessions/<int:pk>/report/', views.ReportView.as_view(), name='session_report'),
]
