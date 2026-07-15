"""Central alerts hub — section-wise red flags across ERP modules (permission-gated)."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import PermissionChecker

PREVIEW_LIMIT = 10
STALE_LEAD_DAYS = 14
AMC_HORIZON_DAYS = 30


def user_can_access_alerts_hub(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if PermissionChecker.has_permission(user, 'settings', 'view'):
        return True
    return bool(PermissionChecker.get_user_permissions(user))


def _can(user, module: str) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or PermissionChecker.has_permission(user, module, 'view'))
    )


def _item(*, label: str, detail: str, link: str, severity: str = 'warning') -> dict:
    return {'label': label, 'detail': detail, 'link': link, 'severity': severity}


def _group(*, title: str, link: str, items: list[dict], total_count: int | None = None) -> dict:
    count = total_count if total_count is not None else len(items)
    return {
        'title': title,
        'link': link,
        'count': count,
        'has_alerts': count > 0,
        'items': items[:PREVIEW_LIMIT],
        'remaining': max(0, count - min(len(items), PREVIEW_LIMIT)),
    }


def _section(*, key: str, module: str, title: str, icon: str, groups: list[dict]) -> dict:
    total = sum(g['count'] for g in groups)
    return {
        'key': key,
        'module': module,
        'title': title,
        'icon': icon,
        'anchor': key,
        'total_count': total,
        'has_alerts': total > 0,
        'groups': groups,
    }


# Gearup Agent (homepage) compliance flags → alerts hub section keys
_COMPLIANCE_SECTION_MAP = {
    'estimate': 'sales',
    'purchase_order': 'purchase',
    'purchase_request': 'purchase',
    'project': 'projects',
    'employee': 'hr',
}

_COMPLIANCE_GROUP_LINKS = {
    'sales': lambda: reverse('sales:estimate_list'),
    'purchase': lambda: reverse('purchase:dashboard'),
    'projects': lambda: reverse('projects:project_list'),
    'hr': lambda: reverse('hr:employee_list'),
}


def _compliance_alert_to_item(alert: dict) -> dict:
    detail = str(alert.get('title') or 'Compliance issue')
    extra = str(alert.get('detail') or '').strip()
    if extra:
        detail = f'{detail} · {extra}'
    return _item(
        label=str(alert.get('record_label') or alert.get('module_label') or 'Record'),
        detail=detail,
        link=alert['link'],
        severity='danger',
    )


def _bucket_compliance_alerts(user) -> dict[str, list[dict]]:
    """Same AI compliance data as the homepage Gearup Agent card, keyed by alerts section."""
    from apps.core.compliance_service import get_compliance_dashboard_alerts

    buckets: dict[str, list[dict]] = {}
    for alert in get_compliance_dashboard_alerts(user):
        section_key = _COMPLIANCE_SECTION_MAP.get(alert.get('module', ''))
        if section_key:
            buckets.setdefault(section_key, []).append(alert)
    return buckets


def _compliance_group(section_key: str, alerts: list[dict]) -> dict | None:
    if not alerts:
        return None
    link_fn = _COMPLIANCE_GROUP_LINKS.get(section_key)
    link = link_fn() if link_fn else '/'
    items = [_compliance_alert_to_item(a) for a in alerts]
    group = _group(
        title='Gearup Agent — AI compliance',
        link=link,
        items=items,
        total_count=len(items),
    )
    group['source'] = 'gearup_agent'
    return group


def _inject_compliance_groups(sections: list[dict], user) -> None:
    """Merge homepage Gearup Agent flags into matching alert sections (in-place)."""
    buckets = _bucket_compliance_alerts(user)
    for section in sections:
        alerts = buckets.get(section['key'], [])
        group = _compliance_group(section['key'], alerts)
        if not group:
            continue
        section['groups'].insert(0, group)
        section['total_count'] = sum(g['count'] for g in section['groups'])
        section['has_alerts'] = section['total_count'] > 0


def _contracts_section(user, today) -> dict | None:
    if not _can(user, 'contracts'):
        return None
    from apps.contracts.models import Contract, ContractDocumentExpiry

    horizon = today + timedelta(days=AMC_HORIZON_DAYS)
    amc_qs = (
        Contract.objects.filter(is_active=True)
        .exclude(status='cancelled')
        .filter(Q(contract_types__name__iexact='AMC') | Q(contract_types__slug__icontains='amc'))
        .distinct()
    )
    amc_expired = amc_qs.filter(end_date__lt=today)
    amc_expiring = amc_qs.filter(end_date__gte=today, end_date__lte=horizon)

    amc_items = []
    for c in amc_expired.select_related('customer').order_by('end_date')[:PREVIEW_LIMIT]:
        amc_items.append(
            _item(
                label=c.contract_number,
                detail=f'Expired {c.end_date:%d %b %Y} · {c.customer.name if c.customer_id else "—"}',
                link=reverse('contracts:contract_detail', args=[c.pk]),
                severity='danger',
            )
        )
    for c in amc_expiring.select_related('customer').order_by('end_date')[: max(0, PREVIEW_LIMIT - len(amc_items))]:
        amc_items.append(
            _item(
                label=c.contract_number,
                detail=f'Expires {c.end_date:%d %b %Y} · {c.customer.name if c.customer_id else "—"}',
                link=reverse('contracts:contract_detail', args=[c.pk]),
                severity='warning',
            )
        )

    doc_qs = ContractDocumentExpiry.objects.filter(
        is_active=True,
        contract__is_active=True,
    ).select_related('contract', 'contract__customer')
    doc_expired = [d for d in doc_qs if d.is_expired]
    doc_due = [d for d in doc_qs if d.reminder_due() and not d.is_expired]
    doc_expired.sort(key=lambda d: d.expiry_date)
    doc_due.sort(key=lambda d: d.expiry_date)

    doc_items = []
    for d in doc_expired[:PREVIEW_LIMIT]:
        doc_items.append(
            _item(
                label=d.document_name,
                detail=f'Expired {d.expiry_date:%d %b %Y} · {d.contract.contract_number}',
                link=reverse('contracts:contract_detail', args=[d.contract_id]),
                severity='danger',
            )
        )
    for d in doc_due[: max(0, PREVIEW_LIMIT - len(doc_items))]:
        doc_items.append(
            _item(
                label=d.document_name,
                detail=f'Due {d.expiry_date:%d %b %Y} · {d.contract.contract_number}',
                link=reverse('contracts:contract_detail', args=[d.contract_id]),
                severity='warning',
            )
        )

    return _section(
        key='contracts',
        module='contracts',
        title='Contracts & AMC',
        icon='fa-file-contract',
        groups=[
            _group(
                title='AMC expiry',
                link=reverse('contracts:contract_list'),
                items=amc_items,
                total_count=amc_expired.count() + amc_expiring.count(),
            ),
            _group(
                title='Document expiry',
                link=reverse('contracts:contract_list'),
                items=doc_items,
                total_count=len(doc_expired) + len(doc_due),
            ),
        ],
    )


def _support_section(user) -> dict | None:
    if not _can(user, 'support'):
        return None
    from apps.support.models import SupportTicket

    open_qs = SupportTicket.objects.filter(is_active=True).filter(
        Q(kanban_stage__isnull=True) | Q(kanban_stage__is_closed=False)
    )
    unattended = open_qs.filter(
        Q(assigned_to__isnull=True)
        | Q(kanban_stage__slug='new')
        | Q(kanban_stage__isnull=True)
    ).select_related('customer', 'project', 'kanban_stage').order_by('-opened_date')

    items = [
        _item(
            label=t.ticket_number,
            detail=(t.subject or '')[:80] or 'Unattended ticket',
            link=reverse('support:ticket_detail', args=[t.pk]),
            severity='danger',
        )
        for t in unattended[:PREVIEW_LIMIT]
    ]
    return _section(
        key='support',
        module='support',
        title='Support',
        icon='fa-life-ring',
        groups=[
            _group(
                title='Tickets not attended',
                link=f'{reverse("support:ticket_list")}?stage=unassigned',
                items=items,
                total_count=unattended.count(),
            ),
        ],
    )


def _crm_section(user, today) -> dict | None:
    if not _can(user, 'crm'):
        return None
    from apps.crm.models import Customer
    from apps.crm.dashboard_notifications import get_site_visit_dashboard_alerts

    leads = Customer.objects.filter(is_active=True, customer_type='lead').exclude(
        lead_kanban_stage__slug='lost'
    )
    unassigned_owner = leads.filter(assigned_salesperson__isnull=True)
    unassigned_stage = leads.filter(lead_kanban_stage__isnull=True)
    stale_cutoff = timezone.now() - timedelta(days=STALE_LEAD_DAYS)
    stale = leads.filter(updated_at__lt=stale_cutoff)

    site_alerts = get_site_visit_dashboard_alerts(user)

    def lead_items(qs, detail_fn):
        return [
            _item(
                label=lead.name or f'Lead #{lead.pk}',
                detail=detail_fn(lead),
                link=reverse('crm:customer_detail', args=[lead.pk]),
                severity='warning',
            )
            for lead in qs.select_related('lead_kanban_stage', 'assigned_salesperson')[:PREVIEW_LIMIT]
        ]

    return _section(
        key='crm',
        module='crm',
        title='Leads & CRM',
        icon='fa-user-tag',
        groups=[
            _group(
                title='Leads not assigned (owner)',
                link=f'{reverse("crm:lead_list")}?stage=unassigned',
                items=lead_items(unassigned_owner, lambda l: 'No salesperson assigned'),
                total_count=unassigned_owner.count(),
            ),
            _group(
                title='Leads not on pipeline stage',
                link=f'{reverse("crm:lead_list")}?stage=unassigned',
                items=lead_items(unassigned_stage, lambda l: 'No kanban stage'),
                total_count=unassigned_stage.count(),
            ),
            _group(
                title=f'Stale leads (no move ≥{STALE_LEAD_DAYS} days)',
                link=reverse('crm:lead_list'),
                items=lead_items(stale, lambda l: f'Last updated {l.updated_at:%d %b %Y}'),
                total_count=stale.count(),
            ),
            _group(
                title='Site visit leads (action needed)',
                link=reverse('crm:lead_dashboard'),
                items=[
                    _item(
                        label=row['record_label'],
                        detail=row['title'],
                        link=row['link'],
                        severity='warning',
                    )
                    for row in site_alerts[:PREVIEW_LIMIT]
                ],
                total_count=len(site_alerts),
            ),
        ],
    )


def _sales_section(user) -> dict | None:
    if not _can(user, 'sales'):
        return None
    from apps.core.visibility import filter_estimates_for_user
    from apps.sales.models import Estimate

    qs = filter_estimates_for_user(
        Estimate.objects.filter(is_active=True).select_related('customer'),
        user,
    )
    pending_est = qs.filter(Q(status='sent') | Q(edit_approval_status='pending')).order_by('-updated_at')
    open_quotes = qs.filter(status='under_negotiation').order_by('-valid_until')
    today = timezone.localdate()
    quotes_past_validity = open_quotes.filter(valid_until__lt=today)

    def est_items(rows, detail):
        return [
            _item(
                label=e.estimate_number,
                detail=detail(e),
                link=reverse('sales:estimate_detail', args=[e.pk]),
                severity='warning',
            )
            for e in rows[:PREVIEW_LIMIT]
        ]

    return _section(
        key='sales',
        module='sales',
        title='Sales — Estimates & Quotations',
        icon='fa-file-signature',
        groups=[
            _group(
                title='Estimates pending approval',
                link=f'{reverse("sales:estimate_list")}?tab=pending',
                items=est_items(
                    pending_est,
                    lambda e: 'Edit pending approval' if e.edit_approval_status == 'pending' else 'Sent for approval',
                ),
                total_count=pending_est.count(),
            ),
            _group(
                title='Open quotations (not won)',
                link=reverse('sales:quotation_list'),
                items=est_items(open_quotes, lambda e: e.customer.name if e.customer_id else 'Open quote'),
                total_count=open_quotes.count(),
            ),
            _group(
                title='Quotations past validity',
                link=reverse('sales:quotation_list'),
                items=est_items(
                    quotes_past_validity,
                    lambda e: f'Valid until {e.valid_until:%d %b %Y}' if e.valid_until else 'Past validity',
                ),
                total_count=quotes_past_validity.count(),
            ),
        ],
    )


def _projects_section(user, today) -> dict | None:
    if not _can(user, 'projects'):
        return None
    from apps.core.visibility import filter_projects_for_user
    from apps.projects.approval_rules import (
        pending_completion_projects_for_user,
        pending_conversion_projects_for_user,
    )
    from apps.projects.models import Inspection, Project, ProjectExpense, Task
    from apps.reports.project_report_financial import COMPLETED_STATUSES

    pq = filter_projects_for_user(Project.objects.filter(is_active=True), user)
    incomplete = pq.exclude(status__in=COMPLETED_STATUSES).exclude(status='cancelled')
    overdue = incomplete.filter(end_date__lt=today, end_date__isnull=False)

    completion = pending_completion_projects_for_user(user)
    conversion = pending_conversion_projects_for_user(user)
    approval_pks = {p.pk for p in completion + conversion}
    for p in pq.filter(edit_approval_status='pending'):
        approval_pks.add(p.pk)
    for p in pq.filter(status='draft', conversion_approval_status='pending'):
        approval_pks.add(p.pk)
    pending_projects = list(pq.filter(pk__in=approval_pks).select_related('customer')[:PREVIEW_LIMIT])

    tasks_open = Task.objects.filter(is_active=True, status__in=('pending', 'in_progress'))
    tasks_overdue = tasks_open.filter(due_date__lt=today, due_date__isnull=False)

    expenses_pending = ProjectExpense.objects.filter(is_active=True, status='draft')

    insp_rows = (
        Inspection.objects.filter(is_active=True)
        .select_related('project', 'amc_contract')
        .annotate(
            item_count=Count('checklist_items', filter=Q(checklist_items__is_active=True)),
            done_count=Count(
                'checklist_items',
                filter=Q(checklist_items__is_active=True, checklist_items__is_flagged_red=True),
            ),
        )
    )
    pending_insp = [i for i in insp_rows if i.item_count and i.done_count < i.item_count]

    return _section(
        key='projects',
        module='projects',
        title='Projects, Tasks & Expenses',
        icon='fa-project-diagram',
        groups=[
            _group(
                title='Projects overdue (not completed)',
                link=f'{reverse("projects:project_list")}?status=ongoing',
                items=[
                    _item(
                        label=p.project_code,
                        detail=f'Due {p.end_date:%d %b %Y}' if p.end_date else 'Overdue',
                        link=reverse('projects:project_detail', args=[p.pk]),
                        severity='danger',
                    )
                    for p in overdue.select_related('customer').order_by('end_date')[:PREVIEW_LIMIT]
                ],
                total_count=overdue.count(),
            ),
            _group(
                title='Projects pending approval',
                link=f'{reverse("projects:project_list")}?status=completion_pending',
                items=[
                    _item(
                        label=p.project_code,
                        detail='Completion or conversion pending',
                        link=reverse('projects:project_detail', args=[p.pk]),
                        severity='warning',
                    )
                    for p in pending_projects
                ],
                total_count=len(approval_pks),
            ),
            _group(
                title='Tasks not completed',
                link=f'{reverse("projects:task_list")}?status=pending',
                items=[
                    _item(
                        label=t.name[:60],
                        detail=f'{t.get_status_display()} · {t.project.project_code if t.project_id else "—"}',
                        link=reverse('projects:task_list') + f'?project={t.project_id}' if t.project_id else reverse('projects:task_list'),
                        severity='warning',
                    )
                    for t in tasks_open.select_related('project').order_by('due_date')[:PREVIEW_LIMIT]
                ],
                total_count=tasks_open.count(),
            ),
            _group(
                title='Tasks overdue',
                link=f'{reverse("projects:task_list")}?status=pending',
                items=[
                    _item(
                        label=t.name[:60],
                        detail=f'Due {t.due_date:%d %b %Y}',
                        link=reverse('projects:task_list') + f'?project={t.project_id}' if t.project_id else reverse('projects:task_list'),
                        severity='danger',
                    )
                    for t in tasks_overdue.select_related('project').order_by('due_date')[:PREVIEW_LIMIT]
                ],
                total_count=tasks_overdue.count(),
            ),
            _group(
                title='Project expenses not approved',
                link=f'{reverse("projects:expense_list")}?status=draft',
                items=[
                    _item(
                        label=exp.expense_number,
                        detail=f'AED {exp.total_amount:,.2f} · {exp.project.project_code if exp.project_id else "—"}',
                        link=reverse('projects:expense_detail', args=[exp.pk]),
                        severity='warning',
                    )
                    for exp in expenses_pending.select_related('project').order_by('-created_at')[:PREVIEW_LIMIT]
                ],
                total_count=expenses_pending.count(),
            ),
            _group(
                title='Inspections not completed',
                link=reverse('projects:inspection_list'),
                items=[
                    _item(
                        label=i.inspection_number,
                        detail=f'{i.item_count - i.done_count} checklist item(s) open',
                        link=reverse('projects:inspection_detail', args=[i.pk]),
                        severity='warning',
                    )
                    for i in sorted(pending_insp, key=lambda x: x.item_count - x.done_count, reverse=True)[:PREVIEW_LIMIT]
                ],
                total_count=len(pending_insp),
            ),
        ],
    )


def _operations_section(user, today) -> dict | None:
    if not _can(user, 'projects'):
        return None
    from apps.operations.models import StaffDutySchedule

    active = (
        StaffDutySchedule.STATUS_SCHEDULED,
        StaffDutySchedule.STATUS_PENDING,
        StaffDutySchedule.STATUS_IN_PROGRESS,
    )
    overdue_past = StaffDutySchedule.objects.filter(
        is_active=True,
        duty_date__lt=today,
        status__in=active,
    ).select_related('employee', 'project', 'amc_contract')
    marked_overdue = StaffDutySchedule.objects.filter(is_active=True, status=StaffDutySchedule.STATUS_OVERDUE)
    unassigned = StaffDutySchedule.objects.filter(
        is_active=True,
        employee__isnull=True,
        status__in=(StaffDutySchedule.STATUS_PENDING, StaffDutySchedule.STATUS_SCHEDULED),
    ).select_related('project', 'amc_contract')
    planned_pending = StaffDutySchedule.objects.filter(
        is_active=True,
        status=StaffDutySchedule.STATUS_PENDING,
    ).select_related('employee', 'project', 'amc_contract')

    def duty_items(qs, detail_fn, severity='warning'):
        return [
            _item(
                label=d.employee.full_name if d.employee_id else 'Unassigned',
                detail=detail_fn(d),
                link=reverse('operations:schedule_list'),
                severity=severity,
            )
            for d in qs.order_by('duty_date')[:PREVIEW_LIMIT]
        ]

    return _section(
        key='operations',
        module='projects',
        title='Operations & Scheduling',
        icon='fa-hard-hat',
        groups=[
            _group(
                title='Scheduled duties missed (past date)',
                link=f'{reverse("operations:schedule_list")}?status=overdue',
                items=duty_items(
                    overdue_past,
                    lambda d: f'{d.duty_date:%d %b %Y} · {d.project.project_code if d.project_id else (d.amc_contract.contract_number if d.amc_contract_id else "—")}',
                    severity='danger',
                ),
                total_count=overdue_past.count(),
            ),
            _group(
                title='Duties marked overdue',
                link=f'{reverse("operations:schedule_list")}?status=overdue',
                items=duty_items(
                    marked_overdue,
                    lambda d: f'{d.duty_date:%d %b %Y}',
                    severity='danger',
                ),
                total_count=marked_overdue.count(),
            ),
            _group(
                title='Planned / pending (unassigned staff)',
                link=f'{reverse("operations:schedule_list")}?status=pending',
                items=duty_items(
                    unassigned,
                    lambda d: f'Pending · {d.duty_date:%d %b %Y}',
                ),
                total_count=unassigned.count(),
            ),
            _group(
                title='Pending duties (awaiting start)',
                link=f'{reverse("operations:schedule_list")}?status=pending',
                items=duty_items(
                    planned_pending,
                    lambda d: f'{d.duty_date:%d %b %Y}',
                ),
                total_count=planned_pending.count(),
            ),
        ],
    )


def _pr_approval_section(user) -> dict | None:
    """Pending PR approvals for configured approvers without purchase module access."""
    from apps.purchase.models import PurchaseRequest
    from apps.purchase.pr_approval_rules import user_can_act_on_purchase_request, user_is_pr_approver_portal

    if not user_is_pr_approver_portal(user):
        return None

    pending_qs = PurchaseRequest.objects.filter(is_active=True, status='pending').order_by('-updated_at')
    pending = [pr for pr in pending_qs if user_can_act_on_purchase_request(user, pr)]

    return _section(
        key='purchase_approval',
        module='purchase',
        title='Purchase approvals',
        icon='fa-clipboard-check',
        groups=[
            _group(
                title='Purchase requests awaiting your approval',
                link=f'{reverse("purchase:pr_list")}?status=pending',
                items=[
                    _item(
                        label=pr.pr_number,
                        detail=pr.requested_by.get_full_name() if pr.requested_by_id else '—',
                        link=reverse('purchase:pr_detail', args=[pr.pk]),
                        severity='warning',
                    )
                    for pr in pending[:PREVIEW_LIMIT]
                ],
                total_count=len(pending),
            ),
        ],
    )


def _purchase_section(user) -> dict | None:
    if not _can(user, 'purchase'):
        return None
    from apps.core.visibility import filter_purchase_orders_for_user, filter_purchase_requests_for_user
    from apps.purchase.models import PurchaseOrder, PurchaseRequest, VendorBill
    from apps.purchase.purchase_dashboard import build_po_invoice_gaps

    pr_qs = filter_purchase_requests_for_user(
        PurchaseRequest.objects.filter(is_active=True, status='pending'),
        user,
    )
    po_qs = filter_purchase_orders_for_user(PurchaseOrder.objects.filter(is_active=True), user)
    po_gaps = build_po_invoice_gaps(po_qs, preview_limit=PREVIEW_LIMIT)
    po_gap_count = len(build_po_invoice_gaps(po_qs, preview_limit=None))

    bills_pending = VendorBill.objects.filter(is_active=True, status='pending_approval')
    open_po = po_qs.filter(status__in=('draft', 'sent', 'confirmed', 'partial_received')).exclude(status='cancelled')
    po_past_delivery = po_qs.filter(
        status__in=('sent', 'confirmed', 'partial_received'),
        expected_delivery_date__lt=timezone.localdate(),
    )

    return _section(
        key='purchase',
        module='purchase',
        title='Purchase',
        icon='fa-shopping-cart',
        groups=[
            _group(
                title='Purchase requests not approved',
                link=f'{reverse("purchase:pr_list")}?status=pending',
                items=[
                    _item(
                        label=pr.pr_number,
                        detail=f'AED {pr.total_amount:,.2f}',
                        link=reverse('purchase:pr_detail', args=[pr.pk]),
                        severity='warning',
                    )
                    for pr in pr_qs.order_by('-updated_at')[:PREVIEW_LIMIT]
                ],
                total_count=pr_qs.count(),
            ),
            _group(
                title='Open purchase orders',
                link=reverse('purchase:po_list'),
                items=[
                    _item(
                        label=po.po_number,
                        detail=f'{po.get_status_display()} · {po.vendor.name if po.vendor_id else "—"}',
                        link=reverse('purchase:po_detail', args=[po.pk]),
                        severity='warning',
                    )
                    for po in open_po.select_related('vendor').order_by('-order_date')[:PREVIEW_LIMIT]
                ],
                total_count=open_po.count(),
            ),
            _group(
                title='POs past delivery date',
                link=reverse('purchase:po_list'),
                items=[
                    _item(
                        label=po.po_number,
                        detail=f'Expected {po.expected_delivery_date:%d %b %Y}' if po.expected_delivery_date else 'Past delivery',
                        link=reverse('purchase:po_detail', args=[po.pk]),
                        severity='danger',
                    )
                    for po in po_past_delivery.select_related('vendor').order_by('expected_delivery_date')[:PREVIEW_LIMIT]
                ],
                total_count=po_past_delivery.count(),
            ),
            _group(
                title='POs — invoice / payment gaps',
                link=f'{reverse("purchase:dashboard")}#po-invoice-gaps',
                items=[
                    _item(
                        label=row['po'].po_number,
                        detail=row['issue_label'],
                        link=row['link'],
                        severity='danger' if row['severity'] == 'red' else 'warning',
                    )
                    for row in po_gaps
                ],
                total_count=po_gap_count,
            ),
            _group(
                title='Vendor bills pending approval',
                link=f'{reverse("purchase:bill_list")}?status=pending_approval',
                items=[
                    _item(
                        label=b.bill_number,
                        detail=f'{b.vendor.name if b.vendor_id else "—"} · AED {b.total_amount:,.2f}',
                        link=reverse('purchase:bill_detail', args=[b.pk]),
                        severity='warning',
                    )
                    for b in bills_pending.select_related('vendor').order_by('-updated_at')[:PREVIEW_LIMIT]
                ],
                total_count=bills_pending.count(),
            ),
        ],
    )


def _hr_section(user) -> dict | None:
    if not _can(user, 'hr'):
        return None
    from apps.hr.models import LeaveRequest
    from apps.recruitment.models import RecruitmentRequest

    leave_pending = LeaveRequest.objects.filter(
        is_active=True,
        status__in=('pending_manager', 'pending_hr'),
    ).select_related('employee')
    recruitment_pending = RecruitmentRequest.objects.filter(
        is_active=True,
        status=RecruitmentRequest.STATUS_PENDING,
    )

    return _section(
        key='hr',
        module='hr',
        title='HR — Leave & Recruitment',
        icon='fa-users',
        groups=[
            _group(
                title='Leave requests not approved',
                link=f'{reverse("hr:leave_list")}?status=pending',
                items=[
                    _item(
                        label=lr.reference_number or f'Leave #{lr.pk}',
                        detail=f'{lr.get_status_display()} · {lr.employee.full_name if lr.employee_id else "—"}',
                        link=reverse('hr:leave_detail', args=[lr.pk]),
                        severity='warning',
                    )
                    for lr in leave_pending.order_by('-created_at')[:PREVIEW_LIMIT]
                ],
                total_count=leave_pending.count(),
            ),
            _group(
                title='Recruitment requests not approved',
                link=f'{reverse("recruitment:request_list")}?status=pending',
                items=[
                    _item(
                        label=rr.display_reference,
                        detail=rr.get_status_display(),
                        link=reverse('recruitment:request_detail', args=[rr.pk]),
                        severity='warning',
                    )
                    for rr in recruitment_pending.select_related('position').order_by('-created_at')[:PREVIEW_LIMIT]
                ],
                total_count=recruitment_pending.count(),
            ),
        ],
    )


def _inventory_section(user) -> dict | None:
    if not _can(user, 'inventory'):
        return None
    from apps.inventory.models import ConsumableRequest

    pending = ConsumableRequest.objects.filter(
        is_active=True,
        status__in=('submitted', 'pending', 'draft'),
    ).select_related('requested_by', 'project')

    material = pending.filter(request_kind='material')
    consumable = pending.filter(request_kind='consumable')

    def cr_items(qs):
        return [
            _item(
                label=cr.request_number,
                detail=f'{cr.get_status_display()} · {cr.project.project_code if cr.project_id else "—"}',
                link=reverse('inventory:consumable_request_detail', args=[cr.pk]),
                severity='warning',
            )
            for cr in qs.order_by('-created_at')[:PREVIEW_LIMIT]
        ]

    return _section(
        key='inventory',
        module='inventory',
        title='Inventory & Material Requests',
        icon='fa-boxes',
        groups=[
            _group(
                title='Material requests not approved',
                link=f'{reverse("inventory:consumable_request_list")}?status=pending',
                items=cr_items(material),
                total_count=material.count(),
            ),
            _group(
                title='Consumable requests not approved',
                link=f'{reverse("inventory:consumable_request_list")}?status=pending',
                items=cr_items(consumable),
                total_count=consumable.count(),
            ),
        ],
    )


def build_alerts_hub(user) -> dict:
    today = timezone.localdate()
    section_builders = (
        lambda: _contracts_section(user, today),
        lambda: _support_section(user),
        lambda: _crm_section(user, today),
        lambda: _sales_section(user),
        lambda: _projects_section(user, today),
        lambda: _operations_section(user, today),
        lambda: _purchase_section(user),
        lambda: _pr_approval_section(user),
        lambda: _hr_section(user),
        lambda: _inventory_section(user),
    )
    sections = []
    for builder in section_builders:
        section = builder()
        if section is not None:
            sections.append(section)

    _inject_compliance_groups(sections, user)

    total_alerts = sum(s['total_count'] for s in sections)
    sections_with_alerts = sum(1 for s in sections if s['has_alerts'])

    from apps.settings_app.models import ModulePermission

    return {
        'today': today,
        'sections': sections,
        'total_alerts': total_alerts,
        'sections_with_alerts': sections_with_alerts,
        'module_display': dict(ModulePermission.MODULE_CHOICES),
    }
