from django.contrib import admin
from .models import Quotation, QuotationItem, Invoice, InvoiceItem


class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 1


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ['quotation_number', 'customer', 'date', 'status', 'total_amount', 'is_active']
    list_filter = ['status', 'date', 'is_active']
    search_fields = ['quotation_number', 'customer__name']
    readonly_fields = ['quotation_number', 'subtotal', 'vat_amount', 'total_amount']
    inlines = [QuotationItemInline]


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'customer', 'invoice_date', 'due_date', 'status', 'total_amount', 'paid_amount']
    list_filter = ['status', 'invoice_date', 'is_active']
    search_fields = ['invoice_number', 'customer__name']
    readonly_fields = ['invoice_number', 'subtotal', 'vat_amount', 'total_amount']
    inlines = [InvoiceItemInline]





