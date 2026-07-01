from django.contrib import admin

from . import models


@admin.register(models.ProductTemplate)
class ProductTemplateAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'company')
    search_fields = ('code', 'name')


@admin.register(models.TemplateBOMItem)
class TemplateBOMItemAdmin(admin.ModelAdmin):
    list_display = ('part_name', 'template', 'quantity', 'unit')


@admin.register(models.TemplateRoutingOp)
class TemplateRoutingOpAdmin(admin.ModelAdmin):
    list_display = ('template', 'work_center', 'sequence', 'std_time_minutes')


@admin.register(models.ProductionOrderStatusLog)
class ProductionOrderStatusLogAdmin(admin.ModelAdmin):
    list_display = ('production_order', 'from_status', 'to_status', 'changed_at', 'changed_by')
    list_filter = ('to_status',)


@admin.register(models.WorkCenter)
class WorkCenterAdmin(admin.ModelAdmin):
    list_display = (
        'code', 'name', 'sequence_order', 'center_type',
        'cost_per_hour', 'is_production_step', 'is_qc_gate', 'company',
    )
    list_filter = ('company', 'center_type', 'is_production_step', 'is_qc_gate')
    search_fields = ('code', 'name')


@admin.register(models.ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'reference', 'status', 'quantity', 'due_date', 'released_at', 'wip_value', 'company')
    list_filter = ('status', 'company')
    search_fields = ('po_number', 'reference')


class BOMItemInline(admin.TabularInline):
    model = models.BOMItem
    extra = 0
    fk_name = 'production_order'
    fields = ('parent', 'part_name', 'material_type', 'quantity', 'unit', 'item_code')


@admin.register(models.BOMItem)
class BOMItemAdmin(admin.ModelAdmin):
    list_display = ('part_name', 'item_code', 'material_type', 'quantity', 'unit_cost', 'production_order')
    list_filter = ('material_type',)


@admin.register(models.Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ('barcode', 'production_order', 'status', 'current_work_center')
    search_fields = ('barcode',)
    list_filter = ('status',)


@admin.register(models.PartScan)
class PartScanAdmin(admin.ModelAdmin):
    list_display = ('part', 'work_center', 'scan_type', 'operator', 'timestamp')
    readonly_fields = ('part', 'work_center', 'operator', 'scan_type', 'machine', 'timestamp', 'company')


@admin.register(models.Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ('name', 'work_center', 'protocol', 'is_online')


@admin.register(models.OracleSyncLog)
class OracleSyncLogAdmin(admin.ModelAdmin):
    list_display = ('entity', 'direction', 'status', 'retry_count', 'created_at')
    list_filter = ('direction', 'status')


@admin.register(models.RoutingOperation)
class RoutingOperationAdmin(admin.ModelAdmin):
    list_display = (
        'production_order', 'work_center', 'sequence',
        'std_time_minutes', 'rate_per_hour', 'status',
    )
