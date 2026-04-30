from django.contrib import admin

from .models import Vehicle, VehicleOtherDocument


class VehicleOtherDocumentInline(admin.TabularInline):
    model = VehicleOtherDocument
    extra = 0


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['plate_number', 'make', 'model', 'driver', 'mulkiya_expiry', 'insurance_expiry', 'is_active']
    list_filter = ['is_active']
    search_fields = ['plate_number', 'make', 'model']
    raw_id_fields = ['driver']
    inlines = [VehicleOtherDocumentInline]


@admin.register(VehicleOtherDocument)
class VehicleOtherDocumentAdmin(admin.ModelAdmin):
    list_display = ['document_name', 'vehicle', 'expiry_date', 'is_active']
    list_filter = ['is_active']
    search_fields = ['document_name', 'vehicle__plate_number']
