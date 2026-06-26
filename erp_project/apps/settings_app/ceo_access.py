"""CEO dashboard access — superuser or admin / super_admin role only."""
from __future__ import annotations

CEO_ROLE_CODES = frozenset({'admin', 'super_admin'})


def user_can_access_ceo_dashboard(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser:
        return True
    from apps.settings_app.models import UserRole

    return UserRole.objects.filter(
        user=user,
        is_active=True,
        role__is_active=True,
        role__code__in=CEO_ROLE_CODES,
    ).exists()
