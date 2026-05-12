from django.contrib import admin
from .models import (
    Vendor, PurchaseRequest, PurchaseRequestItem,
    PurchaseOrder, PurchaseOrderItem, VendorBill, VendorBillItem, VendorBillAttachment,
)


class VendorBillAttachmentInline(admin.TabularInline):
    model = VendorBillAttachment
    extra = 0
    readonly_fields = ['file', 'filename', 'uploaded_at', 'uploaded_by']


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ['vendor_number', 'name', 'contact_person', 'email', 'phone', 'status']
    list_filter = ['status', 'is_active']
    search_fields = ['vendor_number', 'name', 'email']
    readonly_fields = ['vendor_number']


class PurchaseRequestItemInline(admin.TabularInline):
    model = PurchaseRequestItem
    extra = 1
    autocomplete_fields = ['inventory_item']


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ['pr_number', 'date', 'requested_by', 'status', 'total_amount']
    list_filter = ['status', 'date']
    search_fields = ['pr_number']
    readonly_fields = ['pr_number', 'total_amount']
    inlines = [PurchaseRequestItemInline]


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1
    autocomplete_fields = ['inventory_item']


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ['po_number', 'vendor', 'order_date', 'status', 'total_amount']
    list_filter = ['status', 'order_date']
    search_fields = ['po_number', 'vendor__name']
    readonly_fields = ['po_number', 'subtotal', 'vat_amount', 'total_amount']
    inlines = [PurchaseOrderItemInline]


class VendorBillItemInline(admin.TabularInline):
    model = VendorBillItem
    extra = 1


@admin.register(VendorBill)
class VendorBillAdmin(admin.ModelAdmin):
    list_display = ['bill_number', 'vendor', 'project', 'bill_date', 'due_date', 'status', 'total_amount', 'paid_amount']
    list_filter = ['status', 'bill_date']
    search_fields = ['bill_number', 'vendor__name']
    readonly_fields = ['bill_number', 'subtotal', 'vat_amount', 'total_amount']
    inlines = [VendorBillItemInline, VendorBillAttachmentInline]





