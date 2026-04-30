"""Fleet document expiry alerts for the dashboard (≤10 days or expired)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.core.utils import PermissionChecker

ADVANCE_ALERT_DAYS = 10


def _severity_labels(days_left: int) -> tuple[str, str]:
    if days_left < 0:
        severity = 'expired'
        ago = abs(days_left)
        label = f'Expired {ago} day ago' if ago == 1 else f'Expired {ago} days ago'
    elif days_left == 0:
        severity = 'due_today'
        label = 'Expires today'
    else:
        severity = 'expiring'
        label = f'{days_left} days left' if days_left != 1 else '1 day left'
    return severity, label


def get_fleet_dashboard_alerts(user, today: date | None = None) -> list[dict[str, Any]]:
    from .models import Vehicle, VehicleOtherDocument

    today = today or date.today()
    horizon = today + timedelta(days=ADVANCE_ALERT_DAYS)
    if not user.is_superuser and not PermissionChecker.has_permission(user, 'fleet', 'view'):
        return []

    rows: list[dict[str, Any]] = []

    vehicles = Vehicle.objects.filter(is_active=True).select_related('driver')
    for v in vehicles:
        label_base = str(v)

        if v.mulkiya_expiry and v.mulkiya_expiry <= horizon:
            dl = (v.mulkiya_expiry - today).days
            sev, lbl = _severity_labels(dl)
            rows.append(
                {
                    'kind': 'mulkiya',
                    'kind_label': 'Mulkiya',
                    'vehicle': v,
                    'expiry_date': v.mulkiya_expiry,
                    'days_left': dl,
                    'severity': sev,
                    'label': lbl,
                    'vehicle_label': label_base,
                }
            )

        if v.insurance_expiry and v.insurance_expiry <= horizon:
            dl = (v.insurance_expiry - today).days
            sev, lbl = _severity_labels(dl)
            rows.append(
                {
                    'kind': 'insurance',
                    'kind_label': 'Insurance',
                    'vehicle': v,
                    'expiry_date': v.insurance_expiry,
                    'days_left': dl,
                    'severity': sev,
                    'label': lbl,
                    'vehicle_label': label_base,
                }
            )

    for doc in (
        VehicleOtherDocument.objects.filter(is_active=True, vehicle__is_active=True, expiry_date__lte=horizon)
        .select_related('vehicle', 'vehicle__driver')
    ):
        dl = (doc.expiry_date - today).days
        sev, lbl = _severity_labels(dl)
        rows.append(
            {
                'kind': 'other',
                'kind_label': doc.document_name,
                'vehicle': doc.vehicle,
                'expiry_date': doc.expiry_date,
                'days_left': dl,
                'severity': sev,
                'label': lbl,
                'vehicle_label': str(doc.vehicle),
            }
        )

    rows.sort(key=lambda r: (r['expiry_date'], r['vehicle_label'], r['kind_label']))
    return rows
