"""
URL configuration for ERP Project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Authentication
    path('login/', auth_views.LoginView.as_view(template_name='auth/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Apps
    path('', include('apps.core.urls')),
    path('settings/', include('apps.settings_app.urls')),
    path('crm/', include('apps.crm.urls')),
    path('sales/', include('apps.sales.urls')),
    path('purchase/', include('apps.purchase.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('finance/', include('apps.finance.urls')),
    path('projects/', include('apps.projects.urls')),
    path('assets/', include('apps.assets.urls')),
    path('property/', include('apps.property.urls')),
    path('hr/', include('apps.hr.urls')),
    path('documents/', include('apps.documents.urls')),
    path('service-request/', include('apps.service_request.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

