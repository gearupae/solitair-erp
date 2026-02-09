"""
Property Management Admin
"""
from django.contrib import admin
from .models import (
    Property, Unit, Tenant, Lease, PDCCheque,
    PDCAllocation, PDCAllocationLine, PDCBankMatch, AmbiguousMatchLog
)


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ['property_number', 'name', 'property_type', 'city', 'total_units', 'is_active']
    list_filter = ['property_type', 'city', 'is_active']
    search_fields = ['property_number', 'name', 'address']
    readonly_fields = ['property_number', 'created_at', 'updated_at']


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ['unit_number', 'property', 'unit_type', 'status', 'monthly_rent']
    list_filter = ['property', 'unit_type', 'status']
    search_fields = ['unit_number', 'property__name']


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['tenant_number', 'name', 'email', 'phone', 'status', 'is_active']
    list_filter = ['status', 'is_active']
    search_fields = ['tenant_number', 'name', 'email', 'phone']
    readonly_fields = ['tenant_number', 'created_at', 'updated_at']


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ['lease_number', 'tenant', 'unit', 'start_date', 'end_date', 'annual_rent', 'status']
    list_filter = ['status', 'payment_frequency']
    search_fields = ['lease_number', 'tenant__name', 'unit__unit_number']
    readonly_fields = ['lease_number', 'created_at', 'updated_at']


@admin.register(PDCCheque)
class PDCChequeAdmin(admin.ModelAdmin):
    list_display = [
        'pdc_number', 'cheque_number', 'bank_name', 'cheque_date', 
        'amount', 'tenant', 'status', 'deposit_status'
    ]
    list_filter = ['status', 'deposit_status', 'bank_name', 'purpose']
    search_fields = ['pdc_number', 'cheque_number', 'tenant__name', 'bank_name']
    readonly_fields = ['pdc_number', 'created_at', 'updated_at']
    date_hierarchy = 'cheque_date'
    
    fieldsets = (
        ('Cheque Details', {
            'fields': ('pdc_number', 'cheque_number', 'bank_name', 'cheque_date', 
                      'amount', 'drawer_name', 'drawer_account')
        }),
        ('Tenant & Lease', {
            'fields': ('tenant', 'lease', 'purpose', 'payment_period_start', 'payment_period_end')
        }),
        ('Status', {
            'fields': ('status', 'deposit_status')
        }),
        ('Receipt', {
            'fields': ('received_date', 'received_by')
        }),
        ('Deposit', {
            'fields': ('deposited_date', 'deposited_to_bank', 'deposited_by')
        }),
        ('Clearing', {
            'fields': ('cleared_date', 'clearing_reference')
        }),
        ('Bounce', {
            'fields': ('bounce_date', 'bounce_reason', 'bounce_charges'),
            'classes': ('collapse',)
        }),
        ('Reconciliation', {
            'fields': ('bank_statement_line', 'reconciled', 'reconciled_date', 'reconciled_by'),
            'classes': ('collapse',)
        }),
        ('Accounting', {
            'fields': ('journal_entry', 'pdc_control_journal', 'bounce_journal'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )


class PDCAllocationLineInline(admin.TabularInline):
    model = PDCAllocationLine
    extra = 0
    readonly_fields = ['pdc', 'amount']


@admin.register(PDCAllocation)
class PDCAllocationAdmin(admin.ModelAdmin):
    list_display = ['allocation_number', 'bank_statement_line', 'allocation_date', 'total_amount', 'status']
    list_filter = ['status']
    search_fields = ['allocation_number']
    readonly_fields = ['allocation_number', 'created_at', 'updated_at']
    inlines = [PDCAllocationLineInline]


@admin.register(PDCBankMatch)
class PDCBankMatchAdmin(admin.ModelAdmin):
    list_display = ['bank_statement_line', 'pdc', 'match_status', 'match_score']
    list_filter = ['match_status']


@admin.register(AmbiguousMatchLog)
class AmbiguousMatchLogAdmin(admin.ModelAdmin):
    list_display = ['bank_statement_line', 'detected_at', 'resolution_status', 'resolved_by']
    list_filter = ['resolution_status']
    readonly_fields = ['detected_at', 'matching_pdc_ids', 'match_criteria']




