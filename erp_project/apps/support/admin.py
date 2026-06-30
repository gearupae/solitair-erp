from django.contrib import admin

from .models import SupportTicket, SupportTicketKanbanStage


@admin.register(SupportTicketKanbanStage)
class SupportTicketKanbanStageAdmin(admin.ModelAdmin):
    list_display = ('name', 'sort_order', 'is_active', 'is_closed')
    list_filter = ('is_active', 'is_closed')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_number',
        'subject',
        'link_type',
        'priority',
        'opened_date',
        'assigned_to',
        'kanban_stage',
    )
    list_filter = ('priority', 'link_type', 'kanban_stage', 'opened_date')
    search_fields = ('ticket_number', 'subject', 'description')
    raw_id_fields = ('customer', 'project', 'amc_contract', 'assigned_to')
