"""Generate PPM inspections and operations drafts from AMC planned visit dates."""
from __future__ import annotations

from datetime import date, time, timedelta

from django.db import transaction
from django.utils.dateparse import parse_date

from apps.operations.models import StaffDutySchedule
from apps.projects.models import Inspection

from .models import ContractPlannedVisit

DEFAULT_DUTY_START = time(9, 0)


def ppm_terms_from_contract(contract) -> str:
    return (contract.terms_and_conditions or '').strip()


def evenly_spaced_visit_dates(start: date, end: date, count: int) -> list[date]:
    """Suggest visit dates spread across the contract period."""
    if count < 1 or not start or not end:
        return []
    total_days = max((end - start).days, 1)
    interval = max(total_days // count, 1)
    dates: list[date] = []
    for index in range(count):
        visit_date = start + timedelta(days=interval * (index + 1))
        if visit_date > end:
            visit_date = end
        dates.append(visit_date)
    return dates


def parse_visit_dates_from_post(post, planned: int, start: date, end: date) -> tuple[list[date], list[str]]:
    """Read ppm_visit_date_N fields from POST and validate count/range."""
    dates: list[date] = []
    errors: list[str] = []
    for visit_num in range(1, planned + 1):
        raw = (post.get(f'ppm_visit_date_{visit_num}') or '').strip()
        if not raw:
            errors.append(f'Visit {visit_num} date is required.')
            continue
        parsed = parse_date(raw)
        if not parsed:
            errors.append(f'Visit {visit_num} has an invalid date.')
            continue
        if parsed < start or parsed > end:
            errors.append(f'Visit {visit_num} must be between the contract start and end dates.')
            continue
        dates.append(parsed)
    if not errors and len(dates) != planned:
        errors.append('Enter a date for each planned visit.')
    return dates, errors


def visit_dates_for_contract(contract) -> list[date]:
    """Load saved visit dates, or derive from linked inspections, or auto-space."""
    saved = list(
        contract.planned_visit_records.filter(is_active=True)
        .order_by('visit_number')
        .values_list('visit_date', flat=True)
    )
    if saved:
        return saved

    from_inspections = list(
        contract.inspections.filter(link_type='amc', is_active=True)
        .order_by('inspection_date', 'pk')
        .values_list('inspection_date', flat=True)
    )
    if from_inspections:
        return from_inspections[: contract.planned_visits or len(from_inspections)]

    planned = contract.planned_visits or 0
    if planned and contract.start_date and contract.end_date:
        return evenly_spaced_visit_dates(contract.start_date, contract.end_date, planned)
    return []


def _location_from_contract(contract) -> str:
    return (contract.service_site or '').strip()[:255]


def _is_editable_draft(schedule: StaffDutySchedule | None) -> bool:
    if not schedule or not schedule.is_active:
        return False
    if schedule.employee_id:
        return False
    return schedule.status in (
        StaffDutySchedule.STATUS_PENDING,
        StaffDutySchedule.STATUS_SCHEDULED,
    )


@transaction.atomic
def sync_contract_visits(contract, visit_dates: list[date] | None = None) -> dict:
    """
    Persist visit dates and sync linked PPM inspections + operations drafts.
    Operations drafts are pending, unassigned rows in /operations/.
    """
    planned = contract.planned_visits or 0
    if planned < 1 or not contract.start_date or not contract.end_date:
        return {'ppm_created': 0, 'ppm_updated': 0, 'ops_created': 0, 'ops_updated': 0}

    if visit_dates is None:
        visit_dates = visit_dates_for_contract(contract)
    if len(visit_dates) != planned:
        visit_dates = evenly_spaced_visit_dates(contract.start_date, contract.end_date, planned)

    ppm_notes = ppm_terms_from_contract(contract)
    location = _location_from_contract(contract)

    existing = {
        pv.visit_number: pv
        for pv in contract.planned_visit_records.filter(is_active=True).select_related(
            'inspection', 'duty_schedule'
        )
    }

    ppm_created = ppm_updated = ops_created = ops_updated = 0
    seen_numbers: set[int] = set()

    for index, visit_date in enumerate(visit_dates, start=1):
        seen_numbers.add(index)
        pv = existing.get(index)
        if pv is None:
            pv = ContractPlannedVisit(contract=contract, visit_number=index, visit_date=visit_date)
            pv.save()
        elif pv.visit_date != visit_date:
            pv.visit_date = visit_date
            pv.save(update_fields=['visit_date', 'updated_at'])

        visit_name = f'PPM Visit {index} — {contract.contract_number}'

        if pv.inspection_id and pv.inspection and pv.inspection.is_active:
            inspection = pv.inspection
            changed = False
            if inspection.inspection_date != visit_date:
                inspection.inspection_date = visit_date
                changed = True
            if inspection.name != visit_name:
                inspection.name = visit_name
                changed = True
            if ppm_notes and inspection.notes != ppm_notes:
                inspection.notes = ppm_notes
                changed = True
            if changed:
                inspection.save()
                ppm_updated += 1
        else:
            inspection = Inspection.objects.create(
                name=visit_name,
                link_type='amc',
                amc_contract=contract,
                inspection_date=visit_date,
                notes=ppm_notes,
            )
            pv.inspection = inspection
            pv.save(update_fields=['inspection', 'updated_at'])
            ppm_created += 1

        if pv.duty_schedule_id and _is_editable_draft(pv.duty_schedule):
            schedule = pv.duty_schedule
            changed = False
            if schedule.duty_date != visit_date:
                schedule.duty_date = visit_date
                changed = True
            if schedule.location != location:
                schedule.location = location
                changed = True
            if ppm_notes and schedule.notes != ppm_notes:
                schedule.notes = ppm_notes
                changed = True
            if schedule.status != StaffDutySchedule.STATUS_PENDING:
                schedule.status = StaffDutySchedule.STATUS_PENDING
                changed = True
            if changed:
                schedule.save()
                ops_updated += 1
        elif not pv.duty_schedule_id or not (pv.duty_schedule and pv.duty_schedule.is_active):
            schedule = StaffDutySchedule.objects.create(
                employee=None,
                duty_date=visit_date,
                start_time=DEFAULT_DUTY_START,
                link_type='amc',
                amc_contract=contract,
                status=StaffDutySchedule.STATUS_PENDING,
                location=location,
                notes=ppm_notes,
            )
            pv.duty_schedule = schedule
            pv.save(update_fields=['duty_schedule', 'updated_at'])
            ops_created += 1

    for visit_number, pv in existing.items():
        if visit_number in seen_numbers:
            continue
        pv.is_active = False
        pv.save(update_fields=['is_active', 'updated_at'])
        if pv.inspection_id and pv.inspection and pv.inspection.is_active:
            pv.inspection.is_active = False
            pv.inspection.save(update_fields=['is_active', 'updated_at'])
        if _is_editable_draft(pv.duty_schedule):
            pv.duty_schedule.is_active = False
            pv.duty_schedule.save(update_fields=['is_active', 'updated_at'])

    return {
        'ppm_created': ppm_created,
        'ppm_updated': ppm_updated,
        'ops_created': ops_created,
        'ops_updated': ops_updated,
    }


def sync_ppm_visits(contract, *, replace_missing_only: bool = True) -> int:
    """Backward-compatible wrapper — returns count of new PPM inspections created."""
    result = sync_contract_visits(contract)
    return result['ppm_created']


def refresh_ppm_visit_terms(contract) -> int:
    """Push current contract terms to existing PPM inspection notes."""
    ppm_notes = ppm_terms_from_contract(contract)
    if not ppm_notes:
        return 0
    return Inspection.objects.filter(
        link_type='amc',
        amc_contract=contract,
        is_active=True,
    ).update(notes=ppm_notes)
