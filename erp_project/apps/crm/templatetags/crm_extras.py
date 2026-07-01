from django import template

from apps.crm.utils import kanban_stage_inline_class, source_of_lead_inline_class

register = template.Library()


@register.filter
def file_basename(file_field):
    """Last path segment of an uploaded file for display."""
    if not file_field:
        return ''
    name = getattr(file_field, 'name', None) or str(file_field)
    return name.rsplit('/', 1)[-1] if name else ''


@register.filter
def pipeline_stage_class(stage):
    """Colored CSS class for a CRM pipeline stage (or unassigned when empty)."""
    return kanban_stage_inline_class(stage)


@register.filter
def source_of_lead_class(source_code):
    """Colored CSS class for a lead source value (pipeline-style badges)."""
    return source_of_lead_inline_class(source_code)
