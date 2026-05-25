"""Invalidate HR expiry alert cache when compliance records change."""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.hr.expiry_alerts import invalidate_expiry_alerts_cache
from apps.hr.models import Designation, Employee, LeaveRequest, LeaveType
from apps.hr.models_extended import KSACompliance, UAECompliance


@receiver(post_save, sender=UAECompliance)
def expiry_cache_uae(sender, **kwargs):
    invalidate_expiry_alerts_cache()


@receiver(post_save, sender=KSACompliance)
def expiry_cache_ksa(sender, **kwargs):
    invalidate_expiry_alerts_cache()


@receiver(post_save, sender=LeaveRequest)
def leave_balance_sync(sender, instance, **kwargs):
    from apps.hr.leave_balance_service import sync_leave_balances_for_employee

    sync_leave_balances_for_employee(instance.employee_id)


@receiver(post_save, sender=Employee)
def employee_leave_entitlements_refresh(sender, instance, **kwargs):
    """Recalculate LeaveBalance when joining date / probation-related fields change."""
    from apps.hr.leave_balance_service import sync_leave_balances_for_employee

    if instance.pk:
        sync_leave_balances_for_employee(instance.pk)


@receiver(post_save, sender=Employee)
def employee_sync_sales_crm_role(sender, instance, **kwargs):
    """Sales HR employees get the Sales system role for CRM lead assignment."""
    from apps.crm.utils import sync_sales_crm_role_from_employee

    sync_sales_crm_role_from_employee(instance)


@receiver(pre_save, sender=Employee)
def employee_track_designation_change(sender, instance, **kwargs):
    if instance.pk:
        row = Employee.objects.filter(pk=instance.pk).values_list('designation_id', 'user_id').first()
        instance._designation_before_save = row[0] if row else None
        instance._user_before_save = row[1] if row else None
    else:
        instance._designation_before_save = None
        instance._user_before_save = None


@receiver(post_save, sender=Employee)
def employee_sync_erp_role_from_designation(sender, instance, **kwargs):
    prev_desig = getattr(instance, '_designation_before_save', None)
    prev_user = getattr(instance, '_user_before_save', None)
    if (
        instance.pk
        and prev_desig == instance.designation_id
        and prev_user == instance.user_id
        and prev_desig is not None
    ):
        return
    from apps.hr.designation_utils import sync_erp_role_from_designation

    sync_erp_role_from_designation(instance)


@receiver(post_save, sender=Designation)
def designation_sync_erp_role(sender, instance, **kwargs):
    """New/updated designation → matching ERP role (same name) for permission tuning."""
    from apps.hr.designation_utils import ensure_role_for_designation

    ensure_role_for_designation(instance)


@receiver(post_save, sender=LeaveType)
def leave_type_policy_refresh(sender, instance, **kwargs):
    from apps.hr.leave_balance_service import sync_all_employees_for_leave_type

    sync_all_employees_for_leave_type(instance.pk)
