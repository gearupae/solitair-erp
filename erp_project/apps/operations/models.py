"""
Operations — staff duty scheduling for projects and AMC contracts.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.contracts.models import Contract
from apps.core.models import BaseModel
from apps.hr.models import Employee
from apps.projects.models import Project


class OperationsSettings(models.Model):
    """Singleton settings for the operations module (public schedule link token)."""

    public_schedule_token = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        verbose_name = 'Operations settings'
        verbose_name_plural = 'Operations settings'

    def __str__(self):
        return 'Operations settings'


class StaffDutySchedule(BaseModel):
    """One staff member assigned to a project or AMC on a specific date and time."""

    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('paused', 'Paused'),
        ('cancelled', 'Cancelled'),
    ]

    LINK_TYPE_CHOICES = [
        ('project', 'Project'),
        ('amc', 'AMC'),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='duty_schedules',
    )
    duty_date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES, default='project')
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_duty_schedules',
    )
    amc_contract = models.ForeignKey(
        Contract,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_duty_schedules',
        verbose_name='AMC contract',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled', db_index=True)
    location = models.CharField(max_length=255, blank=True)
    contact_person_name = models.CharField(max_length=255, blank=True, verbose_name='Contact person')
    contact_person_phone = models.CharField(max_length=40, blank=True, verbose_name='Contact phone')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-duty_date', 'start_time', 'employee__first_name']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'duty_date'],
                condition=Q(status='scheduled', is_active=True),
                name='operations_unique_scheduled_duty_per_day',
            ),
        ]
        verbose_name = 'Staff duty schedule'
        verbose_name_plural = 'Staff duty schedules'

    def __str__(self):
        return f'{self.employee} — {self.duty_date} ({self.get_status_display()})'

    def clean(self):
        errors = {}
        if self.link_type == 'project':
            if not self.project_id:
                errors['project'] = 'Select a project.'
            self.amc_contract = None
        elif self.link_type == 'amc':
            if not self.amc_contract_id:
                errors['amc_contract'] = 'Select an AMC contract.'
            self.project = None

        if self.end_time and self.start_time and self.end_time <= self.start_time:
            errors['end_time'] = 'End time must be after start time.'

        if self.status == 'scheduled' and self.employee_id and self.duty_date:
            conflict = (
                StaffDutySchedule.objects.filter(
                    is_active=True,
                    status='scheduled',
                    employee_id=self.employee_id,
                    duty_date=self.duty_date,
                )
                .exclude(pk=self.pk)
                .select_related('project', 'amc_contract')
                .first()
            )
            if conflict:
                errors['employee'] = (
                    f'Already scheduled on this date for {conflict.target_label}. '
                    'Pause or cancel the existing assignment first.'
                )

        if errors:
            raise ValidationError(errors)

    @property
    def target_label(self):
        if self.link_type == 'project' and self.project_id:
            return f'Project {self.project.project_code} — {self.project.name}'
        if self.link_type == 'amc' and self.amc_contract_id:
            return f'AMC {self.amc_contract.contract_number} — {self.amc_contract.name}'
        return '—'

    @property
    def time_display(self):
        if self.end_time:
            return f'{self.start_time:%H:%M} – {self.end_time:%H:%M}'
        return f'{self.start_time:%H:%M}'

    @property
    def location_maps_url(self):
        from .utils import location_maps_url

        return location_maps_url(self.location)

    @property
    def contact_phone_tel_href(self):
        from .utils import phone_tel_href

        return phone_tel_href(self.contact_person_phone)
