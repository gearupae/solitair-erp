"""MES URL configuration."""

from django.urls import path

from . import api_views, views, views_actual, views_templates

app_name = 'mes'

urlpatterns = [
    path('', views.MesIndexView.as_view(), name='index'),
    path('work-centers/', views.WorkCenterListView.as_view(), name='work_center_list'),
    path('work-centers/new/', views.WorkCenterCreateView.as_view(), name='work_center_create'),
    path('work-centers/<int:pk>/edit/', views.WorkCenterUpdateView.as_view(), name='work_center_edit'),
    path('work-centers/<int:pk>/delete/', views.WorkCenterDeleteView.as_view(), name='work_center_delete'),
    path('product-templates/', views_templates.ProductTemplateListView.as_view(), name='product_template_list'),
    path('product-templates/new/', views_templates.ProductTemplateCreateView.as_view(), name='product_template_create'),
    path('product-templates/<int:pk>/', views_templates.ProductTemplateDetailView.as_view(), name='product_template_detail'),
    path('product-templates/<int:pk>/edit/', views_templates.ProductTemplateUpdateView.as_view(), name='product_template_edit'),
    path('product-templates/<int:pk>/delete/', views_templates.ProductTemplateDeleteView.as_view(), name='product_template_delete'),
    path(
        'product-templates/<int:template_pk>/bom/new/',
        views_templates.TemplateBOMItemCreateView.as_view(),
        name='template_bom_create',
    ),
    path(
        'product-templates/<int:template_pk>/bom/<int:pk>/edit/',
        views_templates.TemplateBOMItemUpdateView.as_view(),
        name='template_bom_edit',
    ),
    path(
        'product-templates/<int:template_pk>/bom/<int:pk>/delete/',
        views_templates.TemplateBOMItemDeleteView.as_view(),
        name='template_bom_delete',
    ),
    path(
        'product-templates/<int:template_pk>/routing/new/',
        views_templates.TemplateRoutingOpCreateView.as_view(),
        name='template_routing_create',
    ),
    path(
        'product-templates/<int:template_pk>/routing/<int:pk>/delete/',
        views_templates.TemplateRoutingOpDeleteView.as_view(),
        name='template_routing_delete',
    ),
    path('production-orders/', views.ProductionOrderListView.as_view(), name='production_order_list'),
    path('production-orders/new/', views.ProductionOrderCreateView.as_view(), name='production_order_create'),
    path('production-orders/<int:pk>/', views.ProductionOrderDetailView.as_view(), name='production_order_detail'),
    path('production-orders/<int:pk>/edit/', views.ProductionOrderUpdateView.as_view(), name='production_order_edit'),
    path('production-orders/<int:pk>/delete/', views.ProductionOrderDeleteView.as_view(), name='production_order_delete'),
    path(
        'production-orders/<int:pk>/generate-parts/',
        views.GeneratePartsView.as_view(),
        name='production_order_generate_parts',
    ),
    path(
        'production-orders/<int:pk>/release/',
        views.ReleaseProductionOrderView.as_view(),
        name='production_order_release',
    ),
    path(
        'production-orders/<int:pk>/pipeline/',
        views.PipelineAdvanceView.as_view(),
        name='production_order_pipeline',
    ),
    path(
        'production-orders/<int:pk>/team/',
        views.ProductionOrderTeamAssignView.as_view(),
        name='production_order_team',
    ),
    path(
        'production-orders/<int:po_pk>/routing/<int:pk>/team/',
        views.RoutingOperationTeamPageView.as_view(),
        name='routing_operation_team_page',
    ),
    path(
        'production-orders/<int:po_pk>/routing/new/',
        views.RoutingOperationCreateView.as_view(),
        name='routing_operation_create',
    ),
    path(
        'production-orders/<int:po_pk>/routing/<int:pk>/edit/',
        views.RoutingOperationUpdateView.as_view(),
        name='routing_operation_edit',
    ),
    path(
        'production-orders/<int:po_pk>/routing/<int:pk>/delete/',
        views.RoutingOperationDeleteView.as_view(),
        name='routing_operation_delete',
    ),
    path(
        'production-orders/<int:po_pk>/routing/<int:pk>/move/<str:direction>/',
        views.RoutingOperationReorderView.as_view(),
        name='routing_operation_reorder',
    ),
    path(
        'production-orders/<int:po_pk>/bom/new/',
        views.BOMItemCreateView.as_view(),
        name='bom_item_create',
    ),
    path(
        'production-orders/<int:po_pk>/bom/<int:pk>/edit/',
        views.BOMItemUpdateView.as_view(),
        name='bom_item_edit',
    ),
    path(
        'production-orders/<int:po_pk>/bom/<int:pk>/delete/',
        views.BOMItemDeleteView.as_view(),
        name='bom_item_delete',
    ),
    path(
        'production-orders/<int:po_pk>/parts/new/',
        views.PartCreateView.as_view(),
        name='part_create',
    ),
    path(
        'production-orders/<int:po_pk>/parts/<int:pk>/edit/',
        views.PartUpdateView.as_view(),
        name='part_edit',
    ),
    path(
        'production-orders/<int:po_pk>/parts/<int:pk>/delete/',
        views.PartDeleteView.as_view(),
        name='part_delete',
    ),
    path('tablet/', views.tablet_home, name='tablet'),
    path('api/scan/', api_views.scan_api, name='api_scan'),
    path('api/station-queue/', api_views.station_queue_api, name='api_station_queue'),
    path('api/gearup-agent/', api_views.gearup_agent_api, name='api_gearup_agent'),
    path('api/checklist-complete/', api_views.checklist_complete_api, name='api_checklist_complete'),
    path(
        'production-orders/<int:po_pk>/bom/<int:bom_pk>/drawings/',
        api_views.bom_drawings_api,
        name='api_bom_drawings',
    ),
    path('api/drawings/<int:pk>/release/', api_views.drawing_release_api, name='api_drawing_release'),
    path('api/drawings/<int:pk>/delete/', api_views.drawing_delete_api, name='api_drawing_delete'),
    path('parts/<int:pk>/label/', views.part_label, name='part_label'),
    path('oracle-sync-log/', views.OracleSyncLogListView.as_view(), name='oracle_sync_log'),
    path('oracle/pull/', views.OraclePullView.as_view(), name='oracle_pull'),
    path('oracle/pull/run/', views.OraclePullExecuteView.as_view(), name='oracle_pull_run'),
    path('actual/', views_actual.ActualCountView.as_view(), name='actual'),
    path('api/actual/capture/', api_views.actual_count_capture_api, name='api_actual_capture'),
    path('api/actual/increment/', api_views.actual_count_increment_api, name='api_actual_increment'),
    path('api/actual/reset/', api_views.actual_count_reset_api, name='api_actual_reset'),
]
