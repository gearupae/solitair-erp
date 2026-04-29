"""Attendance auto-calculations, UAE Fri–Sat weekend, holidays, monthly aggregates."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum

from apps.hr.models import Employee
from apps.hr.models_extended import AttendanceRecord, AttendanceSettings, AttendanceSummary, Holiday


def is_uae_weekend(d: date) -> bool:
    """UAE/KSA weekend: Friday & Saturday (weekday 4,5 Mon=0)."""
    return d.weekday() in (4, 5)


def is_uae_working_day(d: date) -> bool:
    return not is_uae_weekend(d)


def working_days_in_calendar_month(year: int, month: int) -> int:
    _, last = monthrange(year, month)
    n = 0
    for day in range(1, last + 1):
        if is_uae_working_day(date(year, month, day)):
            n += 1
    return n


def get_attendance_settings() -> AttendanceSettings:
    obj, _ = AttendanceSettings.objects.get_or_create(pk=1)
    return obj


def holiday_on_date_for_employee(d: date, emp: Employee) -> Holiday | None:
    loc = (emp.location or '').lower()
    qs = Holiday.objects.filter(is_active=True, date=d)
    if loc in ('uae', 'ksa'):
        return qs.filter(Q(location='both') | Q(location=loc)).first()
    return qs.filter(location='both').first()


def apply_auto_calculations_to_record(record: AttendanceRecord) -> None:
    """Mutates record before save: weekend/holiday flags, hours, late, overtime."""
    settings = get_attendance_settings()
    d = record.date
    emp = record.employee

    if is_uae_weekend(d):
        record.status = 'weekend'
        record.working_hours = None
        record.late_minutes = 0
        record.overtime_hours = Decimal('0.00')
        return

    hol = holiday_on_date_for_employee(d, emp)
    if hol:
        record.status = 'holiday'
        record.working_hours = None
        record.late_minutes = 0
        record.overtime_hours = Decimal('0.00')
        if hol.name and 'Public Holiday' not in (record.notes or ''):
            prefix = 'Public Holiday: ' + hol.name
            if record.notes:
                record.notes = prefix + '\n' + record.notes
            else:
                record.notes = prefix
        return

    status_lower = (record.status or '').lower()
    if record.check_in and record.check_out:
        dt_start = datetime.combine(d, record.check_in)
        dt_end = datetime.combine(d, record.check_out)
        if dt_end < dt_start:
            dt_end += timedelta(days=1)
        delta = dt_end - dt_start
        hrs = Decimal(str(round(delta.total_seconds() / 3600.0, 2)))
        record.working_hours = hrs
        thr = settings.overtime_threshold_hours or Decimal('9')
        record.overtime_hours = max(Decimal('0'), hrs - thr).quantize(Decimal('0.01'))
    else:
        record.working_hours = None
        record.overtime_hours = Decimal('0.00')

    record.late_minutes = 0
    if status_lower not in ('absent', 'weekend', 'holiday') and record.check_in:
        shift_start = settings.shift_start or time(9, 0)
        ci = datetime.combine(d, record.check_in)
        ss = datetime.combine(d, shift_start)
        if ci > ss:
            record.late_minutes = int((ci - ss).total_seconds() // 60)


def working_days_in_month(year: int, month: int) -> int:
    """Deprecated alias — calendar working days."""
    return working_days_in_calendar_month(year, month)


def recalculate_summary_for_employee_month(
    employee: Employee,
    year: int,
    month: int,
    *,
    skip_if_finalized: bool = False,
) -> AttendanceSummary | None:
    month_first = date(year, month, 1)
    _, last = monthrange(year, month)
    last_day = date(year, month, last)

    if skip_if_finalized:
        existing = AttendanceSummary.objects.filter(employee=employee, month=month_first).first()
        if existing and existing.is_finalized:
            return existing

    wd_calendar = working_days_in_calendar_month(year, month)

    qs = AttendanceRecord.objects.filter(
        employee=employee,
        date__gte=month_first,
        date__lte=last_day,
        is_active=True,
    )
    agg = qs.aggregate(
        tp=Count('pk', filter=Q(status='present')),
        ta=Count('pk', filter=Q(status='absent')),
        tl=Count('pk', filter=Q(status='late')),
        th=Count('pk', filter=Q(status='half_day')),
        thol=Count('pk', filter=Q(status='holiday')),
        tot_ot=Sum('overtime_hours'),
        tot_lm=Sum('late_minutes'),
        tot_wh=Sum('working_hours'),
    )
    tp = agg['tp'] or 0
    ta = agg['ta'] or 0
    tl = agg['tl'] or 0
    th = agg['th'] or 0
    thol = agg['thol'] or 0
    tot_ot = agg['tot_ot'] or Decimal('0')
    tot_lm = agg['tot_lm'] or 0
    tot_wh = agg['tot_wh'] or Decimal('0')

    absent_units = Decimal(str(ta)) + Decimal(str(th)) * Decimal('0.5')

    summ, _ = AttendanceSummary.objects.update_or_create(
        employee=employee,
        month=month_first,
        defaults={
            'total_working_days': wd_calendar,
            'total_present': tp,
            'total_absent': ta,
            'total_late': tl,
            'total_half_day': th,
            'total_holidays': thol,
            'total_overtime_hours': (tot_ot or Decimal('0')).quantize(Decimal('0.01')),
            'total_late_minutes': int(tot_lm),
            'total_working_hours': (tot_wh or Decimal('0')).quantize(Decimal('0.01')),
            'absent_deduction_days': absent_units.quantize(Decimal('0.01')),
        },
    )
    return summ


def auto_mark_absent_for_date(target: date) -> int:
    """Create absent records for active employees missing a row on a working day."""
    settings = get_attendance_settings()
    if not settings.auto_mark_absent:
        return 0
    if not is_uae_working_day(target):
        return 0
    created = 0
    emps = Employee.objects.filter(is_active=True, status='active')
    for emp in emps:
        if holiday_on_date_for_employee(target, emp):
            continue
        obj, was_created = AttendanceRecord.objects.get_or_create(
            employee=emp,
            date=target,
            defaults={
                'status': 'absent',
                'source': 'manual',
                'notes': 'Auto-marked absent',
            },
        )
        if was_created:
            created += 1
            recalculate_summary_for_employee_month(emp, target.year, target.month)
    return created


def auto_mark_holidays_for_date(target: date) -> int:
    """Ensure holiday rows exist for employees whose location matches today's holidays."""
    holidays = Holiday.objects.filter(is_active=True, date=target)
    if not holidays.exists():
        return 0
    touched = 0
    emps = Employee.objects.filter(is_active=True, status='active')
    for emp in emps:
        hol = holiday_on_date_for_employee(target, emp)
        if not hol:
            continue
        obj, created = AttendanceRecord.objects.update_or_create(
            employee=emp,
            date=target,
            defaults={
                'status': 'holiday',
                'source': 'manual',
                'notes': f'Public Holiday: {hol.name}',
            },
        )
        touched += 1
        recalculate_summary_for_employee_month(emp, target.year, target.month)
    return touched


def attendance_snapshot_today() -> dict:
    """Counts across active employees for dashboard / mark page."""
    today = date.today()
    employees = Employee.objects.filter(is_active=True, status='active')
    active_ids = list(employees.values_list('pk', flat=True))
    total = len(active_ids)
    if total == 0:
        return {
            'total_active': 0,
            'present': 0,
            'absent': 0,
            'late': 0,
            'not_marked': 0,
            'late_employees': [],
            'unmarked_employees': [],
        }

    records = {
        r.employee_id: r
        for r in AttendanceRecord.objects.filter(is_active=True, date=today, employee_id__in=active_ids).select_related(
            'employee'
        )
    }

    present = absent = late = not_marked = 0
    late_emps = []
    unmarked = []

    for emp in employees:
        r = records.get(emp.pk)
        if not r:
            if is_uae_weekend(today):
                continue
            if holiday_on_date_for_employee(today, emp):
                continue
            not_marked += 1
            unmarked.append({'id': emp.pk, 'name': emp.full_name, 'code': emp.employee_code})
            continue
        st = r.status
        if st == 'present':
            present += 1
        elif st == 'absent':
            absent += 1
        elif st == 'late':
            late += 1
            late_emps.append({'name': r.employee.full_name, 'late_minutes': r.late_minutes})
        elif st == 'half_day':
            present += 1
        elif st in ('weekend', 'holiday'):
            pass
        else:
            present += 1

    return {
        'total_active': total,
        'present': present,
        'absent': absent,
        'late': late,
        'not_marked': not_marked,
        'late_employees': late_emps[:30],
        'unmarked_employees': unmarked[:50],
    }


def mark_all_present_today() -> int:
    """Create Present rows for active employees with no record today; skip weekend/holidays."""
    today = date.today()
    if not is_uae_working_day(today):
        return 0
    n = 0
    for emp in Employee.objects.filter(is_active=True, status='active'):
        if holiday_on_date_for_employee(today, emp):
            continue
        if AttendanceRecord.objects.filter(employee=emp, date=today).exists():
            continue
        AttendanceRecord.objects.create(
            employee=emp,
            date=today,
            status='present',
            source='manual',
            notes='Marked all present',
        )
        n += 1
        recalculate_summary_for_employee_month(emp, today.year, today.month)
    return n


def month_absent_rate_pct(year: int, month: int) -> Decimal:
    mf = date(year, month, 1)
    summaries = AttendanceSummary.objects.filter(month=mf, is_active=True)
    agg = summaries.aggregate(tp=Sum('total_present'), ta=Sum('total_absent'))
    tp = agg['tp'] or 0
    ta = agg['ta'] or 0
    denom = tp + ta
    if denom == 0:
        return Decimal('0')
    return (Decimal(str(ta)) * Decimal('100') / Decimal(str(denom))).quantize(Decimal('0.01'))


def company_overtime_month(year: int, month: int) -> Decimal:
    mf = date(year, month, 1)
    _, last = monthrange(year, month)
    ld = date(year, month, last)
    s = (
        AttendanceRecord.objects.filter(date__gte=mf, date__lte=ld, is_active=True).aggregate(
            t=Sum('overtime_hours')
        )['t']
        or Decimal('0')
    )
    return s.quantize(Decimal('0.01'))
