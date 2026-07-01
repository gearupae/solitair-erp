"""Purchase module dashboard — pending approvals, open POs, bills due, alerts."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import PermissionChecker
from apps.purchase.models import (
    ExpenseClaim,
    PurchaseOrder,
    PurchaseRequest,
    VendorBill,
)
from apps.purchase.models_grn import GoodsReceiptNote
from apps.purchase.models_rfq import RFQ
from apps.purchase.pr_approval_rules import user_can_act_on_purchase_request

PREVIEW_LIMIT = 8
OPEN_PO_STATUSES = ('draft', 'sent', 'confirmed', 'partial_received')
UNPAID_BILL_STATUSES = ('draft', 'posted', 'pending', 'partial', 'overdue')
PURCHASE_ALERT_MODULES = frozenset({'purchase_order', 'purchase_request'})


def _unpaid_bills_qs():
    return VendorBill.objects.filter(
        is_active=True,
        status__in=UNPAID_BILL_STATUSES,
    ).filter(total_amount__gt=F('paid_amount'))


def build_purchase_dashboard_context(user) -> dict:
    today = timezone.localdate()
    due_soon_end = today + timedelta(days=7)

    pr_qs = PurchaseRequest.objects.filter(is_active=True)
    from apps.core.visibility import filter_purchase_requests_for_user

    pr_qs = filter_purchase_requests_for_user(pr_qs, user)

    po_qs = PurchaseOrder.objects.filter(is_active=True)
    from apps.core.visibility import filter_purchase_orders_for_user

    po_qs = filter_purchase_orders_for_user(po_qs, user)

    bill_qs = _unpaid_bills_qs().select_related('vendor', 'project')
    open_po_qs = po_qs.exclude(status__in=('received', 'cancelled'))
    pending_pr_qs = pr_qs.filter(status='pending').select_related('requested_by')
    draft_pr_qs = pr_qs.filter(status='draft')
    returned_pr_qs = pr_qs.filter(status='returned')

    my_approval_prs = [
        pr for pr in pending_pr_qs[:50]
        if user_can_act_on_purchase_request(user, pr)
    ]

    overdue_bills_qs = bill_qs.filter(due_date__lt=today).order_by('due_date')
    due_soon_bills_qs = bill_qs.filter(
        due_date__gte=today,
        due_date__lte=due_soon_end,
    ).order_by('due_date')
    draft_bills_qs = VendorBill.objects.filter(is_active=True, status='draft').select_related('vendor')

    po_awaiting_receipt = po_qs.filter(
        status__in=('confirmed', 'partial_received', 'sent'),
        expected_delivery_date__lt=today,
    ).select_related('vendor')

    expense_submitted = ExpenseClaim.objects.filter(is_active=True, status='submitted')
    expense_approved_unpaid = ExpenseClaim.objects.filter(is_active=True, status='approved')

    open_rfqs = RFQ.objects.filter(
        is_active=True,
        status__in=(RFQ.STATUS_DRAFT, RFQ.STATUS_SENT, RFQ.STATUS_QUOTES_RECEIVED),
    )

    draft_grns = GoodsReceiptNote.objects.filter(
        is_active=True,
        status=GoodsReceiptNote.STATUS_DRAFT,
    )

    overdue_total = overdue_bills_qs.aggregate(
        t=Sum(F('total_amount') - F('paid_amount')),
    )['t'] or Decimal('0.00')
    due_soon_total = due_soon_bills_qs.aggregate(
        t=Sum(F('total_amount') - F('paid_amount')),
    )['t'] or Decimal('0.00')

    kpis = [
        {
            'key': 'pr_pending',
            'label': 'PRs awaiting approval',
            'value': pending_pr_qs.count(),
            'icon': 'fa-clipboard-check',
            'color': 'warning',
            'link': reverse('purchase:pr_list') + '?status=pending',
            'hint': 'Purchase requests submitted and pending sign-off',
        },
        {
            'key': 'my_approvals',
            'label': 'Awaiting your approval',
            'value': len(my_approval_prs),
            'icon': 'fa-user-check',
            'color': 'danger' if my_approval_prs else 'secondary',
            'link': reverse('purchase:pr_list') + '?status=pending',
            'hint': 'PRs assigned to you in approval configuration',
        },
        {
            'key': 'open_pos',
            'label': 'Open purchase orders',
            'value': open_po_qs.count(),
            'icon': 'fa-file-invoice',
            'color': 'primary',
            'link': reverse('purchase:po_list'),
            'hint': 'Draft, sent, confirmed, or partially received',
        },
        {
            'key': 'po_overdue',
            'label': 'POs past delivery date',
            'value': po_awaiting_receipt.count(),
            'icon': 'fa-truck-loading',
            'color': 'danger' if po_awaiting_receipt.exists() else 'secondary',
            'link': reverse('purchase:po_list'),
            'hint': 'Expected delivery date has passed',
        },
        {
            'key': 'bills_overdue',
            'label': 'Vendor bills overdue',
            'value': overdue_bills_qs.count(),
            'icon': 'fa-exclamation-circle',
            'color': 'danger' if overdue_bills_qs.exists() else 'secondary',
            'link': reverse('purchase:bill_list') + '?status=overdue',
            'hint': f'AED {overdue_total:,.2f} outstanding',
        },
        {
            'key': 'bills_due_soon',
            'label': 'Bills due (7 days)',
            'value': due_soon_bills_qs.count(),
            'icon': 'fa-calendar-alt',
            'color': 'info',
            'link': reverse('purchase:bill_list'),
            'hint': f'AED {due_soon_total:,.2f} due soon',
        },
        {
            'key': 'draft_bills',
            'label': 'Draft vendor bills',
            'value': draft_bills_qs.count(),
            'icon': 'fa-file-alt',
            'color': 'secondary',
            'link': reverse('purchase:bill_list') + '?status=draft',
            'hint': 'Not yet posted to accounting',
        },
        {
            'key': 'expense_pending',
            'label': 'Expense claims pending',
            'value': expense_submitted.count(),
            'icon': 'fa-receipt',
            'color': 'warning',
            'link': reverse('purchase:expenseclaim_list') + '?status=submitted',
            'hint': 'Submitted, awaiting approval',
        },
    ]

    secondary_stats = [
        {'label': 'Draft PRs', 'value': draft_pr_qs.count(), 'link': reverse('purchase:pr_list') + '?status=draft'},
        {'label': 'PRs returned', 'value': returned_pr_qs.count(), 'link': reverse('purchase:pr_list') + '?status=returned'},
        {'label': 'Approved claims to pay', 'value': expense_approved_unpaid.count(), 'link': reverse('purchase:expenseclaim_list') + '?status=approved'},
        {'label': 'Open RFQs', 'value': open_rfqs.count(), 'link': reverse('purchase:rfq_list')},
        {'label': 'Draft GRNs', 'value': draft_grns.count(), 'link': reverse('purchase:grn_list')},
    ]

    alerts = _purchase_alerts(user)

    return {
        'today': today,
        'kpis': kpis,
        'secondary_stats': secondary_stats,
        'pending_prs': list(pending_pr_qs.order_by('-updated_at')[:PREVIEW_LIMIT]),
        'my_approval_prs': my_approval_prs[:PREVIEW_LIMIT],
        'open_pos': list(
            open_po_qs.filter(status__in=OPEN_PO_STATUSES)
            .select_related('vendor')
            .order_by(F('expected_delivery_date').asc(nulls_last=True), '-created_at')[:PREVIEW_LIMIT],
        ),
        'overdue_bills': list(overdue_bills_qs[:PREVIEW_LIMIT]),
        'due_soon_bills': list(due_soon_bills_qs[:PREVIEW_LIMIT]),
        'draft_bills': list(draft_bills_qs.order_by('-created_at')[:PREVIEW_LIMIT]),
        'alerts': alerts[:12],
        'alert_count': len(alerts),
        'can_create_pr': user.is_superuser or PermissionChecker.has_permission(user, 'purchase', 'create'),
        'can_create_po': user.is_superuser or PermissionChecker.has_permission(user, 'purchase', 'create'),
        'can_create_bill': user.is_superuser or PermissionChecker.has_permission(user, 'purchase', 'create'),
    }


def _purchase_alerts(user) -> list[dict]:
    if not (user.is_superuser or PermissionChecker.has_permission(user, 'purchase', 'view')):
        return []

    from apps.core.compliance_service import get_compliance_dashboard_alerts

    alerts = []
    for alert in get_compliance_dashboard_alerts(user):
        if alert.get('module') in PURCHASE_ALERT_MODULES:
            alerts.append(alert)

    today = timezone.localdate()
    for bill in _unpaid_bills_qs().filter(due_date__lt=today).order_by('due_date')[:5]:
        balance = bill.balance
        if balance <= 0:
            continue
        link = reverse('purchase:bill_detail', args=[bill.pk])
        if any(a.get('link') == link for a in alerts):
            continue
        days = (today - bill.due_date).days
        alerts.append(
            {
                'module': 'vendor_bill',
                'module_label': 'Vendor bill',
                'record_label': bill.bill_number,
                'link': link,
                'title': f'Bill overdue — {bill.vendor.name}',
                'detail': f'Due {days} day(s) ago · AED {balance:,.2f} outstanding',
                'severity': 'red',
            },
        )

    pending_count = PurchaseRequest.objects.filter(is_active=True, status='pending').count()
    if pending_count and not any('awaiting approval' in (a.get('title') or '').lower() for a in alerts):
        alerts.append(
            {
                'module': 'purchase_request',
                'module_label': 'Purchase',
                'record_label': 'Queue',
                'link': reverse('purchase:pr_list') + '?status=pending',
                'title': f'{pending_count} purchase request(s) awaiting approval',
                'detail': 'Review and approve or return for revision.',
                'severity': 'amber',
            },
        )

    return alerts
