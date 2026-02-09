from django.contrib import admin
from .models import DocumentType, Document

@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'alert_days_before']

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['document_type', 'entity_type', 'entity_name', 'expiry_date', 'status']
    list_filter = ['document_type', 'entity_type', 'expiry_date']
    search_fields = ['entity_name', 'document_number']





