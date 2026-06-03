"""
Material Requisition — generalized internal stock request (extends ConsumableRequest pattern).
ConsumableRequest remains the storage model; request_kind distinguishes use cases.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel
from apps.core.utils import generate_number


class MaterialRequisitionIssue(BaseModel):
    """One issuance event against a requisition (supports partial issue)."""

    requisition = models.ForeignKey(
        'inventory.ConsumableRequest',
        on_delete=models.CASCADE,
        related_name='issue_events',
    )
    issue_number = models.CharField(max_length=50, unique=True, editable=False)
    warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='requisition_issues',
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='material_requisition_issues',
    )
    issued_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_at', '-pk']

    def save(self, *args, **kwargs):
        if not self.issue_number:
            self.issue_number = generate_number('MRI', MaterialRequisitionIssue, 'issue_number')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.issue_number


class MaterialRequisitionIssueLine(models.Model):
    issue = models.ForeignKey(
        MaterialRequisitionIssue,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    requisition_line = models.ForeignKey(
        'inventory.ConsumableRequestItem',
        on_delete=models.PROTECT,
        related_name='issue_lines',
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    stock_movement = models.ForeignKey(
        'inventory.StockMovement',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requisition_issue_lines',
    )
    storage_location = models.ForeignKey(
        'inventory.StorageLocation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.issue.issue_number}: {self.quantity}'
