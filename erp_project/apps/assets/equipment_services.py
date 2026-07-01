"""Equipment allocation, return, transfer, and project costing helpers."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.projects.models import Project

from .models import (
    EquipmentAllocation,
    EquipmentMaintenanceLog,
    EquipmentMovementLog,
    FixedAsset,
    RentalCostLedger,
)


def _log_movement(
    *,
    asset,
    movement_type,
    user,
    allocation=None,
    from_project=None,
    to_project=None,
    from_location='',
    to_location='',
    notes='',
):
    EquipmentMovementLog.objects.create(
        asset=asset,
        allocation=allocation,
        from_project=from_project,
        to_project=to_project,
        from_location=from_location or asset.current_location,
        to_location=to_location,
        movement_type=movement_type,
        moved_by=user,
        notes=notes,
    )


def _sync_cost_ledger(allocation: EquipmentAllocation):
    """Persist usage cost snapshot (informational only — not project P&L)."""
    hours = allocation.effective_hours()
    days = allocation.usage_days
    total = allocation.display_cost()
    cost_type = allocation.asset.ownership_type
    RentalCostLedger.objects.update_or_create(
        allocation=allocation,
        defaults={
            'hours_used': hours,
            'days_used': days,
            'rate_per_hour': allocation.rate_per_hour,
            'rate_per_day': allocation.rate_per_day,
            'total_cost': total,
            'cost_type': cost_type,
        },
    )


@transaction.atomic
def allocate_asset_to_project(
    asset: FixedAsset,
    project: Project,
    *,
    start_date: date,
    expected_end_date=None,
    user=None,
    notes='',
):
    if not asset.can_allocate():
        raise ValidationError('This equipment is not available for allocation.')

    rate_per_hour = asset.effective_hourly_rate
    rate_per_day = asset.rental_rate_per_day if asset.ownership_type == 'rented' else Decimal('0.00')

    allocation = EquipmentAllocation.objects.create(
        asset=asset,
        project=project,
        start_date=start_date,
        expected_end_date=expected_end_date,
        rate_per_hour=rate_per_hour,
        rate_per_day=rate_per_day,
        allocated_by=user,
        notes=notes,
        created_by=user,
    )
    _sync_cost_ledger(allocation)

    prev_location = asset.current_location or asset.location
    asset.operational_status = 'allocated'
    asset.current_location = f'Project: {project.name}'
    asset.save(update_fields=['operational_status', 'current_location', 'updated_at'])

    _log_movement(
        asset=asset,
        movement_type='allocate',
        user=user,
        allocation=allocation,
        to_project=project,
        from_location=prev_location,
        to_location=asset.current_location,
        notes=notes,
    )
    return allocation


@transaction.atomic
def return_allocation(
    allocation: EquipmentAllocation,
    *,
    return_date=None,
    hours_used=None,
    user=None,
    warehouse_location='',
):
    if allocation.status != 'active':
        raise ValidationError('Only active allocations can be returned.')

    return_date = return_date or date.today()
    allocation.actual_end_date = return_date
    allocation.status = 'returned'
    allocation.returned_by = user
    if hours_used is not None:
        allocation.hours_used = hours_used
    allocation.save()

    asset = allocation.asset
    prev_location = asset.current_location
    asset.operational_status = 'available'
    asset.current_location = warehouse_location or asset.location or 'Warehouse'
    asset.save(update_fields=['operational_status', 'current_location', 'updated_at'])

    _sync_cost_ledger(allocation)
    _log_movement(
        asset=asset,
        movement_type='return',
        user=user,
        allocation=allocation,
        from_project=allocation.project,
        from_location=prev_location,
        to_location=asset.current_location,
    )
    return allocation


@transaction.atomic
def transfer_allocation(
    allocation: EquipmentAllocation,
    target_project: Project,
    *,
    transfer_date=None,
    user=None,
    notes='',
):
    if allocation.status != 'active':
        raise ValidationError('Only active allocations can be transferred.')

    transfer_date = transfer_date or date.today()
    old_project = allocation.project

    allocation.actual_end_date = transfer_date
    allocation.status = 'transferred'
    allocation.returned_by = user
    allocation.save()
    _sync_cost_ledger(allocation)

    asset = allocation.asset
    asset.operational_status = 'available'
    asset.save(update_fields=['operational_status', 'updated_at'])

    new_allocation = allocate_asset_to_project(
        asset,
        target_project,
        start_date=transfer_date,
        expected_end_date=allocation.expected_end_date,
        user=user,
        notes=notes or f'Transferred from {old_project.project_code}',
    )

    _log_movement(
        asset=allocation.asset,
        movement_type='transfer',
        user=user,
        allocation=new_allocation,
        from_project=old_project,
        to_project=target_project,
        notes=notes,
    )
    return new_allocation


@transaction.atomic
def flag_maintenance(asset: FixedAsset, *, reason: str, user=None):
    if asset.operational_status == 'allocated' and asset.active_allocation:
        raise ValidationError('Return equipment from project before flagging maintenance.')

    EquipmentMaintenanceLog.objects.create(
        asset=asset,
        reason=reason,
        flagged_by=user,
        created_by=user,
    )
    asset.operational_status = 'maintenance'
    asset.save(update_fields=['operational_status', 'updated_at'])
    _log_movement(
        asset=asset,
        movement_type='maintenance',
        user=user,
        notes=reason,
    )


@transaction.atomic
def clear_maintenance(log: EquipmentMaintenanceLog, *, user=None):
    if log.cleared_at:
        raise ValidationError('Maintenance already cleared.')
    log.cleared_by = user
    log.cleared_at = timezone.now()
    log.save(update_fields=['cleared_by', 'cleared_at', 'updated_at'])

    asset = log.asset
    if not log.blocks_allocation:
        return log
    if asset.operational_status == 'maintenance':
        asset.operational_status = 'available'
        asset.save(update_fields=['operational_status', 'updated_at'])
    _log_movement(
        asset=asset,
        movement_type='maintenance_clear',
        user=user,
        notes='Maintenance cleared',
    )
    return log


def project_equipment_summary(project: Project):
    """Active + recently returned allocations for project detail card."""
    allocations = (
        EquipmentAllocation.objects.filter(
            project=project,
            is_active=True,
            status='active',
        )
        .select_related('asset', 'allocated_by')
        .order_by('-start_date', '-pk')
    )
    rows = []
    total_cost = Decimal('0.00')
    for alloc in allocations:
        if alloc.status != 'active':
            continue
        cost = alloc.display_cost()
        rows.append({
            'allocation': alloc,
            'asset': alloc.asset,
            'hours': alloc.effective_hours(),
            'rate_per_hour': alloc.rate_per_hour,
            'cost': cost,
            'is_active': True,
        })
        total_cost += cost
    return rows, total_cost


def asset_allocation_context(asset: FixedAsset):
    """Context helpers for asset detail page."""
    active = asset.active_allocation
    history = (
        asset.allocations.filter(is_active=True)
        .select_related('project', 'allocated_by', 'returned_by')
        .order_by('-start_date', '-pk')[:20]
    )
    movements = asset.movement_logs.select_related(
        'from_project', 'to_project', 'moved_by'
    ).order_by('-moved_at')[:15]
    maintenance_qs = asset.maintenance_logs.filter(is_active=True).order_by('-created_at')
    open_maintenance = maintenance_qs.filter(
        cleared_at__isnull=True, blocks_allocation=True,
    ).first()
    return {
        'active_allocation': active,
        'allocation_history': history,
        'movement_logs': movements,
        'maintenance_logs': maintenance_qs[:5],
        'open_maintenance': open_maintenance,
        'can_allocate': asset.can_allocate(),
    }
