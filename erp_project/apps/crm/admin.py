from django.contrib import admin
from .models import Customer, CustomerPublicUpload, CrmLeadKanbanStage


@admin.register(CrmLeadKanbanStage)
class CrmLeadKanbanStageAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'sort_order', 'is_active', 'converts_to_customer', 'is_site_visit']
    list_filter = ['is_active', 'converts_to_customer', 'is_site_visit']
    search_fields = ['name', 'slug']
    ordering = ['sort_order', 'id']


@admin.register(CustomerPublicUpload)
class CustomerPublicUploadAdmin(admin.ModelAdmin):
    list_display = ['customer', 'original_filename', 'note', 'created_at', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['original_filename', 'note', 'customer__customer_number', 'customer__name', 'customer__company']
    raw_id_fields = ['customer']
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = [
        'customer_number',
        'name',
        'company',
        'email',
        'phone',
        'customer_type',
        'assigned_salesperson',
        'business_segment',
        'status',
        'is_active',
    ]
    list_filter = ['customer_type', 'status', 'is_active', 'created_at']
    search_fields = ['customer_number', 'name', 'company', 'email', 'phone', 'trn', 'website', 'job_type']
    readonly_fields = ['customer_number', 'created_at', 'updated_at', 'created_by', 'updated_by']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'customer_number',
                'name',
                'company',
                'customer_type',
                'business_segment',
                'lead_kanban_stage',
                'assigned_salesperson',
            )
        }),
        ('Contact Details', {
            'fields': ('email', 'phone', 'address', 'city', 'country')
        }),
        ('Business', {
            'fields': (
                'trn',
                'trn_document',
                'trade_license_document',
                'website',
                'job_type',
                'scope',
                'primary_project',
                'payment_terms',
                'credit_limit',
            )
        }),
        ('Status', {
            'fields': ('status', 'is_active', 'notes')
        }),
        ('Audit Trail', {
            'fields': ('created_at', 'updated_at', 'created_by', 'updated_by'),
            'classes': ('collapse',)
        }),
    )





