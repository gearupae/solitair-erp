from django.contrib import admin

from .models import OperationsSettings, StaffDutySchedule


@admin.register(StaffDutySchedule)
class StaffDutyScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'duty_date',
        'start_time',
        'end_time',
        'link_type',
        'status',
        'project',
        'amc_contract',
    )
    list_filter = ('status', 'link_type', 'duty_date')
    search_fields = (
        'employee__first_name',
        'employee__last_name',
        'project__name',
        'amc_contract__name',
        'location',
        'contact_person_name',
        'contact_person_phone',
    )
    raw_id_fields = ('employee', 'project', 'amc_contract')


@admin.register(OperationsSettings)
class OperationsSettingsAdmin(admin.ModelAdmin):
    list_display = ('pk', 'public_schedule_token')
