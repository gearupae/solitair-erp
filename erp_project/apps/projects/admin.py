from django.contrib import admin
from .models import Project, Task, Timesheet

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['project_code', 'name', 'customer', 'manager', 'status', 'start_date', 'end_date']
    list_filter = ['status', 'start_date']
    search_fields = ['project_code', 'name']

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'assigned_to', 'status', 'priority', 'due_date']
    list_filter = ['status', 'priority']

@admin.register(Timesheet)
class TimesheetAdmin(admin.ModelAdmin):
    list_display = ['task', 'user', 'date', 'hours']
    list_filter = ['date', 'user']





