from django import template

from apps.projects.forms import project_staff_choice_label

register = template.Library()


@register.filter
def staff_label(user):
    if not user:
        return ''
    return project_staff_choice_label(user)
