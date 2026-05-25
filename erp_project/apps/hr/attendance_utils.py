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


def open_attendance_session(employee: Employee, d: date) -> AttendanceRecord | None:
    """Latest open punch (clocked in, not yet out) for this employee on this date."""
    return (
        AttendanceRecord.objects.filter(
            employee=employee,
            date=d,
            is_active=True,
            check_in__isnull=False,
            check_out__isnull=True,
        )
        .order_by('-check_in', '-pk')
        .first()
    )


def _session_datetimes(d: date, check_in, check_out):
    """Return (start, end) datetimes for a closed session."""
    if not check_in or not check_out:
        return None
    start = datetime.combine(d, check_in)
    end = datetime.combine(d, check_out)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def attendance_intervals_overlap(d: date, in_a, out_a, in_b, out_b) -> bool:
    """True when two closed punch ranges on the same date overlap in time."""
    range_a = _session_datetimes(d, in_a, out_a)
    range_b = _session_datetimes(d, in_b, out_b)
    if not range_a or not range_b:
        return False
    a0, a1 = range_a
    b0, b1 = range_b
    return a0 < b1 and b0 < a1


def _format_session_range(check_in, check_out) -> str:
    return f'{check_in.strftime("%H:%M")}–{check_out.strftime("%H:%M")}'


def attendance_overlap_message(
    employee: Employee,
    d: date,
    check_in,
    check_out=None,
    *,
    exclude_pk=None,
    extra_sessions=None,
) -> str | None:
    """
    Return an error message if this punch overlaps another session the same day.
    extra_sessions: optional list of (check_in, check_out) tuples from the same import batch.
    """
    if not check_in:
        return None

    def _conflicts_with(ci, co):
        if not ci or not co:
            return False
        if check_out:
            return attendance_intervals_overlap(d, check_in, check_out, ci, co)
        start, end = _session_datetimes(d, ci, co)
        if not start:
            return False
        t = datetime.combine(d, check_in)
        return start <= t < end

    qs = AttendanceRecord.objects.filter(
        employee=employee,
        date=d,
        is_active=True,
        check_in__isnull=False,
        check_out__isnull=False,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    for rec in qs:
        if _conflicts_with(rec.check_in, rec.check_out):
            return (
                f'This time overlaps an existing session '
                f'({_format_session_range(rec.check_in, rec.check_out)}).'
            )

    for ci, co in extra_sessions or []:
        if _conflicts_with(ci, co):
            return (
                f'This time overlaps another row in the file '
                f'({_format_session_range(ci, co)}).'
            )

    return None


def hours_between_punches(d: date, check_in, check_out) -> Decimal | None:
    """Duration in decimal hours between two punches on date d (handles overnight out)."""
    if not check_in or not check_out:
        return None
    dt_start = datetime.combine(d, check_in)
    dt_end = datetime.combine(d, check_out)
    if dt_end < dt_start:
        dt_end += timedelta(days=1)
    delta = dt_end - dt_start
    return Decimal(str(round(delta.total_seconds() / 3600.0, 2)))


def record_working_hours(record: AttendanceRecord) -> Decimal:
    """Effective hours for costing — uses stored WH or derives from punches."""
    if record.working_hours is not None:
        return record.working_hours
    hrs = hours_between_punches(record.date, record.check_in, record.check_out)
    return hrs if hrs is not None else Decimal('0.00')


def apply_auto_calculations_to_record(record: AttendanceRecord) -> None:
    """Mutates record before save: weekend/holiday flags, hours, late, overtime."""
    settings = get_attendance_settings()
    d = record.date
    emp = record.employee

    if is_uae_weekend(d):
        record.status = 'weekend'
        record.working_hours = hours_between_punches(d, record.check_in, record.check_out)
        record.late_minutes = 0
        record.overtime_hours = Decimal('0.00')
        record.overtime_type = 'normal'
        return

    hol = holiday_on_date_for_employee(d, emp)
    if hol:
        record.status = 'holiday'
        record.late_minutes = 0
        if record.check_in and record.check_out:
            hrs = hours_between_punches(d, record.check_in, record.check_out) or Decimal('0.00')
            record.working_hours = hrs
            record.overtime_hours = hrs.quantize(Decimal('0.01'))
            record.overtime_type = 'holiday'
        else:
            record.working_hours = None
            record.overtime_hours = Decimal('0.00')
            record.overtime_type = 'normal'
        if hol.name and 'Public Holiday' not in (record.notes or ''):
            prefix = 'Public Holiday: ' + hol.name
            if record.notes:
                record.notes = prefix + '\n' + record.notes
            else:
                record.notes = prefix
        return

    status_lower = (record.status or '').lower()
    if record.check_in and record.check_out:
        hrs = hours_between_punches(d, record.check_in, record.check_out) or Decimal('0.00')
        record.working_hours = hrs
        thr = settings.overtime_threshold_hours or Decimal('9')
        record.overtime_hours = max(Decimal('0'), hrs - thr).quantize(Decimal('0.01'))
    else:
        record.working_hours = None
        record.overtime_hours = Decimal('0.00')

    if record.overtime_hours and record.overtime_hours > 0:
        co = record.check_out
        if co and (co >= time(22, 0) or co < time(4, 0)):
            record.overtime_type = 'night'
        else:
            record.overtime_type = 'normal'
    else:
        record.overtime_type = 'normal'

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
        ta=Count('pk', filter=Q(status='absent', check_in__isnull=True)),
        tl=Count('pk', filter=Q(status='late')),
        th=Count('pk', filter=Q(status='half_day')),
        thol=Count('pk', filter=Q(status='holiday')),
        tot_ot=Sum('overtime_hours'),
        tot_lm=Sum('late_minutes'),
        tot_wh=Sum('working_hours'),
    )
    tp = qs.filter(check_in__isnull=False).values('date').distinct().count()
    ta = qs.filter(status='absent', check_in__isnull=True).values('date').distinct().count()
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
        if AttendanceRecord.objects.filter(employee=emp, date=target).exists():
            continue
        AttendanceRecord.objects.create(
            employee=emp,
            date=target,
            status='absent',
            source='manual',
            notes='Auto-marked absent',
        )
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
        if AttendanceRecord.objects.filter(employee=emp, date=target).exists():
            continue
        AttendanceRecord.objects.create(
            employee=emp,
            date=target,
            status='holiday',
            source='manual',
            notes=f'Public Holiday: {hol.name}',
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

    records_by_emp: dict[int, list] = {}
    for r in AttendanceRecord.objects.filter(
        is_active=True, date=today, employee_id__in=active_ids
    ).select_related('employee').order_by('employee_id', '-pk'):
        records_by_emp.setdefault(r.employee_id, []).append(r)

    present = absent = late = not_marked = 0
    late_emps = []
    unmarked = []

    for emp in employees:
        sessions = records_by_emp.get(emp.pk, [])
        if not sessions:
            if is_uae_weekend(today):
                continue
            if holiday_on_date_for_employee(today, emp):
                continue
            not_marked += 1
            unmarked.append({'id': emp.pk, 'name': emp.full_name, 'code': emp.employee_code})
            continue
        if any(s.check_in for s in sessions):
            present += 1
            late_sess = next((s for s in sessions if s.status == 'late' and s.late_minutes), None)
            if late_sess:
                late += 1
                late_emps.append({'name': emp.full_name, 'late_minutes': late_sess.late_minutes})
            continue
        st = sessions[0].status
        if st == 'absent':
            absent += 1
        elif st == 'late':
            late += 1
            late_emps.append({'name': emp.full_name, 'late_minutes': sessions[0].late_minutes})
        elif st in ('weekend', 'holiday'):
            pass
        elif st == 'half_day':
            present += 1
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
