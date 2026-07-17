"""Home dashboard for minimal deployment — Purchase, HR, Inventory + Gearup Agent."""
from __future__ import annotations

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from apps.core.compliance_service import get_compliance_dashboard_alerts, sync_compliance_notifications
from apps.core.dashboard_pending_cards import get_minimal_dashboard_pending_cards
from apps.core.nav_config import MINIMAL_NAV_MENU_MODULE_CODES
from apps.core.utils import PermissionChecker

# Gearup Agent on minimal dashboard — purchase and inventory only.
MINIMAL_AGENT_MODULES = frozenset({
    'purchase_order',
    'purchase_request',
    'vendor_bill',
    'inventory',
    'purchase',
})


def _can(user, module: str) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or PermissionChecker.has_permission(user, module, 'view'))
    )


def _can_purchase_feature(user, feature: str, permission_type: str = 'view') -> bool:
    return PermissionChecker.has_feature_permission(user, 'purchase', feature, permission_type)


def _dashboard_quick_links(user) -> list[dict]:
    links = []
    if _can(user, 'purchase'):
        if _can_purchase_feature(user, 'pr'):
            url = reverse('purchase:pr_list')
        elif _can_purchase_feature(user, 'po'):
            url = reverse('purchase:po_list')
        elif _can_purchase_feature(user, 'bills'):
            url = reverse('purchase:bill_list')
        else:
            url = reverse('purchase:dashboard')
        links.append({'label': 'Purchase', 'url': url, 'icon': 'fa-truck'})
    if _can(user, 'hr'):
        links.append({'label': 'HR', 'url': reverse('hr:dashboard'), 'icon': 'fa-user-friends'})
    if _can(user, 'inventory'):
        links.append({'label': 'Inventory', 'url': reverse('inventory:dashboard'), 'icon': 'fa-boxes'})
    return links


def _dashboard_subtitle(user, today) -> str:
    labels = [link['label'] for link in _dashboard_quick_links(user)]
    date_label = today.strftime('%d %b %Y')
    if not labels:
        return f'As of {date_label}'
    if len(labels) == 1:
        return f'{labels[0]} overview — as of {date_label}'
    return f"{' · '.join(labels)} — as of {date_label}"


def _purchase_summary(user) -> dict | None:
    if not _can(user, 'purchase'):
        return None
    from apps.core.visibility import filter_purchase_orders_for_user, filter_purchase_requests_for_user
    from apps.purchase.models import PurchaseOrder, PurchaseRequest, VendorBill
    from django.db.models import F

    has_pr = _can_purchase_feature(user, 'pr')
    has_po = _can_purchase_feature(user, 'po')
    has_bills = _can_purchase_feature(user, 'bills')

    rows = []
    total = 0
    total_label = 'Purchase activity'
    link = reverse('purchase:dashboard')

    if has_pr:
        pr_qs = filter_purchase_requests_for_user(
            PurchaseRequest.objects.filter(is_active=True),
            user,
        )
        pending_prs = pr_qs.filter(status='pending').count()
        rows.extend([
            {'label': 'PRs awaiting approval', 'count': pending_prs},
            {'label': 'Draft PRs', 'count': pr_qs.filter(status='draft').count()},
            {'label': 'Approved PRs', 'count': pr_qs.filter(status='approved').count()},
        ])
        total = pending_prs
        total_label = 'PRs awaiting approval'
        link = reverse('purchase:pr_list')

    if has_po:
        po_qs = filter_purchase_orders_for_user(
            PurchaseOrder.objects.filter(is_active=True),
            user,
        )
        open_pos = po_qs.exclude(status__in=('received', 'cancelled')).count()
        if not rows:
            total = open_pos
            total_label = 'Open purchase orders'
            link = reverse('purchase:po_list')
        rows.append({'label': 'Open purchase orders', 'count': open_pos})

    if has_bills:
        today = timezone.localdate()
        overdue_bills = VendorBill.objects.filter(
            is_active=True,
            status__in=('posted', 'partial', 'overdue'),
            due_date__lt=today,
        ).filter(total_amount__gt=F('paid_amount')).count()
        rows.append({'label': 'Overdue vendor bills', 'count': overdue_bills})
        if not has_pr and not has_po:
            total = overdue_bills
            total_label = 'Overdue vendor bills'
            link = reverse('purchase:bill_list')

    if not rows:
        return None

    return {
        'title': 'Purchase',
        'icon': 'fa-truck',
        'color': 'warning',
        'total_label': total_label,
        'total': total,
        'link': link,
        'rows': rows[:4],
    }


def _hr_summary(user) -> dict | None:
    if not _can(user, 'hr'):
        return None
    from apps.hr.models import Employee

    emps = Employee.objects.filter(is_active=True)
    status_counts = {r['status']: r['c'] for r in emps.values('status').annotate(c=Count('pk'))}

    return {
        'title': 'HR',
        'icon': 'fa-user-friends',
        'color': 'success',
        'total_label': 'Active employees',
        'total': emps.count(),
        'link': reverse('hr:dashboard'),
        'rows': [
            {'label': 'Active', 'count': status_counts.get('active', 0)},
            {'label': 'Inactive', 'count': status_counts.get('inactive', 0)},
            {'label': 'Terminated', 'count': status_counts.get('terminated', 0)},
        ],
    }


def _inventory_summary(user) -> dict | None:
    if not _can(user, 'inventory'):
        return None
    from apps.inventory.models import Item, Warehouse

    items_in_stock = (
        Item.objects.filter(
            is_active=True,
            item_type='product',
            stock_records__quantity__gt=0,
        )
        .distinct()
        .count()
    )
    low_stock_count = sum(
        1 for item in Item.objects.filter(is_active=True, item_type='product') if item.is_low_stock
    )
    total_items = Item.objects.filter(is_active=True, item_type='product').count()

    return {
        'title': 'Inventory',
        'icon': 'fa-boxes',
        'color': 'info',
        'total_label': 'Items in stock',
        'total': items_in_stock,
        'link': reverse('inventory:dashboard'),
        'rows': [
            {'label': 'Active warehouses', 'count': Warehouse.objects.filter(is_active=True).count()},
            {'label': 'Total items', 'count': total_items},
            {'label': 'Low stock items', 'count': low_stock_count},
        ],
    }


def _inventory_agent_alerts(user) -> list[dict]:
    if not _can(user, 'inventory'):
        return []
    from apps.inventory.models import Item

    alerts = []
    for item in Item.objects.filter(is_active=True, item_type='product')[:60]:
        if not item.is_low_stock:
            continue
        total = item.total_stock
        alerts.append(
            {
                'module': 'inventory',
                'module_label': 'Inventory',
                'record_label': item.item_code,
                'link': reverse('inventory:item_detail', args=[item.pk]),
                'title': 'Low stock — reorder needed',
                'detail': f'{total:g} on hand · minimum {item.minimum_stock:g}',
                'severity': 'red' if total <= 0 else 'amber',
            },
        )
        if len(alerts) >= 12:
            break
    return alerts


def get_minimal_gearup_agent_alerts(user) -> list[dict]:
    """Compliance + operational issues for modules active in minimal deployment."""
    alerts: list[dict] = []

    if _can(user, 'purchase') and (
        _can_purchase_feature(user, 'pr')
        or _can_purchase_feature(user, 'po')
        or _can_purchase_feature(user, 'bills')
    ):
        from apps.purchase.purchase_dashboard import _purchase_alerts

        for row in _purchase_alerts(user):
            module = row.get('module')
            if module == 'purchase_request' and not _can_purchase_feature(user, 'pr'):
                continue
            if module == 'purchase_order' and not _can_purchase_feature(user, 'po'):
                continue
            alerts.append(row)

    for row in get_compliance_dashboard_alerts(user):
        if row.get('module') in MINIMAL_AGENT_MODULES:
            alerts.append(row)

    alerts.extend(_inventory_agent_alerts(user))

    seen: set[tuple] = set()
    deduped: list[dict] = []
    for row in alerts:
        key = (row.get('link'), row.get('title'))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    deduped.sort(
        key=lambda row: (
            0 if row.get('severity') == 'red' else 1,
            row.get('module_label', ''),
            row.get('record_label', ''),
        ),
    )
    return deduped[:80]


def build_minimal_dashboard_context(user) -> dict:
    today = timezone.localdate()
    module_summaries = [
        s for s in (_purchase_summary(user), _hr_summary(user), _inventory_summary(user)) if s
    ]
    dashboard_pending_cards = get_minimal_dashboard_pending_cards(user)
    compliance_alerts = get_minimal_gearup_agent_alerts(user)
    sync_compliance_notifications(user, [a for a in compliance_alerts if a.get('severity') == 'red'])

    summary_count = len(module_summaries)
    if summary_count >= 3:
        summary_cols = 'row-cols-xl-3'
    elif summary_count == 2:
        summary_cols = 'row-cols-xl-2'
    else:
        summary_cols = ''

    card_count = len(dashboard_pending_cards)
    if card_count >= 4:
        pending_cols = 'row-cols-xl-4'
    elif card_count == 3:
        pending_cols = 'row-cols-xl-3'
    elif card_count == 2:
        pending_cols = 'row-cols-xl-2'
    else:
        pending_cols = ''

    return {
        'title': 'Dashboard',
        'today': today,
        'dashboard_month_label': today.strftime('%B %Y'),
        'dashboard_subtitle': _dashboard_subtitle(user, today),
        'dashboard_quick_links': _dashboard_quick_links(user),
        'module_summaries': module_summaries,
        'module_summary_cols': summary_cols,
        'dashboard_pending_cards': dashboard_pending_cards,
        'pending_card_cols': pending_cols,
        'compliance_alerts': compliance_alerts,
        'active_modules': sorted(MINIMAL_NAV_MENU_MODULE_CODES),
    }
