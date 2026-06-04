from django import template

register = template.Library()


@register.filter
def file_basename(file_field):
    """Last path segment of an uploaded file for display."""
    if not file_field:
        return ''
    name = getattr(file_field, 'name', None) or str(file_field)
    return name.rsplit('/', 1)[-1] if name else ''
