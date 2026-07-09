"""Vendor bill approval routing from Settings → Approval Configuration."""
from __future__ import annotations

from apps.settings_app.models import ApprovalConfiguration


def vendor_bill_approval_enabled() -> bool:
    return ApprovalConfiguration.objects.filter(module='vendor_bill', is_active=True).exists()


def get_configured_vendor_bill_approver(bill):
    """Configured approver for this bill amount — no superuser fallback."""
    config = ApprovalConfiguration.objects.filter(module='vendor_bill', is_active=True).first()
    if not config:
        return None
    amount = bill.total_amount or 0
    if config.approval_type == 'single':
        return config.default_approver
    level = (
        config.levels.filter(is_active=True)
        .order_by('amount_threshold')
        .filter(amount_threshold__gte=amount)
        .first()
    )
    if not level:
        level = config.levels.filter(is_active=True).order_by('-amount_threshold').first()
    return (level.approver if level else None) or config.default_approver


def user_can_act_on_vendor_bill(user, bill) -> bool:
    """True when user may approve, reject, or return this pending vendor bill."""
    if not user or not user.is_authenticated:
        return False
    if bill.status != 'pending_approval':
        return False
    approver = get_configured_vendor_bill_approver(bill)
    if approver is not None:
        return approver.pk == user.pk
    return user.is_superuser


def bill_status_allows_edit(bill) -> bool:
    return bill.status in ('draft', 'returned')


def bill_status_allows_post(bill) -> bool:
    if bill.total_amount <= 0:
        return False
    if vendor_bill_approval_enabled():
        return bill.status == 'approved'
    return bill.status == 'draft'
