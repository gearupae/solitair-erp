"""Activity timeline for a single sales estimate (audit + derived events)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from apps.sales.models import Estimate


@dataclass
class EstimateActivityItem:
    timestamp: datetime
    title: str
    detail: str = ''
    user_label: str = ''
    icon: str = 'fa-circle'
    icon_bg: str = 'bg-secondary'


def _user_label(user) -> str:
    if not user:
        return ''
    return (user.get_full_name() or '').strip() or getattr(user, 'username', '') or ''


def _local_ts(dt) -> datetime:
    if dt is None:
        return timezone.now()
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt)


def _describe_audit_log(log) -> tuple[str, str]:
    changes = log.changes or {}
    action = log.action

    if changes.get('field') == 'status':
        old = changes.get('from_display') or changes.get('from', '')
        new = changes.get('to_display') or changes.get('to', '')
        detail = f'{old} → {new}' if old and new else (new or old or '')
        if changes.get('rejection_reason'):
            detail = f'{detail} · {changes["rejection_reason"]}' if detail else changes['rejection_reason']
        return 'Status changed', detail

    if changes.get('field') == 'revision':
        label = changes.get('revision_label') or f'R{changes.get("revision", "")}'
        note = changes.get('note') or 'Quotation edited and sent for re-approval'
        return f'Revision {label} created', note

    if changes.get('field') == 'edit_approval':
        return changes.get('title', 'Edit review'), changes.get('detail', '')

    if changes.get('field') == 'project':
        return 'Converted to project', changes.get('project_code', changes.get('project_name', ''))

    if changes.get('field') == 'invoice':
        return 'Converted to invoice', changes.get('invoice_number', '')

    if changes.get('field') == 'sales_order':
        return 'Sales order assigned', changes.get('sales_order_number', '')

    if changes.get('field') == 'duplicate':
        return 'Estimate duplicated', changes.get('source_number', '')

    if action == 'create':
        return 'Estimate created', changes.get('estimate_number', '')

    if action == 'approve':
        return 'Approved', changes.get('detail', changes.get('comment', ''))

    if action == 'reject':
        return 'Rejected', changes.get('detail', changes.get('comment', changes.get('rejection_reason', '')))

    if action == 'update' and changes.get('summary'):
        return 'Estimate updated', changes['summary']

    if changes:
        parts = []
        for key, val in changes.items():
            if key in ('estimate_number', 'field'):
                continue
            if isinstance(val, dict) and 'old' in val and 'new' in val:
                parts.append(f'{key}: {val["old"]} → {val["new"]}')
            elif val not in (None, ''):
                parts.append(f'{key}: {val}')
        if parts:
            return 'Record updated', ' · '.join(parts[:4])

    labels = {
        'create': 'Created',
        'update': 'Updated',
        'delete': 'Deleted',
        'approve': 'Approved',
        'reject': 'Rejected',
        'post': 'Posted',
    }
    return labels.get(action, action.replace('_', ' ').title()), ''


def _audit_icon(action: str) -> tuple[str, str]:
    mapping = {
        'create': ('fa-plus', 'bg-success'),
        'update': ('fa-edit', 'bg-info'),
        'delete': ('fa-trash', 'bg-danger'),
        'approve': ('fa-check', 'bg-success'),
        'reject': ('fa-times', 'bg-danger'),
        'post': ('fa-check-double', 'bg-primary'),
    }
    return mapping.get(action, ('fa-circle', 'bg-secondary'))


def get_estimate_activity_feed(estimate: Estimate, *, limit: int = 50) -> list[EstimateActivityItem]:
    """Collect recent activity for one estimate, newest first."""
    from apps.settings_app.models import ApprovalAuditLog, AuditLog

    items: list[EstimateActivityItem] = []
    record_ids = {str(estimate.pk), estimate.estimate_number}

    audit_logs = (
        AuditLog.objects.filter(model='Estimate', record_id__in=record_ids)
        .select_related('user')
        .order_by('-timestamp')[:limit]
    )
    has_any_audit = audit_logs.exists()
    for log in audit_logs:
        title, detail = _describe_audit_log(log)
        icon, icon_bg = _audit_icon(log.action)
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(log.timestamp),
                title=title,
                detail=detail,
                user_label=_user_label(log.user),
                icon=icon,
                icon_bg=icon_bg,
            )
        )

    for approval in (
        ApprovalAuditLog.objects.filter(module='estimate', reference=estimate.estimate_number)
        .select_related('approver')
        .order_by('-timestamp')[:limit]
    ):
        comment_l = (approval.comment or '').lower()
        is_edit_review = 'edit' in comment_l or 'acknowledged' in comment_l
        if has_any_audit and not is_edit_review:
            continue
        action_titles = {
            'approve': 'Edit changes approved' if 'edit' in (approval.comment or '').lower() else 'Estimate approved',
            'reject': 'Estimate rejected',
            'return': 'Returned for revision',
        }
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(approval.timestamp),
                title=action_titles.get(approval.action, approval.get_action_display()),
                detail=(approval.comment or '').strip(),
                user_label=_user_label(approval.approver),
                icon='fa-check' if approval.action == 'approve' else 'fa-times',
                icon_bg='bg-success' if approval.action == 'approve' else 'bg-danger',
            )
        )

    if estimate.edit_approval_status == 'pending' and estimate.edit_approval_submitted_at:
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(estimate.edit_approval_submitted_at),
                title='Edit submitted for approval',
                detail='Changes are waiting for approver review',
                user_label=_user_label(estimate.edit_approval_submitted_by),
                icon='fa-clock',
                icon_bg='bg-warning',
            )
        )

    for snap in estimate.revision_snapshots.select_related('created_by').order_by('-created_at')[:limit]:
        status_label = snap.get_status_at_snapshot_display()
        label = snap.display_title
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(snap.created_at),
                title=f'Revision snapshot saved ({label})',
                detail=f'{status_label} · AED {snap.total_amount:,.2f}',
                user_label=_user_label(snap.created_by),
                icon='fa-code-branch',
                icon_bg='bg-info',
            )
        )

    for pf in estimate.proforma_invoices.select_related('created_by').order_by('-created_at')[:limit]:
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(pf.created_at),
                title='Proforma invoice created',
                detail=f'{pf.proforma_number} · AED {pf.total_amount:,.2f}',
                user_label=_user_label(pf.created_by),
                icon='fa-file-invoice-dollar',
                icon_bg='bg-warning',
            )
        )

    if estimate.project_id and estimate.project:
        project = estimate.project
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(project.created_at),
                title='Linked to project',
                detail=f'{project.project_code} — {project.name}',
                user_label=_user_label(project.created_by),
                icon='fa-project-diagram',
                icon_bg='bg-primary',
            )
        )

    if estimate.sales_order_number:
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(estimate.updated_at),
                title='Sales order number assigned',
                detail=estimate.sales_order_number,
                user_label='',
                icon='fa-trophy',
                icon_bg='bg-success',
            )
        )

    from apps.sales.estimate_public_link import public_quotation_view_stats

    stats = public_quotation_view_stats(estimate)
    if stats.get('total_views'):
        last = stats.get('last_viewed_at')
        detail = f'{stats["total_views"]} view(s) · {stats["unique_devices"]} device(s)'
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(last or estimate.updated_at),
                title='Public quotation link activity',
                detail=detail,
                user_label='',
                icon='fa-external-link-alt',
                icon_bg='bg-secondary',
            )
        )

    has_create = any(item.title == 'Estimate created' for item in items)
    if not has_create and estimate.created_at:
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(estimate.created_at),
                title='Estimate created',
                detail=estimate.display_estimate_number,
                user_label=_user_label(estimate.created_by),
                icon='fa-plus',
                icon_bg='bg-success',
            )
        )

    if (
        estimate.updated_at
        and estimate.created_at
        and estimate.updated_at > estimate.created_at
        and estimate.updated_by_id
    ):
        items.append(
            EstimateActivityItem(
                timestamp=_local_ts(estimate.updated_at),
                title='Last saved',
                detail=f'Status: {estimate.get_status_display()}',
                user_label=_user_label(estimate.updated_by),
                icon='fa-save',
                icon_bg='bg-secondary',
            )
        )

    items.sort(key=lambda item: item.timestamp, reverse=True)
    return items[:limit]


def log_estimate_activity(user, action: str, estimate: Estimate, *, changes=None, request=None) -> None:
    from apps.core.audit import log_audit

    payload = dict(changes or {})
    payload.setdefault('estimate_number', estimate.estimate_number)
    log_audit(user, action, 'Estimate', estimate.pk, changes=payload, request=request)
