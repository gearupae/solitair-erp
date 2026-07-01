"""Part barcode scan — work-center routing and floor tablet payload."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import Q

from apps.mes.models import (
    ChecklistCompletion,
    ChecklistItem,
    Drawing,
    OperationChecklist,
    Part,
    PartScan,
    ProductionOrder,
    WorkCenter,
)
from apps.mes.services.costing import compute_wip_breakdown, recalculate_wip


class ScanError(Exception):
    """Operator-facing scan failure."""

    def __init__(self, message: str, code: str = 'scan_error'):
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass
class ScanResult:
    part: Part
    work_center: WorkCenter
    scan_type: str
    message: str
    wip_value: str


def get_production_line(company) -> list[WorkCenter]:
    """Ordered production-line stations only (excludes sample room, storage, etc.)."""
    return list(
        WorkCenter.objects.filter(
            company=company,
            is_active=True,
            is_production_step=True,
        ).order_by('sequence_order', 'pk'),
    )


def get_next_work_center(company, current: WorkCenter) -> WorkCenter | None:
    """Next line station after *current*; None at Dispatch (last production step)."""
    if not current.is_production_step:
        return None
    route = get_production_line(company)
    for idx, wc in enumerate(route):
        if wc.pk == current.pk and idx + 1 < len(route):
            return route[idx + 1]
    return None


def _update_part_status(part: Part, work_center: WorkCenter) -> None:
    if work_center.is_qc_gate:
        part.status = Part.STATUS_AT_QC
    elif part.status in (Part.STATUS_PENDING, Part.STATUS_CREATED, Part.STATUS_HOLD):
        part.status = Part.STATUS_IN_WIP
    elif part.status != Part.STATUS_DONE:
        part.status = Part.STATUS_IN_WIP


def _released_drawings(part: Part) -> list[Drawing]:
    return list(
        Drawing.objects.filter(
            company=part.company,
            is_active=True,
            is_released=True,
        ).filter(
            Q(bom_item=part.bom_item) | Q(part=part),
        ).order_by('-created_at'),
    )


def _checklist_payload(part: Part, work_center: WorkCenter) -> dict[str, Any] | None:
    checklist = (
        OperationChecklist.objects.filter(
            company=part.company,
            work_center=work_center,
            is_active=True,
        )
        .prefetch_related('items')
        .first()
    )
    if not checklist:
        return None

    completed_ids = set(
        ChecklistCompletion.objects.filter(
            company=part.company,
            part=part,
            work_center=work_center,
            is_active=True,
        ).values_list('checklist_item_id', flat=True),
    )
    items = []
    for item in checklist.items.filter(is_active=True).order_by('sort_order', 'pk'):
        items.append(
            {
                'id': item.pk,
                'label': item.label,
                'requires_sign_off': item.requires_sign_off,
                'completed': item.pk in completed_ids,
            },
        )
    return {
        'id': checklist.pk,
        'name': checklist.name,
        'items': items,
    }


def build_scan_response(result: ScanResult) -> dict[str, Any]:
    part = result.part
    wc = result.work_center
    po = part.production_order
    drawings = _released_drawings(part)
    return {
        'success': True,
        'message': result.message,
        'scan_type': result.scan_type,
        'part': {
            'id': part.pk,
            'barcode': part.barcode,
            'name': part.bom_item.part_name,
            'production_order': po.po_number,
            'production_order_id': po.pk,
            'status': part.status,
            'status_display': part.get_status_display(),
        },
        'work_center': {
            'id': wc.pk,
            'code': wc.code,
            'name': wc.name,
            'is_qc_gate': wc.is_qc_gate,
        },
        'wip_value': result.wip_value,
        'drawings': [
            {
                'id': d.pk,
                'version': d.version,
                'url': d.file.url if d.file else '',
                'filename': d.file.name.rsplit('/', 1)[-1] if d.file else '',
            }
            for d in drawings
            if d.file
        ],
        'checklist': _checklist_payload(part, wc),
    }


@transaction.atomic
def process_scan(
    *,
    company,
    barcode: str,
    work_center_id: int,
    scan_type: str,
    operator=None,
) -> ScanResult:
    barcode = (barcode or '').strip()
    if not barcode:
        raise ScanError('Barcode is required.', code='missing_barcode')

    if scan_type not in (PartScan.SCAN_IN, PartScan.SCAN_OUT):
        raise ScanError('scan_type must be "in" or "out".', code='invalid_scan_type')

    try:
        work_center = WorkCenter.objects.get(
            pk=work_center_id,
            company=company,
            is_active=True,
        )
    except WorkCenter.DoesNotExist as exc:
        raise ScanError(
            f'Work center #{work_center_id} not found for this company.',
            code='unknown_work_center',
        ) from exc

    try:
        part = Part.objects.select_related(
            'bom_item', 'production_order', 'current_work_center',
        ).get(
            company=company,
            barcode=barcode,
            is_active=True,
        )
    except Part.DoesNotExist as exc:
        raise ScanError(
            f'No active part found for barcode "{barcode}".',
            code='unknown_barcode',
        ) from exc

    if part.status == Part.STATUS_SCRAPPED:
        raise ScanError(f'Part "{barcode}" is scrapped and cannot be scanned.', code='part_scrapped')

    po = part.production_order
    if po.status == ProductionOrder.STATUS_DRAFT:
        raise ScanError(
            f'Production order {po.po_number} is not released to the floor yet. '
            'Release the order before scanning parts.',
            code='po_not_released',
        )

    display_wc = work_center

    if scan_type == PartScan.SCAN_IN:
        part.current_work_center = work_center
        _update_part_status(part, work_center)
        message = f'Scanned IN at {work_center.name}'
    else:
        if not work_center.is_production_step:
            raise ScanError(
                f'{work_center.name} is a location, not a production line step. '
                'Use Scan OUT only at line stations (Cutting, Edge Banding, etc.).',
                code='not_production_step',
            )
        if part.current_work_center_id != work_center.pk:
            current_label = (
                part.current_work_center.name
                if part.current_work_center
                else 'no station'
            )
            raise ScanError(
                f'Part is at {current_label}, not {work_center.name}. Scan OUT from the current station.',
                code='wrong_station',
            )
        next_wc = get_next_work_center(company, work_center)
        if next_wc:
            part.current_work_center = next_wc
            _update_part_status(part, next_wc)
            display_wc = next_wc
            message = f'Scanned OUT — moved to {next_wc.name}'
        else:
            part.status = Part.STATUS_DONE
            message = f'Scanned OUT — part complete at {work_center.name}'

    part.save(update_fields=['current_work_center', 'status', 'updated_at'])

    PartScan.objects.create(
        company=company,
        part=part,
        work_center=work_center,
        operator=operator,
        scan_type=scan_type,
    )

    po = part.production_order
    if po.status in (ProductionOrder.STATUS_DRAFT, ProductionOrder.STATUS_RELEASED):
        po.status = ProductionOrder.STATUS_IN_PRODUCTION
        po.save(update_fields=['status', 'updated_at'])

    wip = recalculate_wip(po)

    return ScanResult(
        part=part,
        work_center=display_wc,
        scan_type=scan_type,
        message=message,
        wip_value=str(wip),
    )


@transaction.atomic
def complete_checklist_item(
    *,
    company,
    part_id: int,
    checklist_item_id: int,
    work_center_id: int,
    operator=None,
) -> dict[str, Any]:
    try:
        part = Part.objects.select_related('bom_item', 'production_order').get(
            pk=part_id,
            company=company,
            is_active=True,
        )
    except Part.DoesNotExist as exc:
        raise ScanError('Part not found.', code='unknown_part') from exc

    try:
        work_center = WorkCenter.objects.get(
            pk=work_center_id,
            company=company,
            is_active=True,
        )
    except WorkCenter.DoesNotExist as exc:
        raise ScanError('Work center not found.', code='unknown_work_center') from exc

    try:
        checklist_item = ChecklistItem.objects.select_related('checklist').get(
            pk=checklist_item_id,
            company=company,
            checklist__work_center=work_center,
            is_active=True,
        )
    except ChecklistItem.DoesNotExist as exc:
        raise ScanError('Checklist item not found for this station.', code='unknown_item') from exc

    completion, created = ChecklistCompletion.objects.get_or_create(
        company=company,
        part=part,
        work_center=work_center,
        checklist_item=checklist_item,
        defaults={'operator': operator},
    )
    if not created and operator and not completion.operator_id:
        completion.operator = operator
        completion.save(update_fields=['operator', 'updated_at'])

    checklist = _checklist_payload(part, work_center)
    return {
        'success': True,
        'message': f'Checklist item completed: {checklist_item.label}',
        'checklist': checklist,
    }
