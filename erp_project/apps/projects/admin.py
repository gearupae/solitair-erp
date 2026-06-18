from django.contrib import admin
from .models import Project, Task, ProjectGatepass, ProjectPublicUpload, ProjectItemLine, ProjectChecklistItem, ProjectChecklistUpload


class ProjectItemLineInline(admin.TabularInline):
    model = ProjectItemLine
    extra = 0
    fields = ('sort_order', 'group_name', 'description', 'inventory_item', 'quantity', 'unit_price', 'rate', 'line_net', 'vat_amount')
    raw_id_fields = ('inventory_item',)
    show_change_link = True


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['project_code', 'name', 'customer', 'manager', 'status', 'start_date', 'end_date']
    list_filter = ['status', 'start_date']
    search_fields = ['project_code', 'name']
    filter_horizontal = ('members', 'technicians')
    inlines = (ProjectItemLineInline,)

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'customer', 'assigned_to', 'status', 'priority', 'start_date', 'due_date']
    list_filter = ['status', 'priority', 'project', 'customer']
    search_fields = ['name', 'project__project_code', 'project__name', 'customer__customer_number', 'customer__name']
    raw_id_fields = ['project', 'customer', 'assigned_to']

@admin.register(ProjectGatepass)
class ProjectGatepassAdmin(admin.ModelAdmin):
    list_display = ['project', 'member', 'start_date', 'expiry_date', 'reference_number', 'is_active']
    list_filter = ['is_active', 'expiry_date']
    search_fields = ['project__project_code', 'project__name', 'member__username', 'reference_number']
    raw_id_fields = ['project', 'member']
    date_hierarchy = 'expiry_date'


@admin.register(ProjectPublicUpload)
class ProjectPublicUploadAdmin(admin.ModelAdmin):
    list_display = ['project', 'original_filename', 'note', 'created_at', 'is_active']
    list_filter = ['is_active', 'created_at', 'project']
    search_fields = ['original_filename', 'note', 'project__project_code', 'project__name']
    raw_id_fields = ['project']
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']


@admin.register(ProjectChecklistItem)
class ProjectChecklistItemAdmin(admin.ModelAdmin):
    list_display = ['project', 'text', 'item_date', 'is_flagged_red', 'is_active']
    list_filter = ['is_flagged_red', 'is_active']
    search_fields = ['text', 'project__project_code']
    raw_id_fields = ['project']


@admin.register(ProjectChecklistUpload)
class ProjectChecklistUploadAdmin(admin.ModelAdmin):
    list_display = ['project', 'original_filename', 'checklist_item', 'created_at', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['original_filename', 'project__project_code']
    raw_id_fields = ['project', 'checklist_item']


