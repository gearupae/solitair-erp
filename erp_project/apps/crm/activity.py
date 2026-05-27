"""Build a unified activity timeline for CRM customer / lead detail pages."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.urls import reverse
from django.utils import timezone

from apps.crm.models import CrmLeadKanbanStage, Customer


@dataclass
class CustomerActivityItem:
    timestamp: datetime
    title: str
    detail: str = ''
    user_label: str = ''
    icon: str = 'fa-circle'
    icon_bg: str = 'bg-secondary'
    url: str = ''


def _user_label(user) -> str:
    if not user:
        return ''
    return (user.get_full_name() or '').strip() or user.username


def _stage_name_map() -> dict[str, str]:
    return {
        s.slug: s.name
        for s in CrmLeadKanbanStage.objects.filter(is_active=True).only('slug', 'name')
    }


def _describe_customer_audit(log, stage_names: dict[str, str]) -> tuple[str, str]:
    changes = log.changes or {}
    action = log.action

    if changes.get('action') == 'kanban_won' or changes.get('converted_to_customer'):
        return 'Converted to customer', 'Moved to Won on the pipeline board'

    if changes.get('action') == 'converted_to_customer':
        return 'Converted to customer', 'Lead was converted to a customer account'

    if 'lead_kanban_stage' in changes:
        val = changes['lead_kanban_stage']
        if val == 'unassigned':
            return 'Pipeline stage updated', 'Set to Unassigned'
        name = stage_names.get(val, val)
        return 'Pipeline stage updated', name

    if 'customer_type' in changes:
        val = changes['customer_type']
        if isinstance(val, dict):
            val = val.get('new', val)
        label = 'Lead' if val == 'lead' else 'Customer'
        return 'Type changed', label

    if 'status' in changes:
        val = changes['status']
        if isinstance(val, dict):
            val = val.get('new', val)
        labels = dict(Customer.STATUS_CHOICES)
        return 'Status changed', labels.get(val, str(val))

    if action == 'create':
        return 'Record created', log.changes.get('name', '') if isinstance(log.changes, dict) else ''

    if action == 'delete':
        return 'Record deactivated', ''

    field_labels = {
        'assigned_salesperson': 'Assigned salesman',
        'business_segment': 'Business type',
        'trn': 'VAT (TRN)',
        'name': 'Contact name',
        'company': 'Company',
    }
    parts = []
    for field, change in changes.items():
        if isinstance(change, dict) and 'old' in change and 'new' in change:
            label = field_labels.get(field, field.replace('_', ' ').title())
            old = change['old'] or '—'
            new = change['new'] or '—'
            parts.append(f'{label}: {old} → {new}')
        elif field in ('name', 'customer_number') and not isinstance(change, dict):
            parts.append(str(change))
    if parts:
        return 'Details updated', '; '.join(parts[:4])

    return action.replace('_', ' ').title(), ''


def get_customer_activity_feed(customer: Customer, *, limit: int = 50) -> list[CustomerActivityItem]:
    """Collect recent activity for a customer or lead, newest first."""
    from apps.projects.models import Project
    from apps.sales.models import Estimate, Invoice
    from apps.settings_app.models import ApprovalAuditLog, AuditLog

    items: list[CustomerActivityItem] = []
    stage_names = _stage_name_map()
    customer_id = str(customer.pk)
    has_create_log = False

    audit_logs = (
        AuditLog.objects.filter(model='Customer', record_id=customer_id)
        .select_related('user')
        .order_by('-timestamp')[:limit]
    )
    for log in audit_logs:
        if log.action == 'create':
            has_create_log = True
        title, detail = _describe_customer_audit(log, stage_names)
        items.append(
            CustomerActivityItem(
                timestamp=log.timestamp,
                title=title,
                detail=detail,
                user_label=_user_label(log.user),
                icon='fa-user-tag' if 'Status' in title or 'Type' in title else 'fa-edit',
                icon_bg='bg-info' if log.action == 'update' else 'bg-success',
            )
        )

    if not has_create_log and customer.created_at:
        items.append(
            CustomerActivityItem(
                timestamp=customer.created_at,
                title='Record created',
                detail=customer.name,
                user_label=_user_label(customer.created_by),
                icon='fa-plus',
                icon_bg='bg-success',
            )
        )

    estimates = (
        Estimate.objects.filter(customer=customer, is_active=True)
        .select_related('created_by', 'updated_by')
        .order_by('-created_at')[:limit]
    )
    estimate_numbers = []
    for est in estimates:
        estimate_numbers.append(est.estimate_number)
        items.append(
            CustomerActivityItem(
                timestamp=timezone.localtime(est.created_at),
                title='Estimate created',
                detail=est.display_estimate_number,
                user_label=_user_label(est.created_by),
                icon='fa-file-invoice',
                icon_bg='bg-warning',
                url=reverse('sales:estimate_detail', args=[est.pk]),
            )
        )
        if est.edit_approval_submitted_at and est.edit_approval_status == 'pending':
            items.append(
                CustomerActivityItem(
                    timestamp=timezone.localtime(est.edit_approval_submitted_at),
                    title='Estimate edit submitted for approval',
                    detail=est.display_estimate_number,
                    user_label=_user_label(est.edit_approval_submitted_by),
                    icon='fa-paper-plane',
                    icon_bg='bg-primary',
                    url=reverse('sales:estimate_detail', args=[est.pk]),
                )
            )

    if estimate_numbers:
        for approval in (
            ApprovalAuditLog.objects.filter(module='estimate', reference__in=estimate_numbers)
            .select_related('approver')
            .order_by('-timestamp')[:limit]
        ):
            action_labels = {
                'approve': 'Estimate approved',
                'reject': 'Estimate rejected',
                'return': 'Estimate returned for revision',
            }
            est = next((e for e in estimates if e.estimate_number == approval.reference), None)
            items.append(
                CustomerActivityItem(
                    timestamp=timezone.localtime(approval.timestamp),
                    title=action_labels.get(approval.action, 'Estimate review'),
                    detail=approval.reference,
                    user_label=_user_label(approval.approver),
                    icon='fa-check' if approval.action == 'approve' else 'fa-times',
                    icon_bg='bg-success' if approval.action == 'approve' else 'bg-danger',
                    url=reverse('sales:estimate_detail', args=[est.pk]) if est else '',
                )
            )

    for inv in (
        Invoice.objects.filter(customer=customer, is_active=True)
        .select_related('created_by')
        .order_by('-created_at')[:limit]
    ):
        items.append(
            CustomerActivityItem(
                timestamp=timezone.localtime(inv.created_at),
                title='Invoice created',
                detail=inv.invoice_number,
                user_label=_user_label(inv.created_by),
                icon='fa-receipt',
                icon_bg='bg-success',
                url=reverse('sales:invoice_detail', args=[inv.pk]),
            )
        )

    for project in (
        Project.objects.filter(customer=customer, is_active=True)
        .select_related('created_by')
        .order_by('-created_at')[:limit]
    ):
        items.append(
            CustomerActivityItem(
                timestamp=timezone.localtime(project.created_at),
                title='Project linked',
                detail=f'{project.project_code} — {project.name}',
                user_label=_user_label(project.created_by),
                icon='fa-project-diagram',
                icon_bg='bg-primary',
                url=reverse('projects:project_detail', args=[project.pk]),
            )
        )

    for upload in customer.public_uploads.filter(is_active=True).order_by('-created_at')[:limit]:
        filename = upload.original_filename or upload.file.name.split('/')[-1]
        items.append(
            CustomerActivityItem(
                timestamp=timezone.localtime(upload.created_at),
                title='Public file uploaded',
                detail=filename,
                user_label='Public upload',
                icon='fa-cloud-upload-alt',
                icon_bg='bg-secondary',
            )
        )

    items.sort(key=lambda item: item.timestamp, reverse=True)
    return items[:limit]
