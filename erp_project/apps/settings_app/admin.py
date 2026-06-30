from django.contrib import admin
from .models import (
    Role,
    Permission,
    RolePermission,
    UserRole,
    UserProfile,
    CompanySettings,
    Company,
    EstimateTextTemplate,
    PurchaseOrderTermsTemplate,
    ItemSubGroupExpenseType,
    NumberSeries,
    AuditLog,
    ApprovalWorkflow,
    ModulePermission,
    CashFlowMonthSheet,
    CashFlowIncomeLine,
    CashFlowChequeLine,
    CashFlowExpenseLine,
)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'is_system_role', 'is_active']
    list_filter = ['is_system_role', 'is_active']
    search_fields = ['name', 'code']


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['name', 'module', 'code', 'permission_type']
    list_filter = ['module', 'permission_type']
    search_fields = ['name', 'code']


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ['role', 'permission', 'can_create', 'can_read', 'can_update', 'can_delete', 'can_approve']
    list_filter = ['role', 'permission__module']


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'assigned_date', 'is_active']
    list_filter = ['role', 'is_active']
    search_fields = ['user__username', 'role__name']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone', 'timezone']
    search_fields = ['user__username', 'phone']


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'email', 'phone', 'currency']


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'country', 'mol_number', 'trade_license_number', 'is_active']
    list_filter = ['country', 'is_active']
    search_fields = ['name', 'trade_license_number']


@admin.register(ItemSubGroupExpenseType)
class ItemSubGroupExpenseTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'sort_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name']


@admin.register(EstimateTextTemplate)
class EstimateTextTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'template_type', 'is_default', 'sort_order', 'is_active']
    list_filter = ['template_type', 'is_default', 'is_active']
    search_fields = ['name', 'body']


@admin.register(PurchaseOrderTermsTemplate)
class PurchaseOrderTermsTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_default', 'sort_order', 'is_active']
    list_filter = ['is_default', 'is_active']
    search_fields = ['name', 'body']


@admin.register(NumberSeries)
class NumberSeriesAdmin(admin.ModelAdmin):
    list_display = ['document_type', 'prefix', 'next_number', 'padding']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'user', 'action', 'model', 'record_id', 'ip_address']
    list_filter = ['action', 'model', 'timestamp']
    search_fields = ['user__username', 'model', 'record_id']
    readonly_fields = ['user', 'action', 'model', 'record_id', 'changes', 'timestamp', 'ip_address']


@admin.register(ApprovalWorkflow)
class ApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = ['module', 'approver', 'auto_approve', 'is_active']
    list_filter = ['module', 'auto_approve', 'is_active']


@admin.register(ModulePermission)
class ModulePermissionAdmin(admin.ModelAdmin):
    list_display = ['role', 'module', 'can_view', 'can_create', 'can_edit', 'can_delete']
    list_filter = ['role', 'module']
    search_fields = ['role__name', 'module']


@admin.register(CashFlowMonthSheet)
class CashFlowMonthSheetAdmin(admin.ModelAdmin):
    list_display = ['year', 'month', 'cash_bank_in_hand', 'updated_at', 'is_active']
    list_filter = ['year', 'is_active']


class CashFlowIncomeLineInline(admin.TabularInline):
    model = CashFlowIncomeLine
    extra = 0


class CashFlowChequeLineInline(admin.TabularInline):
    model = CashFlowChequeLine
    extra = 0


class CashFlowExpenseLineInline(admin.TabularInline):
    model = CashFlowExpenseLine
    extra = 0


CashFlowMonthSheetAdmin.inlines = [
    CashFlowIncomeLineInline,
    CashFlowChequeLineInline,
    CashFlowExpenseLineInline,
]

