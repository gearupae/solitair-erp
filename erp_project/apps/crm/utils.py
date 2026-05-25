"""CRM helpers."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.projects.models import Project
from apps.settings_app.models import UserRole

User = get_user_model()

CRM_ELEVATED_ROLE_CODES = frozenset({'admin', 'manager'})
SALES_ROLE_CODE = 'sales'


def get_crm_project_queryset():
    """Active projects for CRM customer primary-project dropdowns."""
    return Project.objects.filter(is_active=True).order_by('project_code', 'name')


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
    codes = get_user_role_codes(user)
    if 'superuser' in codes:
        return True
    return bool(CRM_ELEVATED_ROLE_CODES & codes)


def crm_leads_restricted_to_assignee(user):
    """
    Sales-role users (without admin/manager) only see leads assigned to them.
    """
    if not user or not user.is_authenticated:
        return False
    if user_has_elevated_crm_access(user):
        return False
    return SALES_ROLE_CODE in get_user_role_codes(user)


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
    """All active sales HR employees for the assign-salesman dropdown."""
    return _sales_employee_base_filter().select_related(
        'department', 'designation', 'user'
    ).order_by('first_name', 'last_name', 'employee_code')


def get_sales_employee_for_user(user):
    if not user:
        return None
    from apps.hr.models import Employee

    emp = _sales_employee_base_filter().filter(user=user).first()
    if emp:
        return emp
    return Employee.objects.filter(user=user, is_active=True, status='active').first()


def is_sales_hr_employee(employee):
    if not employee or not employee.is_active or employee.status != 'active':
        return False
    if employee.department:
        code = (employee.department.code or '').lower()
        name = (employee.department.name or '').lower()
        if code == 'sales' or name == 'sales':
            return True
    if employee.designation:
        desig = (employee.designation.name or '').lower()
        if desig in {'sales', 'salesman'} or 'sales' in desig or 'salesman' in desig:
            return True
    return False


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


def filter_customers_for_user(queryset, user):
    """Restrict queryset for sales reps to their assigned leads only."""
    if crm_leads_restricted_to_assignee(user):
        return queryset.filter(
            customer_type='lead',
            assigned_salesperson__user=user,
        )
    return queryset


def user_can_access_customer(user, customer):
    if not customer:
        return False
    if not crm_leads_restricted_to_assignee(user):
        return True
    sp = customer.assigned_salesperson
    return (
        customer.customer_type == 'lead'
        and sp is not None
        and sp.user_id == user.id
    )
