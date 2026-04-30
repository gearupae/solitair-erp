from django.contrib import admin
from .models import Project, Task, Timesheet, ProjectGatepass

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['project_code', 'name', 'customer', 'manager', 'status', 'start_date', 'end_date']
    list_filter = ['status', 'start_date']
    search_fields = ['project_code', 'name']
    filter_horizontal = ('members',)

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'assigned_to', 'status', 'priority', 'start_date', 'due_date']
    list_filter = ['status', 'priority', 'project']
    search_fields = ['name', 'project__project_code', 'project__name']
    raw_id_fields = ['project', 'assigned_to']

@admin.register(ProjectGatepass)
class ProjectGatepassAdmin(admin.ModelAdmin):
    list_display = ['project', 'member', 'start_date', 'expiry_date', 'reference_number', 'is_active']
    list_filter = ['is_active', 'expiry_date']
    search_fields = ['project__project_code', 'project__name', 'member__username', 'reference_number']
    raw_id_fields = ['project', 'member']
    date_hierarchy = 'expiry_date'


@admin.register(Timesheet)
class TimesheetAdmin(admin.ModelAdmin):
    list_display = ['task', 'user', 'date', 'hours']
    list_filter = ['date', 'user']





