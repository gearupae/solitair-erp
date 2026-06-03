"""
Material Requisition workflow — generalizes consumable request issue/approve logic.
"""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.consumable_project_lines import sync_consumable_request_to_project_item_lines
from apps.inventory.models import ConsumableRequest, ConsumableRequestItem, Stock, StockMovement
from apps.inventory.models_requisition import MaterialRequisitionIssue, MaterialRequisitionIssueLine


LEGACY_STATUS_MAP = {
    'pending': 'submitted',
    'dispensed': 'issued',
}


def normalize_status(status: str) -> str:
    return LEGACY_STATUS_MAP.get(status, status)


def submit_requisition(req: ConsumableRequest, user):
    status = normalize_status(req.status)
    if status not in ('draft', 'submitted', 'pending'):
        raise ValidationError('Only draft or submitted requisitions can be submitted.')
    req.status = 'submitted'
    req.submitted_at = timezone.now()
    req.save(update_fields=['status', 'submitted_at', 'updated_at'])


def approve_requisition(req: ConsumableRequest, user, warehouse=None, line_approvals=None):
    """
    line_approvals: optional dict {line_pk: qty_approved}
    """
    status = normalize_status(req.status)
    if status not in ('submitted', 'pending', 'draft'):
        raise ValidationError('Only submitted requisitions can be approved.')

    req.status = 'approved'
    req.approved_by = user
    req.approved_date = timezone.now()
    if warehouse:
        req.warehouse = warehouse
        req.source_warehouse = warehouse

    for line in req.items.all():
        qty = (line_approvals or {}).get(line.pk, line.quantity)
        line.qty_approved = Decimal(str(qty)).quantize(Decimal('0.01'))
        line.save(update_fields=['qty_approved'])

    req.save()
    return req


def reject_requisition(req: ConsumableRequest, user, reason=''):
    status = normalize_status(req.status)
    if status not in ('submitted', 'pending', 'approved', 'draft'):
        raise ValidationError('This requisition cannot be rejected.')
    req.status = 'rejected'
    req.approved_by = user
    req.approved_date = timezone.now()
    req.admin_notes = reason
    req.save()


@transaction.atomic
def issue_requisition(req: ConsumableRequest, user, warehouse, line_quantities, notes=''):
    """
    Partial or full issue. line_quantities: {ConsumableRequestItem.pk: qty_to_issue_now}
    """
    status = normalize_status(req.status)
    if status not in ('approved', 'partially_issued'):
        raise ValidationError('Requisition must be approved before issuing.')

    if req.project_id and req.has_serial_tracked_items():
        sync_consumable_request_to_project_item_lines(req)
        req.status = 'issued'
        req.warehouse = warehouse
        req.dispensed_by = user
        req.dispensed_date = timezone.now()
        req.save()
        return None

    issue = MaterialRequisitionIssue.objects.create(
        requisition=req,
        warehouse=warehouse,
        issued_by=user,
        issued_at=timezone.now(),
        notes=notes,
        created_by=user,
    )

    lines_by_id = {ln.pk: ln for ln in req.items.select_for_update()}
    movements = []

    for line_pk, qty_raw in line_quantities.items():
        qty = Decimal(str(qty_raw)).quantize(Decimal('0.01'))
        if qty <= 0:
            continue
        line = lines_by_id.get(int(line_pk))
        if not line:
            raise ValidationError(f'Unknown line id {line_pk}.')

        approved = line.qty_approved if line.qty_approved is not None else line.quantity
        already = line.qty_issued or Decimal('0')
        remaining = (approved - already).quantize(Decimal('0.01'))
        if qty > remaining:
            raise ValidationError(
                f'Cannot issue {qty} for {line.item.name}; only {remaining} remaining on approval.'
            )

        unit_cost = line.unit_cost or line.item.get_issue_unit_cost(warehouse)
        allow_zero = unit_cost <= 0

        stock = Stock.objects.filter(item=line.item, warehouse=warehouse).first()
        if not stock or stock.quantity < qty:
            avail = stock.quantity if stock else Decimal('0')
            raise ValidationError(
                f'Insufficient stock for {line.item.name}. Available: {avail}, requested: {qty}'
            )

        movement = StockMovement.objects.create(
            item=line.item,
            warehouse=warehouse,
            movement_type='out',
            source='manual',
            quantity=qty,
            unit_cost=unit_cost,
            reference=f'Material Requisition: {req.request_number}',
            notes=f'Issued to {req.requested_by.get_full_name() or req.requested_by.username}',
            movement_date=date.today(),
            created_by=user,
        )
        movement.execute(user=user, allow_zero_cost=allow_zero)
        movements.append(movement)

        MaterialRequisitionIssueLine.objects.create(
            issue=issue,
            requisition_line=line,
            quantity=qty,
            stock_movement=movement,
            storage_location=line.storage_location,
        )
        line.qty_issued = (already + qty).quantize(Decimal('0.01'))
        line.save(update_fields=['qty_issued'])

    if not movements and not req.project_id:
        issue.delete()
        raise ValidationError('Enter at least one quantity to issue.')

    all_done = True
    for line in req.items.all():
        approved = line.qty_approved if line.qty_approved is not None else line.quantity
        issued = line.qty_issued or Decimal('0')
        if issued < approved:
            all_done = False
            break

    req.warehouse = warehouse
    req.dispensed_by = user
    req.dispensed_date = timezone.now()
    req.stock_movement = movements[0] if movements else req.stock_movement
    req.status = 'issued' if all_done else 'partially_issued'
    if all_done:
        req.closed_at = timezone.now()
    req.save()
    return issue


def close_requisition(req: ConsumableRequest, user):
    if normalize_status(req.status) not in ('partially_issued', 'approved', 'issued'):
        raise ValidationError('Cannot close this requisition.')
    req.status = 'closed'
    req.closed_at = timezone.now()
    req.save(update_fields=['status', 'closed_at', 'updated_at'])
