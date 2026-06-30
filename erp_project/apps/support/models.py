"""
Support ticket models — customer / project / AMC linked tickets with kanban pipeline.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.core.models import BaseModel
from apps.core.utils import generate_number
from apps.crm.models import Customer
from apps.hr.models import Employee
from apps.projects.models import Project
from apps.contracts.models import Contract


class SupportTicketKanbanStage(models.Model):
    """Configurable support pipeline columns (Settings → Support pipeline)."""

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, unique=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True)
    is_closed = models.BooleanField(
        default=False,
        help_text='If checked, tickets in this column are treated as closed/resolved.',
    )

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Support kanban stage'
        verbose_name_plural = 'Support kanban stages'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not (self.slug or '').strip():
            self.slug = slugify(self.name)[:80] or 'stage'
        if self.is_closed:
            SupportTicketKanbanStage.objects.exclude(pk=self.pk).update(is_closed=False)
        super().save(*args, **kwargs)


class SupportTicket(BaseModel):
    """Customer support ticket linked to a customer, project, or AMC contract."""

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    LINK_TYPE_CHOICES = [
        ('customer', 'Customer'),
        ('project', 'Project'),
        ('amc', 'AMC'),
        ('unlinked', 'General'),
    ]

    ticket_number = models.CharField(max_length=50, unique=True, editable=False)
    subject = models.CharField(max_length=255)
    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES, default='customer')
    submitted_via_public = models.BooleanField(default=False)
    requester_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Name or company entered on the public support form.',
    )
    requester_email = models.EmailField(blank=True)
    requester_phone = models.CharField(max_length=40, blank=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets',
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets',
    )
    amc_contract = models.ForeignKey(
        Contract,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets',
        verbose_name='AMC contract',
    )
    opened_date = models.DateField()
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    assigned_to = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_tickets',
    )
    description = models.TextField(blank=True)
    kanban_stage = models.ForeignKey(
        SupportTicketKanbanStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
    )

    class Meta:
        ordering = ['-opened_date', '-created_at']

    def __str__(self):
        return f'{self.ticket_number} — {self.subject}'

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            year = self.opened_date.year if self.opened_date else None
            self.ticket_number = generate_number(
                'SUPPORT_TICKET',
                SupportTicket,
                number_field='ticket_number',
                year=year,
            )
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if self.submitted_via_public:
            if not (self.requester_name or '').strip():
                errors['requester_name'] = 'Enter your name or company.'
            has_link = (
                (self.link_type == 'customer' and self.customer_id)
                or (self.link_type == 'project' and self.project_id)
                or (self.link_type == 'amc' and self.amc_contract_id)
            )
            if has_link:
                if self.link_type == 'customer':
                    self.project = None
                    self.amc_contract = None
                elif self.link_type == 'project':
                    self.customer = None
                    self.amc_contract = None
                elif self.link_type == 'amc':
                    self.customer = None
                    self.project = None
            elif self.link_type != 'unlinked':
                self.link_type = 'unlinked'
                self.customer = None
                self.project = None
                self.amc_contract = None
            if errors:
                raise ValidationError(errors)
            return

        if self.link_type == 'customer':
            if not self.customer_id:
                errors['customer'] = 'Select a customer.'
            self.project = None
            self.amc_contract = None
        elif self.link_type == 'project':
            if not self.project_id:
                errors['project'] = 'Select a project.'
            self.customer = None
            self.amc_contract = None
        elif self.link_type == 'amc':
            if not self.amc_contract_id:
                errors['amc_contract'] = 'Select an AMC contract.'
            self.customer = None
            self.project = None
        elif self.link_type == 'unlinked':
            self.customer = None
            self.project = None
            self.amc_contract = None
        if errors:
            raise ValidationError(errors)

    @property
    def link_label(self):
        if self.link_type == 'customer' and self.customer_id:
            return self.customer.name
        if self.link_type == 'project' and self.project_id:
            return f'{self.project.project_code} — {self.project.name}'
        if self.link_type == 'amc' and self.amc_contract_id:
            return f'{self.amc_contract.contract_number} — {self.amc_contract.name}'
        if self.link_type == 'unlinked' and self.requester_name:
            return self.requester_name
        return '—'

    @property
    def related_customer(self):
        if self.link_type == 'customer' and self.customer_id:
            return self.customer
        if self.link_type == 'project' and self.project_id and self.project.customer_id:
            return self.project.customer
        if self.link_type == 'amc' and self.amc_contract_id and self.amc_contract.customer_id:
            return self.amc_contract.customer
        return None
