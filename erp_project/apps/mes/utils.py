"""MES helpers — company scope for tenant-filtered queries."""


def get_default_mes_company():
    """Primary legal entity for demo seed and single-company installs."""
    from apps.settings_app.models import Company

    return Company.objects.filter(is_active=True).order_by('pk').first()
