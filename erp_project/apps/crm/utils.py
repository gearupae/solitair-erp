"""CRM helpers."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Q

from apps.core.visibility import (
    filter_customers_for_user,
    user_can_access_customer,
    user_data_scope_restricted,
    user_has_elevated_data_access,
)
from apps.projects.models import Project
from apps.settings_app.models import UserRole

User = get_user_model()

CRM_ELEVATED_ROLE_CODES = frozenset({'super_admin', 'admin', 'manager'})
SALES_ROLE_CODE = 'sales'


def get_crm_project_queryset(user=None):
    """Active projects for CRM customer primary-project dropdowns."""
    from apps.core.visibility import filter_projects_for_user

    qs = Project.objects.filter(is_active=True).order_by('project_code', 'name')
    if user is not None:
        qs = filter_projects_for_user(qs, user)
    return qs


def project_choice_label(project):
    return f'{project.project_code} — {project.name}'


def get_user_role_codes(user):
    if not user or not user.is_authenticated:
        return frozenset()
    if user.is_superuser:
        return frozenset({'superuser'})
    return frozenset(
        UserRole.objects.filter(user=user, is_active=True).values_list('role__code', flat=True)
    )


def user_has_elevated_crm_access(user):
    """Admins, managers, and superusers see all CRM records."""
    return user_has_elevated_data_access(user)


def crm_leads_restricted_to_assignee(user):
    """
    Non-elevated CRM users only see records they created or are assigned to.
    Admins, managers, and superusers see all.
    """
    return user_data_scope_restricted(user, 'crm')


def _sales_employee_base_filter():
    """Active HR employees treated as sales staff for CRM assignment."""
    from apps.hr.models import Employee

    return Employee.objects.filter(is_active=True, status='active').filter(
        Q(department__code__iexact='sales')
        | Q(department__name__iexact='sales')
        | Q(designation__name__iexact='sales')
        | Q(designation__name__iexact='salesman')
        | Q(designation__name__icontains='sales')
        | Q(designation__name__icontains='salesman')
    )


def get_sales_employee_queryset():
    """Active HR employees available for CRM assigned salesman dropdowns."""
    from apps.hr.models import Employee

    return Employee.objects.filter(is_active=True, status='active').select_related(
        'department', 'designation', 'user'
    ).order_by('first_name', 'last_name', 'employee_code')


def get_sales_employee_for_user(user):
    if not user:
        return None
    from apps.hr.models import Employee

    return Employee.objects.filter(user=user, is_active=True).first()


def is_sales_hr_employee(employee):
    if not employee or not employee.pk:
        return False
    return _sales_employee_base_filter().filter(pk=employee.pk).exists()


def ensure_sales_crm_role_for_user(user):
    """Grant Sales system role when employee gets ERP login."""
    if not user or not user.is_active:
        return
    from apps.settings_app.models import Role

    sales_role = Role.objects.filter(code=SALES_ROLE_CODE, is_active=True).first()
    if not sales_role:
        return
    UserRole.objects.get_or_create(
        user=user,
        role=sales_role,
        defaults={'is_active': True},
    )


def sync_sales_crm_role_from_employee(employee):
    """Keep CRM salesman login role in sync when HR saves a sales employee."""
    if not employee or not employee.user_id:
        return
    if is_sales_hr_employee(employee):
        ensure_sales_crm_role_for_user(employee.user)


def salesperson_display_name(employee):
    if not employee:
        return '—'
    return f'{employee.full_name} ({employee.employee_code})'


CRM_KANBAN_UNASSIGNED_THEME = {
    'header_bg': '#f3f4f6',
    'header_color': '#374151',
    'card_bg': '#ffffff',
    'card_border': '#d1d5db',
    'accent': '#6b7280',
    'body_bg': '#f9fafb',
}

CRM_KANBAN_WON_THEME = {
    'header_bg': '#dcfce7',
    'header_color': '#166534',
    'card_bg': '#f0fdf4',
    'card_border': '#86efac',
    'accent': '#16a34a',
    'body_bg': '#ecfdf5',
}

CRM_KANBAN_CUSTOMERS_THEME = {
    'header_bg': '#ede9fe',
    'header_color': '#5b21b6',
    'card_bg': '#faf5ff',
    'card_border': '#c4b5fd',
    'accent': '#7c3aed',
    'body_bg': '#f5f3ff',
}

CRM_KANBAN_STAGE_THEMES = [
    {
        'header_bg': '#dbeafe',
        'header_color': '#1e40af',
        'card_bg': '#eff6ff',
        'card_border': '#93c5fd',
        'accent': '#2563eb',
        'body_bg': '#f0f7ff',
    },
    {
        'header_bg': '#fef3c7',
        'header_color': '#b45309',
        'card_bg': '#fffbeb',
        'card_border': '#fcd34d',
        'accent': '#d97706',
        'body_bg': '#fffdf5',
    },
    {
        'header_bg': '#fce7f3',
        'header_color': '#be185d',
        'card_bg': '#fdf2f8',
        'card_border': '#f9a8d4',
        'accent': '#db2777',
        'body_bg': '#fef6fa',
    },
    {
        'header_bg': '#ccfbf1',
        'header_color': '#0f766e',
        'card_bg': '#f0fdfa',
        'card_border': '#5eead4',
        'accent': '#0d9488',
        'body_bg': '#ecfdf8',
    },
    {
        'header_bg': '#e0e7ff',
        'header_color': '#4338ca',
        'card_bg': '#eef2ff',
        'card_border': '#a5b4fc',
        'accent': '#4f46e5',
        'body_bg': '#f5f7ff',
    },
    {
        'header_bg': '#ffedd5',
        'header_color': '#c2410c',
        'card_bg': '#fff7ed',
        'card_border': '#fdba74',
        'accent': '#ea580c',
        'body_bg': '#fffaf5',
    },
]


def kanban_theme_style(theme) -> str:
    """Inline CSS variables for a kanban column theme."""
    return (
        f"--kb-header-bg:{theme['header_bg']};"
        f"--kb-header-color:{theme['header_color']};"
        f"--kb-card-bg:{theme['card_bg']};"
        f"--kb-card-border:{theme['card_border']};"
        f"--kb-accent:{theme['accent']};"
        f"--kb-body-bg:{theme['body_bg']};"
    )


def filter_customers_for_user(queryset, user):
    """Re-export from core.visibility."""
    from apps.core import visibility

    return visibility.filter_customers_for_user(queryset, user)


def normalize_customer_website(value: str) -> str:
    """Accept gear-up.ae, www.gear-up.ae, or https://gear-up.ae and store as a valid URL."""
    website = (value or '').strip()
    if not website:
        return ''
    if not website.startswith(('http://', 'https://')):
        website = f'https://{website}'
    URLValidator()(website)
    return website


def annotate_latest_estimate_value(queryset):
    """Add latest_estimate_value from the customer's most recent active estimate."""
    from decimal import Decimal

    from django.db.models import DecimalField, OuterRef, Subquery
    from django.db.models.functions import Coalesce

    from apps.sales.models import Estimate

    latest = (
        Estimate.objects.filter(customer=OuterRef('pk'), is_active=True)
        .order_by('-date', '-id')
        .values('total_amount')[:1]
    )
    return queryset.annotate(
        latest_estimate_value=Coalesce(
            Subquery(latest, output_field=DecimalField(max_digits=15, decimal_places=2)),
            Decimal('0.00'),
        )
    )


def user_can_access_customer(user, customer):
    from apps.core import visibility

    return visibility.user_can_access_customer(user, customer)
