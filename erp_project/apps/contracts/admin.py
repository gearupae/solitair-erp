from django.contrib import admin

from .models import Contract, ContractAttachment, ContractDocumentExpiry, ContractType


@admin.register(ContractType)
class ContractTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active']
    search_fields = ['name']


class ContractAttachmentInline(admin.TabularInline):
    model = ContractAttachment
    extra = 0


class ContractDocumentExpiryInline(admin.TabularInline):
    model = ContractDocumentExpiry
    extra = 0
    fields = ['document_name', 'expiry_date', 'remind_before_days', 'is_active']


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ['contract_number', 'name', 'customer', 'contract_value', 'start_date', 'end_date', 'status', 'is_active']
    list_filter = ['start_date', 'end_date']
    search_fields = ['contract_number', 'name', 'customer__name']
    raw_id_fields = ['customer']
    filter_horizontal = ('contract_types',)
    inlines = [ContractAttachmentInline, ContractDocumentExpiryInline]
