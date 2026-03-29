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
    name = models.CharField(max_length=255)
    contract_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    start_date = models.DateField()
    end_date = models.DateField()
    remind_before_days = models.PositiveIntegerField(
        default=10,
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
