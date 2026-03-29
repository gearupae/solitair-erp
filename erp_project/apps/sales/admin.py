from django.contrib import admin
from .models import Estimate, EstimateItem, Invoice, InvoiceItem


class EstimateItemInline(admin.TabularInline):
    model = EstimateItem
    extra = 0


@admin.register(Estimate)
class EstimateAdmin(admin.ModelAdmin):
    list_display = ['estimate_number', 'customer', 'date', 'status', 'total_amount', 'is_active']
    list_filter = ['status', 'is_active', 'date']
    search_fields = ['estimate_number', 'customer__name']
    readonly_fields = ['estimate_number', 'subtotal', 'vat_amount', 'total_amount']
    inlines = [EstimateItemInline]


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'customer', 'invoice_date', 'estimate', 'status', 'total_amount', 'is_active']
    list_filter = ['status', 'is_active', 'invoice_date']
    search_fields = ['invoice_number', 'customer__name']
    readonly_fields = ['invoice_number', 'subtotal', 'vat_amount', 'total_amount', 'paid_amount']
    inlines = [InvoiceItemInline]
