"""
Contracts — customer-linked agreements with types, reminders, and attachments.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel
from apps.core.utils import generate_number
from apps.crm.models import Customer


class ContractType(BaseModel):
    """User-defined label (e.g. AMC, NDA, Service)."""
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, blank=True, db_index=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify

            self.slug = (slugify(self.name)[:130] or 'type')[:140]
        super().save(*args, **kwargs)


class Contract(BaseModel):
    """Commercial / legal contract record."""
    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    AMC_CATEGORY_CHOICES = [
        ('fire_alarm', 'Fire Alarm'),
        ('gas', 'Gas'),
        ('cctv', 'CCTV'),
        ('general_maintenance', 'General Maintenance'),
    ]

    contract_number = models.CharField(max_length=50, unique=True, editable=False)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        help_text='Lifecycle status (editable; can align with dates)',
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contracts',
    )
    salesperson = models.ForeignKey(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contracts',
        help_text='Salesperson responsible for this AMC (independent of customer assignment).',
    )
    amc_category = models.CharField(
        max_length=40,
        choices=AMC_CATEGORY_CHOICES,
        blank=True,
        help_text='AMC service category (Fire Alarm, Gas, CCTV, etc.).',
    )
    service_site = models.TextField(
        blank=True,
        help_text='Building, address, and emirate/area where AMC work is performed.',
    )
    name = models.CharField(max_length=255)
    contract_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    start_date = models.DateField()
    end_date = models.DateField()
    planned_visits = models.PositiveIntegerField(
        default=0,
        help_text='Number of planned PPM visits for this contract period.',
    )
    remind_before_days = models.PositiveIntegerField(
        default=30,
        help_text='Reminder this many days before end date',
    )
    description = models.TextField(blank=True)
    terms_and_conditions = models.TextField(
        blank=True,
        help_text='Printed on the contract PDF; defaults from Company Settings and can be edited per contract.',
    )
    contract_types = models.ManyToManyField(
        ContractType,
        blank=True,
        related_name='contracts',
    )
    source_estimate = models.ForeignKey(
        'sales.Estimate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='amc_contracts',
        help_text='Won quotation this AMC was created from.',
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='amc_contracts',
        help_text='Linked job / project for this AMC.',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.contract_number} — {self.name}'

    def save(self, *args, **kwargs):
        if not self.contract_number:
            self.contract_number = generate_number('CONTRACT', Contract, 'contract_number')
        super().save(*args, **kwargs)

    @property
    def as_of_date(self):
        return timezone.now().date()

    def is_active_on(self, d=None):
        d = d or self.as_of_date
        return self.start_date <= d <= self.end_date

    @property
    def is_expired(self):
        return self.end_date < self.as_of_date

    @property
    def is_currently_active(self):
        """True when today is within [start_date, end_date] (business sense; not the soft-delete flag)."""
        d = self.as_of_date
        return not self.is_expired and self.start_date <= d

    def is_expiring_within(self, days: int):
        """End date is in [today, today+days] inclusive."""
        today = self.as_of_date
        if self.end_date < today:
            return False
        return self.end_date <= today + timedelta(days=days)

    def reminder_due(self):
        """True if today is within remind_before_days before end (and not expired)."""
        today = self.as_of_date
        if self.end_date < today:
            return False
        warn_from = self.end_date - timedelta(days=self.remind_before_days)
        return today >= warn_from


class ContractPlannedVisit(BaseModel):
    """Explicit PPM visit date for an AMC contract (drives inspections and operations drafts)."""

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name='planned_visit_records',
    )
    visit_number = models.PositiveSmallIntegerField()
    visit_date = models.DateField()
    inspection = models.OneToOneField(
        'projects.Inspection',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='planned_visit',
    )
    duty_schedule = models.OneToOneField(
        'operations.StaffDutySchedule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='planned_visit',
    )

    class Meta:
        ordering = ['visit_number']
        constraints = [
            models.UniqueConstraint(
                fields=['contract', 'visit_number'],
                condition=models.Q(is_active=True),
                name='contracts_unique_active_planned_visit_number',
            ),
        ]
        verbose_name = 'Planned PPM visit'
        verbose_name_plural = 'Planned PPM visits'

    def __str__(self):
        return f'Visit {self.visit_number} — {self.contract.contract_number} ({self.visit_date:%d %b %Y})'


class ContractAttachment(BaseModel):
    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    file = models.FileField(upload_to='contracts/attachments/%Y/%m/')
    original_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.original_name or str(self.file)


class ContractDocumentExpiry(BaseModel):
    """Per-document expiry tracking with optional reminder lead time."""

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name='document_expiries',
    )
    document_name = models.CharField(max_length=200)
    expiry_date = models.DateField()
    remind_before_days = models.PositiveIntegerField(
        default=10,
        help_text='Reminder this many days before expiry date',
    )

    class Meta:
        ordering = ['expiry_date', 'document_name']
        verbose_name = 'Document expiry'
        verbose_name_plural = 'Document expiries'

    def __str__(self):
        return f'{self.document_name} ({self.expiry_date:%d %b %Y})'

    @property
    def as_of_date(self):
        return timezone.now().date()

    @property
    def days_until_expiry(self):
        return (self.expiry_date - self.as_of_date).days

    @property
    def is_expired(self):
        return self.expiry_date < self.as_of_date

    def reminder_due(self):
        today = self.as_of_date
        if self.expiry_date < today:
            return True
        warn_from = self.expiry_date - timedelta(days=self.remind_before_days)
        return today >= warn_from

    @property
    def expiry_status(self):
        """Badge severity: expired, due_today, expiring, ok."""
        days_left = self.days_until_expiry
        if days_left < 0:
            return 'expired'
        if days_left == 0:
            return 'due_today'
        if self.reminder_due():
            return 'expiring'
        return 'ok'
