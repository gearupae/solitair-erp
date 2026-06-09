from django.contrib import admin

from apps.inventory.models_inter_entity import (
    InterEntityTransfer,
    InterEntityTransferLine,
    InterEntityVatTreatment,
)
from apps.purchase.models_grn import GoodsReceiptNote, GRNLine, GRNAttachment
from apps.purchase.models_rfq import RFQ, RFQLine, SupplierQuote, SupplierQuoteLine, RFQAwardLine


@admin.register(InterEntityVatTreatment)
class InterEntityVatTreatmentAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active']


@admin.register(InterEntityTransfer)
class InterEntityTransferAdmin(admin.ModelAdmin):
    list_display = ['transfer_number', 'source_entity', 'destination_entity', 'status', 'transfer_date']
    list_filter = ['status']


@admin.register(GoodsReceiptNote)
class GoodsReceiptNoteAdmin(admin.ModelAdmin):
    list_display = ['grn_number', 'supplier', 'purchase_order', 'status', 'received_on']
    list_filter = ['status']


@admin.register(RFQ)
class RFQAdmin(admin.ModelAdmin):
    list_display = ['rfq_number', 'title', 'status', 'required_by_date']
    list_filter = ['status']
