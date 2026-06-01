"""
CRM Models - Customer/Lead Management
"""
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from apps.core.models import BaseModel
from apps.core.utils import generate_number


class CrmLeadKanbanStage(models.Model):
    """
    Configurable lead pipeline columns (Settings → CRM Kanban).
    Exactly one stage may have converts_to_customer=True (Won).
    """

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, unique=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True)
    converts_to_customer = models.BooleanField(
        default=False,
        help_text='If checked, leads dropped in the “Won” zone become customers.',
    )

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'CRM lead kanban stage'
        verbose_name_plural = 'CRM lead kanban stages'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not (self.slug or '').strip():
            self.slug = slugify(self.name)[:80] or 'stage'
        if self.converts_to_customer:
            CrmLeadKanbanStage.objects.exclude(pk=self.pk).update(converts_to_customer=False)
        super().save(*args, **kwargs)


class Customer(BaseModel):
    """
    Customer/Lead model for CRM module.
    """
    CUSTOMER_TYPE_CHOICES = [
        ('lead', 'Lead'),
        ('customer', 'Customer'),
    ]

    BUSINESS_SEGMENT_CHOICES = [
        ('', '—'),
        ('b2b', 'B2B'),
        ('b2c', 'B2C'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('prospect', 'Prospect'),
    ]

    SCOPE_CHOICES = [
        ('ff', 'FF'),
        ('fa', 'FA'),
        ('em', 'EM'),
        ('fls', 'FLS'),
        ('mep', 'MEP'),
    ]

    JOB_TYPE_CHOICES = [
        ('', '—'),
        ('amc', 'AMC'),
        ('project', 'Project'),
        ('direct_sale', 'Direct Sale'),
        ('maintenance', 'Maintenance'),
    ]
    
    customer_number = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200, blank=True, default='')
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='United Arab Emirates')
    trn = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='VAT (TRN)',
        help_text='Tax registration / VAT number for B2B invoices',
    )
    website = models.URLField(blank=True, max_length=500)
    scope = models.JSONField(default=list, blank=True, help_text='Disciplines: FF, FA, EM, FLS, MEP')
    job_type = models.CharField(
        max_length=20,
        blank=True,
        default='',
        choices=JOB_TYPE_CHOICES,
        verbose_name='Job type',
    )
    primary_project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='primary_for_customers',
        verbose_name='Project',
    )
    payment_terms = models.CharField(max_length=50, blank=True, default='Net 30')
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE_CHOICES, default='lead')
    lead_kanban_stage = models.ForeignKey(
        CrmLeadKanbanStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leads',
        limit_choices_to={'converts_to_customer': False},
        help_text='Pipeline column for leads (customers do not use this).',
    )
    assigned_salesperson = models.ForeignKey(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_crm_leads',
        verbose_name='Assigned salesman',
        help_text='Sales employee responsible for this lead or customer.',
    )
    business_segment = models.CharField(
        max_length=10,
        blank=True,
        default='',
        choices=BUSINESS_SEGMENT_CHOICES,
        verbose_name='Business type',
        help_text='Required for accounts with type Customer: B2B or B2C.',
    )
    trn_document = models.FileField(
        upload_to='crm/customer_documents/%Y/%m/',
        blank=True,
        max_length=500,
        verbose_name='TRN document',
        help_text='Optional. VAT/TRN certificate (PDF or image) for B2B.',
    )
    trade_license_document = models.FileField(
        upload_to='crm/customer_documents/%Y/%m/',
        blank=True,
        max_length=500,
        verbose_name='Trade license',
        help_text='B2B: upload trade license (PDF or image).',
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'
    
    def __str__(self):
        label = self.display_name or self.customer_number
        return f"{self.customer_number} - {label}"
    
    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if self.customer_type == 'customer':
            self.lead_kanban_stage = None
        elif is_new and self.customer_type == 'lead' and self.lead_kanban_stage_id is None:
            first = (
                CrmLeadKanbanStage.objects.filter(
                    is_active=True,
                    converts_to_customer=False,
                )
                .order_by('sort_order', 'id')
                .first()
            )
            if first:
                self.lead_kanban_stage = first
        if not self.customer_number:
            self.customer_number = generate_number('CUSTOMER', Customer, 'customer_number')
        super().save(*args, **kwargs)
    
    @property
    def display_name(self):
        """Return company name if available, otherwise contact name."""
        return self.company if self.company else self.name

    @property
    def public_upload_option_label(self):
        """Number + contact name (+ company when different) for public pickers."""
        primary = (self.name or self.company or '').strip()
        base = f'{self.customer_number} — {primary}'
        company = (self.company or '').strip()
        name = (self.name or '').strip()
        if company and name and company.casefold() != name.casefold():
            return f'{base} · {company}'
        return base

    @property
    def scope_display_labels(self):
        """Labels for selected scope codes (FF, FA, EM, FLS, MEP)."""
        if not self.scope:
            return []
        labels = dict(self.SCOPE_CHOICES)
        return [labels.get(code, code) for code in self.scope]

    @property
    def assigned_salesman_label(self):
        if not self.assigned_salesperson_id:
            return ''
        from apps.crm.utils import salesperson_display_name
        return salesperson_display_name(self.assigned_salesperson)


class CustomerPublicUpload(BaseModel):
    """
    File uploaded via the anonymous CRM public form.
    Shown on the customer/lead detail page for staff.
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='public_uploads',
    )
    file = models.FileField(upload_to='crm_public/%Y/%m/', max_length=500)
    original_filename = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.customer.customer_number}: {self.original_filename or self.file.name}'

    @property
    def is_probably_image(self):
        name = (self.original_filename or self.file.name or '').lower()
        return name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif'))
