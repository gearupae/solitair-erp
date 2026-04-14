from django.contrib import admin

from .models import (
    StockTakeLine,
    StockTakeScanLog,
    StockTakeSession,
    StockTakeUnknownScan,
)


class StockTakeLineInline(admin.TabularInline):
    model = StockTakeLine
    extra = 0


@admin.register(StockTakeSession)
class StockTakeSessionAdmin(admin.ModelAdmin):
    list_display = ['client_name', 'location', 'session_date', 'status', 'created_at']
    list_filter = ['status', 'session_date']
    readonly_fields = ['public_scan_token', 'created_at']
    inlines = [StockTakeLineInline]


@admin.register(StockTakeScanLog)
class StockTakeScanLogAdmin(admin.ModelAdmin):
    list_display = ['session', 'barcode_raw', 'sku', 'actual_qty_after', 'matched', 'timestamp']
    list_filter = ['matched']


@admin.register(StockTakeUnknownScan)
class StockTakeUnknownScanAdmin(admin.ModelAdmin):
    list_display = ['session', 'barcode_raw', 'timestamp']
