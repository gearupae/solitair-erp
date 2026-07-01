"""
Manufacturing Execution System (MES) — engineer-to-order joinery / fit-out.

Production Order → BOM → Parts → Work-center operations.
Station sequence is data-driven from WorkCenter.sequence_order (never hardcoded in logic).
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel


class TenantScopedModel(BaseModel):
    """All MES business records are scoped to a legal entity (company)."""

    company = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.PROTECT,
        related_name='%(app_label)s_%(class)s_set',
    )

    class Meta:
        abstract = True


class WorkCenter(TenantScopedModel):
    """Factory station or location (cutting, QC gate, sample room, storage, etc.)."""

    TYPE_MACHINE = 'machine'
    TYPE_MANUAL = 'manual'
    TYPE_LOCATION = 'location'
    TYPE_CHOICES = [
        (TYPE_MACHINE, 'Machine'),
        (TYPE_MANUAL, 'Manual'),
        (TYPE_LOCATION, 'Location'),
    ]

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    sequence_order = models.PositiveSmallIntegerField(
        default=100,
        help_text='Defines routing order; lower numbers are earlier in the flow.',
    )
    center_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_MANUAL)
    is_qc_gate = models.BooleanField(default=False)
    is_production_step = models.BooleanField(
        default=False,
        help_text='True for line stations in the Scan OUT routing path; false for sample room, storage, etc.',
    )
    cost_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Machine + labour standard rate (AED/hr) for costing.',
    )
    capacity_units_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text='Nominal throughput capacity (units/hr) for planning.',
    )

    class Meta:
        ordering = ['company', 'sequence_order', 'name']
        unique_together = [('company', 'code')]
        verbose_name = 'Work center'

    def __str__(self):
        return f'{self.code} — {self.name}'


class ProductTemplate(TenantScopedModel):
    """Reusable product definition — BOM + routing copied into POs as a snapshot."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['company', 'name']
        unique_together = [('company', 'code')]
        verbose_name = 'Product template'

    def __str__(self):
        return f'{self.code} — {self.name}'


class TemplateBOMItem(TenantScopedModel):
    """BOM line on a product template (multi-level via parent)."""

    MATERIAL_PANEL = 'panel'
    MATERIAL_VENEER = 'veneer'
    MATERIAL_HARDWARE = 'hardware'
    MATERIAL_EDGE_TAPE = 'edge_tape'
    MATERIAL_FINISH = 'finish'
    MATERIAL_TYPE_CHOICES = [
        (MATERIAL_PANEL, 'Panel'),
        (MATERIAL_VENEER, 'Veneer'),
        (MATERIAL_HARDWARE, 'Hardware'),
        (MATERIAL_EDGE_TAPE, 'Edge tape'),
        (MATERIAL_FINISH, 'Finish'),
    ]

    template = models.ForeignKey(
        ProductTemplate,
        on_delete=models.CASCADE,
        related_name='bom_items',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
    )
    part_name = models.CharField(max_length=200)
    material_type = models.CharField(max_length=20, choices=MATERIAL_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('1.000'))
    unit = models.CharField(max_length=20, default='pcs')
    item_code = models.CharField(max_length=80, blank=True)
    inventory_item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mes_template_bom_lines',
    )

    class Meta:
        ordering = ['template', 'id']
        verbose_name = 'Template BOM item'

    def __str__(self):
        return self.part_name or self.item_code


class TemplateRoutingOp(TenantScopedModel):
    """Routing step on a product template."""

    template = models.ForeignKey(
        ProductTemplate,
        on_delete=models.CASCADE,
        related_name='routing_ops',
    )
    work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.PROTECT,
        related_name='template_routing_ops',
    )
    sequence = models.PositiveSmallIntegerField(default=100)
    std_time_minutes = models.PositiveSmallIntegerField(default=15)

    class Meta:
        ordering = ['template', 'sequence', 'id']
        unique_together = [('template', 'work_center')]
        verbose_name = 'Template routing operation'

    def __str__(self):
        return f'{self.work_center.code} ({self.std_time_minutes} min)'


class ProductionOrder(TenantScopedModel):
    """Standalone production job (not linked to ERP project module)."""

    STATUS_DRAFT = 'draft'
    STATUS_RELEASED = 'released'
    STATUS_IN_PRODUCTION = 'in_production'
    STATUS_FINISHED = 'finished'
    STATUS_ON_HOLD = 'on_hold'
    STATUS_CANCELLED = 'cancelled'
    # Legacy aliases
    STATUS_IN_PROGRESS = STATUS_IN_PRODUCTION
    STATUS_DONE = STATUS_FINISHED
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_RELEASED, 'Released'),
        (STATUS_IN_PRODUCTION, 'In Production'),
        (STATUS_FINISHED, 'Finished'),
        (STATUS_ON_HOLD, 'On Hold'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    PIPELINE_STAGES = [
        STATUS_DRAFT,
        STATUS_RELEASED,
        STATUS_IN_PRODUCTION,
        STATUS_FINISHED,
    ]

    po_number = models.CharField(max_length=50)
    reference = models.CharField(
        max_length=120,
        blank=True,
        help_text='External / Oracle production order reference',
    )
    quantity = models.PositiveIntegerField(default=1)
    due_date = models.DateField(null=True, blank=True)
    planned_start = models.DateField(null=True, blank=True)
    planned_end = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    wip_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    final_total_cost = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Frozen total cost when order is finished.',
    )
    frozen_material_cost = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
    )
    frozen_labour_cost = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
    )
    frozen_machine_cost = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
    )
    frozen_overhead_cost = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
    )
    cost_frozen_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    overhead_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('10.00'),
        help_text='Factory overhead applied to material + labour + machine (percent).',
    )
    product_template = models.ForeignKey(
        ProductTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='production_orders',
        help_text='Source template (snapshot only — template edits do not affect this PO).',
    )
    source_template_name = models.CharField(max_length=200, blank=True)
    assigned_employees = models.ManyToManyField(
        'hr.Employee',
        blank=True,
        related_name='mes_production_orders',
        help_text='Overall crew assigned to this production order.',
    )

    class Meta:
        ordering = ['-due_date', '-created_at']
        unique_together = [('company', 'po_number')]
        verbose_name = 'Production order'

    def __str__(self):
        return self.po_number

    @property
    def is_editable(self) -> bool:
        return self.status == self.STATUS_DRAFT

    @property
    def is_on_floor(self) -> bool:
        return self.status in (
            self.STATUS_RELEASED,
            self.STATUS_IN_PRODUCTION,
            self.STATUS_ON_HOLD,
        )

    @property
    def is_cost_frozen(self) -> bool:
        return self.cost_frozen_at is not None

    @property
    def pipeline_index(self) -> int:
        try:
            return self.PIPELINE_STAGES.index(self.status)
        except ValueError:
            return -1


class BOMItem(TenantScopedModel):
    """Multi-level bill of materials line (self-referencing parent)."""

    MATERIAL_PANEL = 'panel'
    MATERIAL_VENEER = 'veneer'
    MATERIAL_HARDWARE = 'hardware'
    MATERIAL_EDGE_TAPE = 'edge_tape'
    MATERIAL_FINISH = 'finish'
    MATERIAL_TYPE_CHOICES = [
        (MATERIAL_PANEL, 'Panel'),
        (MATERIAL_VENEER, 'Veneer'),
        (MATERIAL_HARDWARE, 'Hardware'),
        (MATERIAL_EDGE_TAPE, 'Edge tape'),
        (MATERIAL_FINISH, 'Finish'),
    ]

    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name='bom_items',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
    )
    part_name = models.CharField(max_length=200)
    material_type = models.CharField(max_length=20, choices=MATERIAL_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('1.000'))
    unit = models.CharField(max_length=20, default='pcs')
    item_code = models.CharField(max_length=80, blank=True)
    inventory_item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mes_bom_lines',
    )
    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Material cost per BOM unit (AED) for roll-up.',
    )

    class Meta:
        ordering = ['production_order', 'id']
        verbose_name = 'BOM item'
        verbose_name_plural = 'BOM items'

    def __str__(self):
        return self.part_name or self.item_code

    def clean(self):
        super().clean()
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be greater than zero.'})
        if not (self.unit or '').strip():
            raise ValidationError({'unit': 'Unit is required.'})
        if self.parent_id and self.pk and self._creates_parent_cycle():
            raise ValidationError({'parent': 'Circular parent reference is not allowed.'})

    def _creates_parent_cycle(self) -> bool:
        seen = {self.pk}
        node = self.parent
        while node is not None:
            if node.pk in seen:
                return True
            seen.add(node.pk)
            node = node.parent
        return False

    @property
    def is_leaf(self) -> bool:
        return not self.children.filter(is_active=True).exists()


class RoutingOperation(TenantScopedModel):
    """Production routing step — work center + standard time for one operation."""

    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_DONE = 'done'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_DONE, 'Done'),
    ]

    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name='routing_operations',
    )
    work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.PROTECT,
        related_name='routing_operations',
    )
    sequence = models.PositiveSmallIntegerField(
        default=100,
        help_text='Operation order; lower numbers run first.',
    )
    std_time_minutes = models.PositiveSmallIntegerField(
        default=15,
        help_text='Standard run time for this operation (minutes per unit/part).',
    )
    rate_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Labour/machine rate (AED/hr); defaults from work center, editable per operation.',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    assigned_employees = models.ManyToManyField(
        'hr.Employee',
        blank=True,
        related_name='mes_routing_operations',
        help_text='Team members assigned to this operation.',
    )

    class Meta:
        ordering = ['production_order', 'sequence', 'id']
        unique_together = [('production_order', 'work_center')]
        verbose_name = 'Routing operation'

    def __str__(self):
        return f'{self.work_center.code} ({self.std_time_minutes} min)'

    def save(self, *args, **kwargs):
        if self.work_center_id and self.rate_per_hour == Decimal('0.00'):
            self.rate_per_hour = self.work_center.cost_per_hour
        super().save(*args, **kwargs)

    @property
    def planned_labour_cost(self) -> Decimal:
        """Standard labour for one part at this operation."""
        hours = Decimal(self.std_time_minutes) / Decimal('60')
        return (hours * self.rate_per_hour).quantize(Decimal('0.01'))


class ProductionOrderStatusLog(TenantScopedModel):
    """Audit trail for production order status transitions."""

    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name='status_logs',
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    notes = models.CharField(max_length=255, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mes_po_status_changes',
    )

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f'{self.production_order.po_number}: {self.from_status} → {self.to_status}'

    def _status_label(self, code: str) -> str:
        return dict(ProductionOrder.STATUS_CHOICES).get(code, code or '—')

    @property
    def from_status_label(self) -> str:
        return self._status_label(self.from_status)

    @property
    def to_status_label(self) -> str:
        return self._status_label(self.to_status)


class Part(TenantScopedModel):
    """Physically tracked component (barcode is the floor identifier)."""

    STATUS_PENDING = 'pending'
    STATUS_CREATED = 'created'
    STATUS_IN_WIP = 'in_wip'
    STATUS_AT_QC = 'at_qc'
    STATUS_HOLD = 'hold'
    STATUS_DONE = 'done'
    STATUS_SCRAPPED = 'scrapped'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_CREATED, 'Created'),
        (STATUS_IN_WIP, 'In WIP'),
        (STATUS_AT_QC, 'At QC'),
        (STATUS_HOLD, 'Hold'),
        (STATUS_DONE, 'Done'),
        (STATUS_SCRAPPED, 'Scrapped'),
    ]

    barcode = models.CharField(max_length=64, db_index=True)
    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name='parts',
    )
    bom_item = models.ForeignKey(
        BOMItem,
        on_delete=models.PROTECT,
        related_name='parts',
    )
    current_work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parts_at_center',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    parent_part = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='child_parts',
    )
    barcode_image = models.ImageField(
        upload_to='mes/part_barcodes/%Y/%m/',
        blank=True,
        null=True,
        help_text='QR code image for floor label printing.',
    )

    class Meta:
        ordering = ['production_order', 'barcode']
        unique_together = [('company', 'barcode')]
        indexes = [
            models.Index(fields=['company', 'barcode']),
            models.Index(fields=['company', 'production_order', 'status']),
        ]

    def __str__(self):
        return self.barcode


class PartScan(models.Model):
    """Immutable scan event — genealogy and WIP movement source of truth."""

    SCAN_IN = 'in'
    SCAN_OUT = 'out'
    SCAN_TYPE_CHOICES = [
        (SCAN_IN, 'In'),
        (SCAN_OUT, 'Out'),
    ]

    company = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.PROTECT,
        related_name='mes_part_scans',
    )
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name='scans')
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT, related_name='scans')
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mes_part_scans',
    )
    scan_type = models.CharField(max_length=10, choices=SCAN_TYPE_CHOICES)
    machine = models.ForeignKey(
        'Machine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='part_scans',
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Part scan'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('PartScan records are immutable.')
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.part.barcode} {self.scan_type} @ {self.work_center.code}'


class OperationChecklist(TenantScopedModel):
    """Operator checklist template for a work center."""

    work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.CASCADE,
        related_name='checklists',
    )
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ['work_center', 'name']
        unique_together = [('company', 'work_center', 'name')]

    def __str__(self):
        return f'{self.work_center.code}: {self.name}'


class ChecklistItem(TenantScopedModel):
    """Single line on an operation checklist."""

    checklist = models.ForeignKey(
        OperationChecklist,
        on_delete=models.CASCADE,
        related_name='items',
    )
    label = models.CharField(max_length=255)
    sort_order = models.PositiveSmallIntegerField(default=0)
    requires_sign_off = models.BooleanField(default=True)

    class Meta:
        ordering = ['checklist', 'sort_order', 'id']

    def __str__(self):
        return self.label


class ChecklistCompletion(TenantScopedModel):
    """Operator sign-off on a checklist line for a part at a work center."""

    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='checklist_completions')
    work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.PROTECT,
        related_name='checklist_completions',
    )
    checklist_item = models.ForeignKey(
        ChecklistItem,
        on_delete=models.CASCADE,
        related_name='completions',
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mes_checklist_completions',
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']
        unique_together = [('part', 'checklist_item', 'work_center')]
        verbose_name = 'Checklist completion'

    def __str__(self):
        return f'{self.part.barcode} — {self.checklist_item.label}'


class TemplateDrawing(TenantScopedModel):
    """Default drawing on a product-template BOM line (copied to PO on apply)."""

    file = models.FileField(upload_to='mes/template-drawings/%Y/%m/')
    template_bom_item = models.ForeignKey(
        TemplateBOMItem,
        on_delete=models.CASCADE,
        related_name='drawings',
    )
    title = models.CharField(max_length=200, blank=True)
    version = models.CharField(max_length=20, default='1.0')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Template drawing'

    def __str__(self):
        label = self.title or (self.file.name.rsplit('/', 1)[-1] if self.file else 'Drawing')
        return f'{label} v{self.version}'


class Drawing(TenantScopedModel):
    """Released CAD / component drawing for the floor tablet."""

    file = models.FileField(upload_to='mes/drawings/%Y/%m/')
    title = models.CharField(max_length=200, blank=True)
    bom_item = models.ForeignKey(
        BOMItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='drawings',
    )
    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='drawings',
    )
    version = models.CharField(max_length=20, default='1.0')
    is_released = models.BooleanField(
        default=False,
        help_text='Only released drawings are shown on the floor tablet.',
    )

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        if bool(self.bom_item_id) == bool(self.part_id):
            raise ValidationError('Link the drawing to exactly one of bom_item or part.')

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.file:
            return self.file.name.rsplit('/', 1)[-1]
        return f'Drawing v{self.version}'

    def __str__(self):
        target = self.bom_item or self.part
        return f'{self.display_title} v{self.version} — {target}'


class Machine(TenantScopedModel):
    """PLC-connected equipment at a work center."""

    PROTOCOL_OPCUA = 'opcua'
    PROTOCOL_MODBUS = 'modbus'
    PROTOCOL_MQTT = 'mqtt'
    PROTOCOL_CHOICES = [
        (PROTOCOL_OPCUA, 'OPC UA'),
        (PROTOCOL_MODBUS, 'Modbus'),
        (PROTOCOL_MQTT, 'MQTT'),
    ]

    name = models.CharField(max_length=120)
    work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.PROTECT,
        related_name='machines',
    )
    plc_endpoint = models.CharField(max_length=255, blank=True)
    protocol = models.CharField(max_length=20, choices=PROTOCOL_CHOICES, default=PROTOCOL_OPCUA)
    is_online = models.BooleanField(default=False)

    class Meta:
        ordering = ['work_center', 'name']

    def __str__(self):
        return self.name


class MachineSignal(models.Model):
    """Time-series signal from a machine (immutable)."""

    company = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.PROTECT,
        related_name='mes_machine_signals',
    )
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='signals')
    cycle_count = models.PositiveIntegerField(default=0)
    output_qty = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    downtime_reason = models.CharField(max_length=40, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('MachineSignal records are immutable.')
        super().save(*args, **kwargs)


class OEESnapshot(TenantScopedModel):
    """Rolled-up OEE metrics per machine for a period."""

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='oee_snapshots')
    availability = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    performance = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    quality = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    oee = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()

    class Meta:
        ordering = ['-period_end']
        indexes = [models.Index(fields=['company', 'machine', '-period_end'])]

    def __str__(self):
        return f'OEE {self.machine.name} @ {self.period_end:%Y-%m-%d %H:%M}'


class MaterialConsumption(TenantScopedModel):
    """Material issued to production — drives Oracle material sync."""

    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name='material_consumptions',
    )
    bom_item = models.ForeignKey(
        BOMItem,
        on_delete=models.PROTECT,
        related_name='material_consumptions',
    )
    qty_consumed = models.DecimalField(max_digits=12, decimal_places=3)
    oracle_posted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


class QCInspection(TenantScopedModel):
    """Quality inspection at a QC gate work center."""

    RESULT_PASS = 'pass'
    RESULT_FAIL = 'fail'
    RESULT_HOLD = 'hold'
    RESULT_CHOICES = [
        (RESULT_PASS, 'Pass'),
        (RESULT_FAIL, 'Fail'),
        (RESULT_HOLD, 'Hold'),
    ]

    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='qc_inspections')
    work_center = models.ForeignKey(
        WorkCenter,
        on_delete=models.PROTECT,
        related_name='qc_inspections',
    )
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mes_qc_inspections',
    )
    result = models.CharField(max_length=10, choices=RESULT_CHOICES)
    notes = models.TextField(blank=True)
    inspected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-inspected_at']


class NCR(TenantScopedModel):
    """Non-conformance report — rework loop tied to part barcode."""

    STATUS_OPEN = 'open'
    STATUS_REWORK = 'rework'
    STATUS_RELEASED = 'released'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_REWORK, 'Rework'),
        (STATUS_RELEASED, 'Released'),
        (STATUS_CLOSED, 'Closed'),
    ]

    inspection = models.ForeignKey(
        QCInspection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ncrs',
    )
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='ncrs')
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    on_hold = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'NCR'
        verbose_name_plural = 'NCRs'


class DispatchNote(TenantScopedModel):
    """Dispatch pack list — delivery confirmation pushed to Oracle."""

    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name='dispatch_notes',
    )
    note_number = models.CharField(max_length=50)
    delivery_confirmed = models.BooleanField(default=False)
    oracle_posted = models.BooleanField(default=False)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('company', 'note_number')]

    def __str__(self):
        return self.note_number


class OracleSyncLog(TenantScopedModel):
    """Bi-directional Oracle sync audit trail."""

    DIRECTION_IN = 'in'
    DIRECTION_OUT = 'out'
    DIRECTION_CHOICES = [
        (DIRECTION_IN, 'Inbound'),
        (DIRECTION_OUT, 'Outbound'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    entity = models.CharField(max_length=80)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Oracle sync log'
