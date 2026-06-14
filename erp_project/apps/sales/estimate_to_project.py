"""Create a project from an approved estimate (optional line items → project Items card)."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.projects.models import Project, ProjectItemLine

from .models import EstimateItem


def _estimate_line_display_label(line: EstimateItem) -> str:
    """Label for copied scope line — prefer inventory name, then description / group."""
    if line.inventory_item_id:
        inv = line.inventory_item
        name = (getattr(inv, 'name', None) or '').strip()
        if name:
            desc = (line.description or '').strip()
            if desc and desc.lower() != name.lower() and name.lower() not in desc.lower():
                return f'{name} — {desc}'[:500]
            return name[:500]
        fb = (getattr(inv, 'item_code', None) or str(inv).strip())[:500]
        if fb:
            return fb
    text = (line.description or '').strip()
    if text:
        return text[:500]
    group = (line.group_name or '').strip()
    if group:
        return group[:500]
    return f'Estimate line #{line.pk}'[:500]


@transaction.atomic
def create_project_from_estimate(*, estimate, include_items: bool, submitted_by=None):
    """
    Create a new Project, link estimate.project, optionally snapshot estimate lines as
    ProjectItemLine rows (shown under “Items” on the project — not as tasks).
    `estimate` must be quotation-won and not already linked to a project.

    Project fields: ``contract_value`` = estimate selling total; ``budget`` = sum of line
    base cost (qty × unit_price); ``estimated_cost`` is left at zero for manual entry later.
    """
    name = f'{estimate.estimate_number} — {estimate.customer.name}'[:200]
    desc_parts = []
    if estimate.notes:
        desc_parts.append(estimate.notes.strip())
    desc_parts.append(f'Created from estimate {estimate.estimate_number}.')
    description = '\n\n'.join(desc_parts)[:5000]

    from apps.projects.conversion_approval import (
        project_conversion_approval_configured,
        queue_project_conversion_approval,
    )

    needs_conversion_approval = project_conversion_approval_configured()
    initial_status = 'draft' if needs_conversion_approval else 'planning'

    project = Project.objects.create(
        name=name,
        description=description,
        customer=estimate.customer,
        manager=estimate.assigned_to,
        status=initial_status,
        start_date=estimate.date,
        contract_value=estimate.total_amount or Decimal('0.00'),
        budget=estimate.total_cost(),
        estimated_cost=Decimal('0.00'),
    )
    if estimate.assigned_to_id:
        project.members.add(estimate.assigned_to)

    estimate.project = project
    estimate.save(update_fields=['project'])

    if needs_conversion_approval and submitted_by:
        queue_project_conversion_approval(submitted_by, project)

    if include_items:
        qs = (
            EstimateItem.objects.filter(estimate=estimate)
            .order_by('sort_order', 'id')
            .select_related('inventory_item')
        )
        bulk = []
        for line in qs:
            bulk.append(
                ProjectItemLine(
                    project=project,
                    sort_order=line.sort_order,
                    group_name=(line.group_name or '')[:200],
                    description=_estimate_line_display_label(line),
                    inventory_item_id=line.inventory_item_id,
                    quantity=line.quantity or Decimal('0'),
                    unit_price=line.unit_price or Decimal('0'),
                    rate=line.rate or Decimal('0'),
                    line_net=line.total or Decimal('0'),
                    vat_amount=line.vat_amount or Decimal('0'),
                )
            )
        if bulk:
            ProjectItemLine.objects.bulk_create(bulk)

    return project
