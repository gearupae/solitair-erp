"""Invalidate HR expiry alert cache when compliance records change."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.hr.expiry_alerts import invalidate_expiry_alerts_cache
from apps.hr.models import Employee, LeaveRequest, LeaveType
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


@receiver(post_save, sender=LeaveType)
def leave_type_policy_refresh(sender, instance, **kwargs):
    from apps.hr.leave_balance_service import sync_all_employees_for_leave_type

    sync_all_employees_for_leave_type(instance.pk)
