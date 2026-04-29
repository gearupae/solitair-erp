"""Template filters for HR compliance badges."""
from django import template

from apps.hr.compliance_utils import expiry_band as band_fn

register = template.Library()


@register.filter
def expiry_band(value):
    return band_fn(value)


@register.filter
def band_badge_class(band):
    if band == 'red':
        return 'bg-danger'
    if band == 'amber':
        return 'bg-warning text-dark'
    if band == 'green':
        return 'bg-success'
    return 'bg-secondary'
