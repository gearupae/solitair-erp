"""Gate pass expiry alerts for the main dashboard (≤10 days or expired)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db.models import Q

ADVANCE_ALERT_DAYS = 10


def pick_display_gatepass(gatepasses_for_member: list, today: date | None = None):
    """Most relevant pass: active window first, else soonest upcoming, else latest expired."""
    today = today or date.today()
    if not gatepasses_for_member:
        return None
    active = [g for g in gatepasses_for_member if g.start_date <= today <= g.expiry_date]
    if active:
        return max(active, key=lambda x: x.expiry_date)
    upcoming = [g for g in gatepasses_for_member if g.start_date > today]
    if upcoming:
        return min(upcoming, key=lambda x: x.start_date)
    return max(gatepasses_for_member, key=lambda x: x.expiry_date)


def get_gatepass_dashboard_alerts(user, today: date | None = None) -> list[dict[str, Any]]:
    from apps.core.utils import PermissionChecker
    from .models import ProjectGatepass

    today = today or date.today()
    horizon = today + timedelta(days=ADVANCE_ALERT_DAYS)
    qs = (
        ProjectGatepass.objects.filter(is_active=True, expiry_date__lte=horizon)
        .select_related('project', 'member')
        .order_by('expiry_date', 'project__project_code', 'member__username')
    )
    if not user.is_superuser and not PermissionChecker.has_permission(user, 'projects', 'view'):
        qs = qs.filter(Q(project__members=user) | Q(project__manager=user))

    rows = []
    for gp in qs:
        days_left = (gp.expiry_date - today).days
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
        rows.append(
            {
                'gatepass': gp,
                'project': gp.project,
                'member': gp.member,
                'start_date': gp.start_date,
                'expiry_date': gp.expiry_date,
                'days_left': days_left,
                'severity': severity,
                'label': label,
            }
        )
    return rows
