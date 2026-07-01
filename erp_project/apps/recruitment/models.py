"""Recruitment — positions, hiring requests, candidates."""
from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Position(BaseModel):
    title = models.CharField(max_length=200)
    department = models.ForeignKey(
        'hr.Department',
        on_delete=models.PROTECT,
        related_name='recruitment_positions',
    )

    class Meta:
        ordering = ['title']

    def __str__(self):
        return f'{self.title} ({self.department.name})'


class RecruitmentRequest(BaseModel):
    STATUS_PENDING = 'pending'
    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Approval'),
        (STATUS_OPEN, 'Open'),
        (STATUS_CLOSED, 'Closed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name='requests',
    )
    openings = models.PositiveIntegerField(default=1)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recruitment_requests_made',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recruitment_requests_approved',
        help_text='Set automatically when approved via Settings → Approval Configuration.',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.position.title} · {self.openings} opening(s) · {self.get_status_display()}'

    @property
    def display_reference(self) -> str:
        return f'{self.position.title} · {self.openings} opening(s)'


class Candidate(BaseModel):
    STATUS_NEW = 'new'
    STATUS_SCREENING = 'screening'
    STATUS_INTERVIEW = 'interview'
    STATUS_OFFER = 'offer'
    STATUS_HIRED = 'hired'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_NEW, 'New'),
        (STATUS_SCREENING, 'Screening'),
        (STATUS_INTERVIEW, 'Interview'),
        (STATUS_OFFER, 'Offer'),
        (STATUS_HIRED, 'Hired'),
        (STATUS_REJECTED, 'Rejected'),
    ]
    KANBAN_STATUSES = (
        STATUS_NEW,
        STATUS_SCREENING,
        STATUS_INTERVIEW,
        STATUS_OFFER,
        STATUS_HIRED,
        STATUS_REJECTED,
    )

    SOURCE_REFERRAL = 'referral'
    SOURCE_LINKEDIN = 'linkedin'
    SOURCE_WALKIN = 'walkin'
    SOURCE_OTHER = 'other'
    SOURCE_CHOICES = [
        (SOURCE_REFERRAL, 'Referral'),
        (SOURCE_LINKEDIN, 'LinkedIn'),
        (SOURCE_WALKIN, 'Walk-in'),
        (SOURCE_OTHER, 'Other'),
    ]

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    position_applied = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name='candidates',
    )
    resume = models.FileField(upload_to='recruitment/resumes/%Y/%m/', blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_OTHER)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    applied_date = models.DateField()
    converted_employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recruitment_candidates',
    )
    conversion_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-applied_date', '-created_at']

    def __str__(self):
        return self.name

    @property
    def is_locked(self) -> bool:
        return self.converted_employee_id is not None

    def split_name(self) -> tuple[str, str]:
        parts = (self.name or '').strip().split(None, 1)
        if not parts:
            return '', ''
        if len(parts) == 1:
            return parts[0], ''
        return parts[0], parts[1]
