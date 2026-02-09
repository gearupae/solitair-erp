from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['customer_number', 'name', 'company', 'email', 'phone', 'customer_type', 'status', 'is_active']
    list_filter = ['customer_type', 'status', 'is_active', 'created_at']
    search_fields = ['customer_number', 'name', 'company', 'email', 'phone']
    readonly_fields = ['customer_number', 'created_at', 'updated_at', 'created_by', 'updated_by']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('customer_number', 'name', 'company', 'customer_type')
        }),
        ('Contact Details', {
            'fields': ('email', 'phone', 'address')
        }),
        ('Status', {
            'fields': ('status', 'is_active', 'notes')
        }),
        ('Audit Trail', {
            'fields': ('created_at', 'updated_at', 'created_by', 'updated_by'),
            'classes': ('collapse',)
        }),
    )





