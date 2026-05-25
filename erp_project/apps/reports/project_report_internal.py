"""Project Profit and Loss Report: estimate vs utilization, costs, and P&L."""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal

from django.db.models import Count, Sum

from apps.projects.item_delivery import (
    project_inventory_spend_total,
    project_item_delivered_qty,
)
from apps.projects.labour_utils import project_labour_summary
from apps.projects.models import Project, ProjectItemDelivery, ProjectItemLine, ProjectItemReturn
from apps.purchase.models import VendorBill


def _decimal(value) -> Decimal:
    if value is None:
        return Decimal('0.00')
    return Decimal(value)


def _group_estimate_lines(project):
    """Estimate scope lines grouped by group_name."""
    lines = list(
        project.item_lines.select_related('inventory_item').order_by('sort_order', 'id')
    )
    groups = OrderedDict()
    for line in lines:
        key = (line.group_name or '').strip() or 'General'
        groups.setdefault(key, []).append(line)

    total_net = sum((line.line_net or Decimal('0')) for line in lines)
    total_vat = sum((line.vat_amount or Decimal('0')) for line in lines)
    return lines, groups, total_net, total_vat


def _item_gross_delivered_qty(project, item):
    from apps.inventory.models import ItemSerialNumber

    if item.track_by_serial:
        on_site = ItemSerialNumber.objects.filter(
            assigned_project=project,
            item=item,
            status=ItemSerialNumber.STATUS_DELIVERED,
            is_active=True,
        ).count()
        returned = ProjectItemReturn.objects.filter(
            project=project,
            item=item,
            serial_number__isnull=False,
        ).count()
        return Decimal(on_site + returned)

    delivery_sum = (
        ProjectItemDelivery.objects.filter(project=project, item=item).aggregate(t=Sum('quantity'))['t']
        or Decimal('0')
    )
    return delivery_sum


def _item_returned_qty(project, item):
    from apps.inventory.models import ItemSerialNumber

    if item.track_by_serial:
        return Decimal(
            ProjectItemReturn.objects.filter(
                project=project,
                item=item,
                serial_number__isnull=False,
            ).count()
        )

    returned_sum = (
        ProjectItemReturn.objects.filter(
            project=project,
            item=item,
            serial_number__isnull=True,
        ).aggregate(t=Sum('quantity'))['t']
        or Decimal('0')
    )
    return returned_sum


def _utilization_rows(project):
    """All items issued / delivered to the project site."""
    from apps.inventory.models import ItemSerialNumber

    rows = []

    for delivery in (
        ProjectItemDelivery.objects.filter(project=project)
        .select_related('item', 'delivered_by')
        .order_by('-delivered_date', '-pk')
    ):
        rows.append(
            {
                'item_name': delivery.item.name,
                'item_code': delivery.item.item_code,
                'detail': f'Qty {delivery.quantity}',
                'quantity': delivery.quantity,
                'delivered_date': delivery.delivered_date,
                'delivered_by': (
                    delivery.delivered_by.get_full_name() or delivery.delivered_by.username
                    if delivery.delivered_by
                    else '—'
                ),
                'sort_date': delivery.delivered_date,
            }
        )

    for sn in (
        ItemSerialNumber.objects.filter(
            assigned_project=project,
            status=ItemSerialNumber.STATUS_DELIVERED,
            is_active=True,
        )
        .select_related('item', 'delivered_by')
        .order_by('-delivered_date', 'model_number')
    ):
        rows.append(
            {
                'item_name': sn.item.name,
                'item_code': sn.item.item_code,
                'detail': sn.model_number,
                'quantity': Decimal('1'),
                'delivered_date': sn.delivered_date,
                'delivered_by': (
                    sn.delivered_by.get_full_name() or sn.delivered_by.username
                    if sn.delivered_by
                    else '—'
                ),
                'sort_date': sn.delivered_date,
            }
        )

    seen_serial_pks = set()
    for ret in (
        ProjectItemReturn.objects.filter(project=project, serial_number__isnull=False)
        .select_related('item', 'serial_number', 'serial_number__delivered_by')
        .order_by('-returned_date', '-pk')
    ):
        sn = ret.serial_number
        if not sn or sn.pk in seen_serial_pks:
            continue
        seen_serial_pks.add(sn.pk)
        rows.append(
            {
                'item_name': ret.item.name,
                'item_code': ret.item.item_code,
                'detail': sn.model_number,
                'quantity': Decimal('1'),
                'delivered_date': sn.delivered_date,
                'delivered_by': (
                    sn.delivered_by.get_full_name() or sn.delivered_by.username
                    if sn.delivered_by
                    else '—'
                ),
                'sort_date': sn.delivered_date,
            }
        )

    rows.sort(key=lambda r: (r['sort_date'] or project.start_date, r['item_name']), reverse=True)
    return rows


def _return_rows(project):
    rows = []
    for ret in (
        ProjectItemReturn.objects.filter(project=project)
        .select_related('item', 'serial_number', 'returned_by')
        .order_by('-returned_date', '-pk')
    ):
        if ret.serial_number_id:
            detail = ret.serial_number.model_number
            qty = Decimal('1')
        else:
            qty = ret.quantity
            detail = f'Qty {qty}'
        rows.append(
            {
                'item_name': ret.item.name,
                'item_code': ret.item.item_code,
                'detail': detail,
                'quantity': qty,
                'returned_date': ret.returned_date,
                'returned_by': (
                    ret.returned_by.get_full_name() or ret.returned_by.username
                    if ret.returned_by
                    else '—'
                ),
                'notes': ret.notes or '',
            }
        )
    return rows


def _estimate_vs_actual_rows(project, estimate_lines):
    """Compare scoped estimate qty vs delivered / on-site / returned."""
    from apps.inventory.models import Item

    item_map = {}
    for line in estimate_lines:
        if not line.inventory_item_id:
            continue
        item = line.inventory_item
        entry = item_map.setdefault(
            item.pk,
            {
                'item': item,
                'item_name': item.name,
                'item_code': item.item_code,
                'estimated_qty': Decimal('0'),
            },
        )
        entry['estimated_qty'] += line.quantity or Decimal('0')

    delivered_item_ids = set(
        ProjectItemDelivery.objects.filter(project=project).values_list('item_id', flat=True)
    )
    from apps.inventory.models import ItemSerialNumber

    serial_item_ids = set(
        ItemSerialNumber.objects.filter(assigned_project=project).values_list('item_id', flat=True)
    )
    return_item_ids = set(
        ProjectItemReturn.objects.filter(project=project).values_list('item_id', flat=True)
    )
    extra_ids = (delivered_item_ids | serial_item_ids | return_item_ids) - set(item_map.keys())
    for item in Item.objects.filter(pk__in=extra_ids):
        item_map[item.pk] = {
            'item': item,
            'item_name': item.name,
            'item_code': item.item_code,
            'estimated_qty': None,
        }

    rows = []
    for entry in item_map.values():
        item = entry['item']
        delivered = _item_gross_delivered_qty(project, item)
        returned = _item_returned_qty(project, item)
        on_site = project_item_delivered_qty(project, item)
        rows.append(
            {
                **entry,
                'delivered_qty': delivered,
                'returned_qty': returned,
                'on_site_qty': on_site,
                'variance_qty': (
                    (entry['estimated_qty'] - delivered)
                    if entry['estimated_qty'] is not None
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: r['item_name'].lower())
    return rows


def _other_expenses(project):
    manual_qs = (
        project.project_expenses.filter(is_active=True)
        .exclude(status='rejected')
        .exclude(vendor_bill__isnull=False)
        .order_by('-expense_date', '-pk')
    )
    manual_total = manual_qs.aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')

    by_category = (
        manual_qs.values('category')
        .annotate(total=Sum('total_amount'), count=Count('id'))
        .order_by('-total')
    )
    category_labels = dict(project.project_expenses.model.CATEGORY_CHOICES)
    category_rows = [
        {
            'category': row['category'],
            'label': category_labels.get(row['category'], row['category']),
            'total': row['total'] or Decimal('0.00'),
            'count': row['count'],
        }
        for row in by_category
    ]

    vendor_bills = (
        project.vendor_bills.filter(is_active=True)
        .exclude(status='cancelled')
        .select_related('vendor')
        .order_by('-bill_date')
    )
    vendor_bills_total = vendor_bills.aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')

    return {
        'manual_expenses': list(manual_qs),
        'manual_total': manual_total,
        'category_rows': category_rows,
        'vendor_bills': list(vendor_bills),
        'vendor_bills_total': vendor_bills_total,
        'other_expenses_total': manual_total + vendor_bills_total,
    }


def build_project_report_internal(*, project, user=None):
    """
    Build context for Project Profit and Loss Report.
    Covers estimate scope, site utilization, returns, labour, expenses, and P&L.
    """
    from apps.settings_app.models import CompanySettings

    estimate_lines, estimate_groups, estimate_net, estimate_vat = _group_estimate_lines(project)
    utilization_rows = _utilization_rows(project)
    return_rows = _return_rows(project)
    compare_rows = _estimate_vs_actual_rows(project, estimate_lines)

    labour_rows, labour_hours, labour_cost = project_labour_summary(project)
    expenses = _other_expenses(project)
    inventory_spend = project_inventory_spend_total(project)

    materials_and_inventory = inventory_spend
    labour_total = labour_cost
    other_expenses_total = expenses['other_expenses_total']
    total_project_cost = materials_and_inventory + labour_total + other_expenses_total

    contract_value = _decimal(project.contract_value)
    budget = _decimal(project.budget)
    revenue = contract_value if contract_value > 0 else budget

    gross_profit = revenue - total_project_cost
    profit_margin_pct = None
    if revenue > 0:
        profit_margin_pct = (gross_profit / revenue * Decimal('100')).quantize(Decimal('0.1'))

    estimate = project.estimates.filter(is_active=True).order_by('-date', '-pk').first()

    return {
        'project': project,
        'company': CompanySettings.get_settings(),
        'estimate': estimate,
        'estimate_lines': estimate_lines,
        'estimate_groups': estimate_groups,
        'estimate_net_total': estimate_net,
        'estimate_vat_total': estimate_vat,
        'estimate_grand_total': estimate_net + estimate_vat,
        'compare_rows': compare_rows,
        'utilization_rows': utilization_rows,
        'utilization_total_qty': sum((r['quantity'] for r in utilization_rows), Decimal('0')),
        'return_rows': return_rows,
        'return_total_qty': sum((r['quantity'] for r in return_rows), Decimal('0')),
        'labour_rows': labour_rows,
        'labour_total_hours': labour_hours,
        'labour_total_cost': labour_cost,
        'expenses': expenses,
        'inventory_spend_total': inventory_spend,
        'cost_summary': {
            'materials_inventory': materials_and_inventory,
            'labour': labour_total,
            'other_expenses': other_expenses_total,
            'manual_expenses': expenses['manual_total'],
            'vendor_bills': expenses['vendor_bills_total'],
            'total': total_project_cost,
        },
        'revenue': revenue,
        'revenue_label': 'Contract value' if contract_value > 0 else 'Budget (revenue baseline)',
        'contract_value': contract_value,
        'budget': budget,
        'gross_profit': gross_profit,
        'profit_margin_pct': profit_margin_pct,
        'is_profitable': gross_profit >= 0,
        'period_start': project.start_date,
        'period_end': project.end_date,
    }


def project_choices_for_report():
    return (
        Project.objects.filter(is_active=True)
        .select_related('customer', 'manager')
        .order_by('-created_at', '-pk')
    )
