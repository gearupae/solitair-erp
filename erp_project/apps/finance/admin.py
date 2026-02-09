from django.contrib import admin
from .models import Account, FiscalYear, JournalEntry, JournalEntryLine, TaxCode, Payment, VATReturn


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'account_type', 'balance', 'is_active', 'is_system']
    list_filter = ['account_type', 'is_active', 'is_system']
    search_fields = ['code', 'name']


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_date', 'end_date', 'is_closed']
    list_filter = ['is_closed']


class JournalEntryLineInline(admin.TabularInline):
    model = JournalEntryLine
    extra = 2


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ['entry_number', 'date', 'reference', 'status', 'total_debit', 'total_credit']
    list_filter = ['status', 'date']
    search_fields = ['entry_number', 'reference']
    readonly_fields = ['entry_number', 'total_debit', 'total_credit']
    inlines = [JournalEntryLineInline]


@admin.register(TaxCode)
class TaxCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'rate', 'is_default']
    list_filter = ['is_default']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_number', 'payment_type', 'party_name', 'amount', 'payment_date', 'status']
    list_filter = ['payment_type', 'status', 'payment_method']
    search_fields = ['payment_number', 'party_name', 'reference']
    readonly_fields = ['payment_number']


@admin.register(VATReturn)
class VATReturnAdmin(admin.ModelAdmin):
    list_display = ['period_start', 'period_end', 'output_vat', 'input_vat', 'net_vat', 'status']
    list_filter = ['status']





