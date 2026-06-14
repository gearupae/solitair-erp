"""Sales order numbering for quotation-won estimates."""
from __future__ import annotations

import re

from django.db import transaction

_SO_PATTERN = re.compile(r'^SO-(\d+)$', re.IGNORECASE)


def _next_sales_order_sequence() -> int:
    from .models import Estimate

    max_seq = 0
    for num in (
        Estimate.objects.exclude(sales_order_number__isnull=True)
        .exclude(sales_order_number='')
        .values_list('sales_order_number', flat=True)
    ):
        match = _SO_PATTERN.match((num or '').strip())
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    return max_seq + 1


def allocate_sales_order_number() -> str:
    """Return the next sequential sales order number (SO-1, SO-2, …)."""
    return f'SO-{_next_sales_order_sequence()}'


def ensure_sales_order_number(estimate) -> bool:
    """
    Assign a sales order number when an estimate is quotation-won.
    Returns True if a new number was assigned.
    """
    if estimate.status != 'quotation_won':
        return False
    if (estimate.sales_order_number or '').strip():
        return False
    with transaction.atomic():
        estimate.sales_order_number = allocate_sales_order_number()
        estimate.save(update_fields=['sales_order_number', 'updated_at'])
    return True
