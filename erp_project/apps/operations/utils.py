"""Operations module helpers."""

import re
import uuid
from urllib.parse import quote

from django.db.models import Q

from apps.contracts.models import Contract, ContractType
from apps.hr.models import Employee


def get_hr_employee_queryset():
    """All employees visible in HR (same scope as the employee list)."""
    return (
        Employee.objects.filter(is_active=True)
        .select_related('department', 'designation')
        .order_by('first_name', 'last_name', 'employee_code')
    )


def employee_choice_label(employee):
    return f'{employee.full_name} ({employee.employee_code})'


def get_amc_contract_queryset():
    """Active contracts; prefer those tagged as AMC when types exist."""
    qs = Contract.objects.filter(is_active=True).select_related('customer').prefetch_related(
        'contract_types'
    )
    amc_types = ContractType.objects.filter(
        Q(name__icontains='amc') | Q(slug__icontains='amc'),
        is_active=True,
    )
    if amc_types.exists():
        qs = qs.filter(contract_types__in=amc_types).distinct()
    return qs.order_by('-created_at')


def get_operations_settings():
    from .models import OperationsSettings

    settings_obj, _ = OperationsSettings.objects.get_or_create(pk=1)
    return settings_obj


def ensure_operations_public_token():
    settings_obj = get_operations_settings()
    if not settings_obj.public_schedule_token:
        settings_obj.public_schedule_token = uuid.uuid4()
        settings_obj.save(update_fields=['public_schedule_token'])
    return settings_obj.public_schedule_token


def get_schedule_for_public_token(token):
    from .models import OperationsSettings

    if not token:
        return None
    try:
        settings_obj = OperationsSettings.objects.get(public_schedule_token=token)
    except (OperationsSettings.DoesNotExist, ValueError):
        return None
    return settings_obj


def find_employee_schedule_conflicts(employee_ids, duty_date, exclude_pk=None):
    """
    Return dict employee_id -> existing StaffDutySchedule for active scheduled duties on duty_date.
    """
    from .models import StaffDutySchedule

    if not employee_ids or not duty_date:
        return {}

    qs = StaffDutySchedule.objects.filter(
        is_active=True,
        status='scheduled',
        duty_date=duty_date,
        employee_id__in=employee_ids,
    ).select_related('employee', 'project', 'amc_contract')
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    return {row.employee_id: row for row in qs}


def format_conflict_message(schedule):
    target = schedule.target_label
    return (
        f'{schedule.employee.full_name} is already scheduled on '
        f'{schedule.duty_date:%d %b %Y} for {target}.'
    )


def location_maps_url(location):
    if not location:
        return ''
    location = str(location).strip()
    if location.lower().startswith(('http://', 'https://')):
        return location
    return f'https://www.google.com/maps/search/?api=1&query={quote(location)}'


def phone_tel_href(phone):
    if not phone:
        return ''
    cleaned = re.sub(r'[^\d+]', '', str(phone).strip())
    if not cleaned:
        return ''
    return f'tel:{cleaned}'
