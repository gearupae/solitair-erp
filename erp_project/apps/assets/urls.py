from django.urls import path
from . import views

app_name = 'assets'

urlpatterns = [
    # Asset Categories
    path('categories/', views.AssetCategoryListView.as_view(), name='category_list'),
    path('categories/create/', views.AssetCategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', views.AssetCategoryUpdateView.as_view(), name='category_edit'),
    
    # Fixed Assets
    path('', views.FixedAssetListView.as_view(), name='asset_list'),
    path('create/', views.FixedAssetCreateView.as_view(), name='asset_create'),
    path('<int:pk>/', views.FixedAssetDetailView.as_view(), name='asset_detail'),
    path('<int:pk>/edit/', views.FixedAssetUpdateView.as_view(), name='asset_edit'),
    path('<int:pk>/activate/', views.asset_activate, name='asset_activate'),
    path('<int:pk>/depreciate/', views.asset_depreciate, name='asset_depreciate'),
    path('<int:pk>/dispose/', views.asset_dispose, name='asset_dispose'),
    
    # Depreciation Run
    path('depreciation/run/', views.run_depreciation, name='run_depreciation'),
    
    # Reports
    path('reports/register/', views.asset_register_report, name='register_report'),
    path('reports/depreciation/', views.depreciation_report, name='depreciation_report'),
]




