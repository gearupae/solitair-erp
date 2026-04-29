"""
Location-aware document expiry alerts for HR dashboard and scheduled emails.
Cached for 1 hour; invalidated via signals on UAE/KSA compliance saves.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from django.core.cache import cache

CACHE_KEY = 'hr:document_expiry_alerts:v1'
CACHE_TIMEOUT = 3600  # 1 hour


def invalidate_expiry_alerts_cache() -> None:
    cache.delete(CACHE_KEY)


def _classify(days_remaining: int, threshold: int) -> str:
    """
    GREEN: > threshold days away (no alert — excluded from dashboard list).
    AMBER: within threshold but > 7 days (or expired band below).
    RED: <= 7 days and not expired.
    EXPIRED: past date.
    """
    if days_remaining < 0:
        return 'expired'
    if days_remaining <= 7:
        return 'red'
    if days_remaining <= threshold:
        return 'amber'
    return 'green'


def _sort_key(row: dict[str, Any]) -> tuple:
    st = row['status']
    order = {'expired': 0, 'red': 1, 'amber': 2, 'green': 3}
    dr = row['days_remaining']
    # Most critical first: expired (most negative dr first), then red (lowest days), etc.
    return (order.get(st, 9), dr)


def _build_raw_alerts() -> list[dict[str, Any]]:
    """Scan all active UAE/KSA employees and yield alert rows (non-green only)."""
    from apps.hr.models import Employee

    today = date.today()
    rows: list[dict[str, Any]] = []

    qs = (
        Employee.objects.filter(is_active=True, location__in=['uae', 'ksa'])
        .select_related('company', 'department', 'uae_compliance', 'ksa_compliance')
        .order_by('first_name', 'last_name')
    )

    for emp in qs:
        loc = emp.location
        uc = getattr(emp, 'uae_compliance', None)
        kc = getattr(emp, 'ksa_compliance', None)

        # (expiry_date or None, human_label, threshold_days, internal_key)
        to_check: list[tuple[Any, str, int, str]] = []

        if loc == 'uae':
            to_check.append((emp.visa_expiry, 'Visa', 30, 'visa_expiry'))
            if uc:
                to_check.extend(
                    [
                        (uc.emirates_id_expiry, 'Emirates ID', 30, 'emirates_id_expiry'),
                        (uc.labour_card_expiry, 'Labour Card', 30, 'labour_card_expiry'),
                        (uc.medical_insurance_expiry, 'Medical Insurance', 30, 'medical_insurance_expiry'),
                        (uc.iloe_insurance_expiry, 'ILOE Insurance', 30, 'iloe_insurance_expiry'),
                        (uc.passport_expiry, 'Passport', 60, 'passport_expiry'),
                        (uc.unified_number_expiry, 'Unified ID (UID)', 30, 'unified_number_expiry'),
                    ]
                )
        elif loc == 'ksa' and kc:
            to_check.extend(
                [
                    (kc.iqama_expiry, 'Iqama (Residency)', 30, 'iqama_expiry'),
                    (kc.work_permit_expiry, 'Work Permit', 30, 'work_permit_expiry'),
                    (kc.medical_insurance_expiry, 'Medical Insurance', 30, 'medical_insurance_expiry'),
                    (kc.passport_expiry, 'Passport', 60, 'passport_expiry'),
                    (kc.muqeem_expiry, 'Muqeem Status', 30, 'muqeem_expiry'),
                ]
            )

        for exp_date, label, threshold, key in to_check:
            if not exp_date:
                continue
            dr = (exp_date - today).days
            status = _classify(dr, threshold)
            if status == 'green':
                continue
            rows.append(
                {
                    'employee_id': emp.pk,
                    'employee_name': emp.full_name,
                    'employee_code': emp.employee_code,
                    'company_id': emp.company_id,
                    'company_name': emp.company.name if emp.company_id else '—',
                    'department_id': emp.department_id,
                    'department_name': emp.department.name if emp.department_id else '—',
                    'location': loc,
                    'location_display': emp.get_location_display() if hasattr(emp, 'get_location_display') else loc.upper(),
                    'document_type': label,
                    'document_key': key,
                    'expiry_date': exp_date,
                    'days_remaining': dr,
                    'status': status,
                    'threshold_days': threshold,
                }
            )

    rows.sort(key=_sort_key)
    return rows


def get_expiry_alerts(
    *,
    company_id: int | None = None,
    location: str | None = None,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Return cached alert rows (non-green only), optionally filtered.
    """
    data = cache.get(CACHE_KEY)
    if data is None:
        data = _build_raw_alerts()
        cache.set(CACHE_KEY, data, CACHE_TIMEOUT)

    out = []
    for row in data:
        if company_id is not None and row['company_id'] != company_id:
            continue
        if location and row['location'] != location:
            continue
        if department_id is not None and row['department_id'] != department_id:
            continue
        out.append(row)
    return sorted(out, key=_sort_key)


def summarize_alerts(rows: list[dict[str, Any]]) -> dict[str, int]:
    expired = sum(1 for r in rows if r['status'] == 'expired')
    critical = sum(1 for r in rows if r['status'] == 'red')
    expiring_soon = sum(1 for r in rows if r['status'] == 'amber')
    affected = len({r['employee_id'] for r in rows})
    return {
        'expired': expired,
        'critical': critical,
        'expiring_soon': expiring_soon,
        'employees_affected': affected,
        'total_documents': len(rows),
    }


def filter_by_tab(rows: list[dict[str, Any]], tab: str) -> list[dict[str, Any]]:
    tab = (tab or 'all').lower()
    if tab == 'expired':
        return [r for r in rows if r['status'] == 'expired']
    if tab == 'critical':
        return [r for r in rows if r['status'] == 'red']
    if tab in ('expiring', 'expiring_soon', 'soon'):
        return [r for r in rows if r['status'] == 'amber']
    return list(rows)


def build_daily_email_body(rows: list[dict[str, Any]]) -> str:
    expired = [r for r in rows if r['status'] == 'expired']
    critical = [r for r in rows if r['status'] == 'red']
    soon = [r for r in rows if r['status'] == 'amber']

    def lines(section_rows):
        out = []
        for r in section_rows:
            ed = r['expiry_date'].strftime('%Y-%m-%d')
            dr = r['days_remaining']
            if dr < 0:
                tail = f'expired {abs(dr)} day(s) ago ({ed})'
            elif dr == 0:
                tail = f'due today ({ed})'
            else:
                tail = f'expiry {ed} ({dr} days remaining)'
            out.append(f"  - {r['employee_name']} ({r['employee_code']}) — {r['document_type']} — {tail}")
        return '\n'.join(out) if out else '  (none)'

    today_s = date.today().strftime('%Y-%m-%d')
    body = f'Daily Document Expiry Report — {today_s}\n\n'
    body += '1. EXPIRED (immediate action required)\n'
    body += lines(expired) + '\n\n'
    body += '2. CRITICAL — expiring within 7 days\n'
    body += lines(critical) + '\n\n'
    body += '3. EXPIRING SOON — within document threshold (30 / 60 days)\n'
    body += lines(soon) + '\n'
    return body


def recipient_emails() -> list[str]:
    """HR notification email + ADMINS."""
    from django.conf import settings

    from apps.hr import hr_notifications

    raw = list(hr_notifications.hr_recipient_list())
    for _name, addr in getattr(settings, 'ADMINS', ()) or ():
        if addr and addr.strip():
            raw.append(addr.strip())
    # Dedupe preserving order
    seen = set()
    out = []
    for e in raw:
        el = e.lower()
        if el not in seen:
            seen.add(el)
            out.append(e)
    return out
