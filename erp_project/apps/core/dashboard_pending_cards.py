"""Homepage module cards — pending approvals / action items per business area."""
from __future__ import annotations

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import PermissionChecker
from apps.crm.dashboard_notifications import get_site_visit_dashboard_alerts

PREVIEW_LIMIT = 3


def _can(user, module: str) -> bool:
    return bool(user and user.is_authenticated and (
        user.is_superuser or PermissionChecker.has_permission(user, module, 'view')
    ))


def _card(*, key, title, icon, color, pending_count, link, items, empty_label='All clear'):
    preview = items[:PREVIEW_LIMIT]
    return {
        'key': key,
        'title': title,
        'icon': icon,
        'color': color,
        'pending_count': pending_count,
        'has_pending': pending_count > 0,
        'link': link,
        'items': preview,
        'remaining_count': max(0, pending_count - len(preview)),
        'empty_label': empty_label,
    }


def _lead_card(user) -> dict | None:
    if not _can(user, 'crm'):
        return None
    alerts = get_site_visit_dashboard_alerts(user)
    items = [
        {
            'label': row['record_label'],
            'detail': row['title'],
            'link': row['link'],
        }
        for row in alerts
    ]
    return _card(
        key='lead',
        title='Lead',
        icon='fa-user-tag',
        color='primary',
        pending_count=len(alerts),
        link=reverse('crm:lead_list'),
        items=items,
        empty_label='No site-visit leads',
    )


def _estimate_card(user) -> dict | None:
    if not _can(user, 'sales'):
        return None
    from apps.core.visibility import filter_estimates_for_user
    from apps.sales.approval_rules import (
        user_can_approve_estimate_edit,
        user_can_approve_estimate_status,
        user_is_any_estimate_approver,
    )
    from apps.sales.models import Estimate

    qs = filter_estimates_for_user(
        Estimate.objects.filter(is_active=True).select_related('customer'),
        user,
    )
    candidates = qs.filter(Q(status='sent') | Q(edit_approval_status='pending')).order_by(
        '-updated_at'
    )

    if user_is_any_estimate_approver(user) and not user.is_superuser:
        pending = []
        for est in candidates:
            if est.status == 'sent' and user_can_approve_estimate_status(user, est):
                pending.append(est)
            elif est.edit_approval_status == 'pending' and user_can_approve_estimate_edit(user, est):
                pending.append(est)
    else:
        pending = list(candidates)

    items = []
    for est in pending:
        if est.edit_approval_status == 'pending':
            detail = 'Edit pending approval'
        else:
            detail = 'Sent for approval'
        items.append(
            {
                'label': est.estimate_number,
                'detail': detail,
                'link': reverse('sales:estimate_detail', args=[est.pk]),
            }
        )

    link = reverse('sales:estimate_list')
    if user_is_any_estimate_approver(user) and not user.is_superuser:
        link = f'{link}?tab=pending'

    return _card(
        key='estimate',
        title='Estimation',
        icon='fa-file-signature',
        color='warning',
        pending_count=len(pending),
        link=link,
        items=items,
        empty_label='No pending approvals',
    )


def _project_card(user) -> dict | None:
    if not _can(user, 'projects'):
        return None
    from apps.core.visibility import filter_projects_for_user
    from apps.projects.approval_rules import (
        pending_completion_projects_for_user,
        pending_conversion_projects_for_user,
        user_is_project_completion_approver,
        user_is_project_conversion_approver,
    )
    from apps.projects.models import Project

    completion = pending_completion_projects_for_user(user)
    conversion = pending_conversion_projects_for_user(user)
    is_approver = user_is_project_completion_approver(user) or user_is_project_conversion_approver(user)

    by_pk = {p.pk: p for p in completion + conversion}
    if not by_pk and not is_approver:
        pq = filter_projects_for_user(Project.objects.filter(is_active=True), user)
        for project in pq.filter(edit_approval_status='pending').select_related('customer'):
            by_pk[project.pk] = project
        for project in pq.filter(
            status='draft', conversion_approval_status='pending'
        ).select_related('customer'):
            by_pk[project.pk] = project

    pending_list = sorted(by_pk.values(), key=lambda p: p.updated_at, reverse=True)
    items = []
    for project in pending_list:
        if project.conversion_approval_status == 'pending' and project.status == 'draft':
            detail = 'Conversion pending approval'
        else:
            detail = 'Completion pending approval'
        items.append(
            {
                'label': project.project_code,
                'detail': detail,
                'link': reverse('projects:project_detail', args=[project.pk]),
            }
        )

    return _card(
        key='project',
        title='Project',
        icon='fa-project-diagram',
        color='info',
        pending_count=len(pending_list),
        link=reverse('projects:project_list'),
        items=items,
        empty_label='No pending approvals',
    )


def _inspection_card(user) -> dict | None:
    if not _can(user, 'projects'):
        return None
    from apps.projects.models import Inspection

    rows = (
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
    pending = [i for i in rows if i.item_count and i.done_count < i.item_count]
    pending.sort(key=lambda i: (i.item_count - i.done_count), reverse=True)

    items = [
        {
            'label': insp.inspection_number,
            'detail': f'{insp.item_count - insp.done_count} checklist item(s) open',
            'link': reverse('projects:inspection_detail', args=[insp.pk]),
        }
        for insp in pending
    ]

    return _card(
        key='inspection',
        title='Inspection',
        icon='fa-clipboard-check',
        color='success',
        pending_count=len(pending),
        link=reverse('projects:inspection_list'),
        items=items,
        empty_label='All checklists complete',
    )


def _operation_card(user) -> dict | None:
    if not _can(user, 'projects'):
        return None
    from apps.operations.models import StaffDutySchedule

    today = timezone.localdate()
    qs = (
        StaffDutySchedule.objects.filter(
            is_active=True,
            status='scheduled',
            duty_date__lt=today,
        )
        .select_related('employee', 'project', 'amc_contract')
        .order_by('-duty_date')
    )
    pending = list(qs)

    items = []
    for duty in pending:
        target = duty.project.project_code if duty.project_id else (
            duty.amc_contract.contract_number if duty.amc_contract_id else '—'
        )
        items.append(
            {
                'label': duty.employee.full_name if duty.employee_id else 'Staff',
                'detail': f'Missed duty · {target}',
                'link': reverse('operations:schedule_list'),
            }
        )

    return _card(
        key='operation',
        title='Operation',
        icon='fa-hard-hat',
        color='secondary',
        pending_count=len(pending),
        link=reverse('operations:schedule_list'),
        items=items,
        empty_label='No missed duties',
    )


def _support_card(user) -> dict | None:
    if not _can(user, 'support'):
        return None
    from apps.support.models import SupportTicket

    open_qs = SupportTicket.objects.filter(is_active=True).filter(
        Q(kanban_stage__isnull=True) | Q(kanban_stage__is_closed=False)
    )
    pending_qs = open_qs.filter(
        Q(assigned_to__isnull=True)
        | Q(kanban_stage__slug='new')
        | Q(kanban_stage__isnull=True)
    ).select_related('kanban_stage', 'customer', 'project').order_by('-opened_date')
    pending = list(pending_qs)

    items = [
        {
            'label': ticket.ticket_number,
            'detail': ticket.subject[:80],
            'link': reverse('support:ticket_detail', args=[ticket.pk]),
        }
        for ticket in pending
    ]

    return _card(
        key='support',
        title='Support',
        icon='fa-life-ring',
        color='danger',
        pending_count=len(pending),
        link=reverse('support:ticket_list'),
        items=items,
        empty_label='No unattended tickets',
    )


def _purchase_request_card(user) -> dict | None:
    from apps.purchase.models import PurchaseRequest
    from apps.purchase.pr_approval_rules import user_can_act_on_purchase_request, user_is_any_pr_approver

    if not user_is_any_pr_approver(user):
        return None

    pending_qs = (
        PurchaseRequest.objects.filter(is_active=True, status='pending')
        .select_related('requested_by')
        .order_by('-updated_at')
    )
    pending = [pr for pr in pending_qs if user_can_act_on_purchase_request(user, pr)]
    items = [
        {
            'label': pr.pr_number,
            'detail': pr.requested_by.get_full_name() or pr.requested_by.username,
            'link': reverse('purchase:pr_detail', args=[pr.pk]),
        }
        for pr in pending
    ]
    return _card(
        key='purchase_request',
        title='Purchase request',
        icon='fa-clipboard-list',
        color='warning',
        pending_count=len(pending),
        link=f'{reverse("purchase:pr_list")}?status=pending',
        items=items,
        empty_label='No pending approvals',
    )


def get_dashboard_pending_cards(user) -> list[dict]:
    builders = (
        _lead_card,
        _estimate_card,
        _project_card,
        _purchase_request_card,
        _inspection_card,
        _operation_card,
        _support_card,
    )
    cards = []
    for builder in builders:
        card = builder(user)
        if card is not None:
            cards.append(card)
    return cards
