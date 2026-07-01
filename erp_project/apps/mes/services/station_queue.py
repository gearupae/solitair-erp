"""Work queue for floor tablet — parts waiting at a station."""

from __future__ import annotations

from django.db.models import F

from apps.mes.models import Part, ProductionOrder, WorkCenter


def get_station_queue(company, work_center_id: int) -> dict:
    """
    Parts at *work_center* on released/in-production orders, pending or in WIP.
    Ordered by PO due date (earliest first), then PO number.
    """
    try:
        work_center = WorkCenter.objects.get(
            pk=work_center_id,
            company=company,
            is_active=True,
        )
    except WorkCenter.DoesNotExist as exc:
        raise ValueError(f'Work center #{work_center_id} not found.') from exc

    po_statuses = (
        ProductionOrder.STATUS_RELEASED,
        ProductionOrder.STATUS_IN_PRODUCTION,
    )
    part_statuses = (
        Part.STATUS_PENDING,
        Part.STATUS_IN_WIP,
    )

    parts = (
        Part.objects.filter(
            company=company,
            is_active=True,
            current_work_center_id=work_center.pk,
            status__in=part_statuses,
            production_order__is_active=True,
            production_order__status__in=po_statuses,
        )
        .select_related('bom_item', 'production_order')
        .order_by(
            F('production_order__due_date').asc(nulls_last=True),
            'production_order__po_number',
            'barcode',
        )
    )

    items = []
    for part in parts:
        po = part.production_order
        items.append(
            {
                'part_id': part.pk,
                'barcode': part.barcode,
                'po_number': po.po_number,
                'reference': po.reference or '',
                'item_name': part.bom_item.part_name,
                'part_status': part.status,
                'part_status_display': part.get_status_display(),
                'due_date': po.due_date.isoformat() if po.due_date else None,
            },
        )

    return {
        'work_center': {
            'id': work_center.pk,
            'code': work_center.code,
            'name': work_center.name,
        },
        'count': len(items),
        'items': items,
    }
