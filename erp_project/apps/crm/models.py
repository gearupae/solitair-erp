"""
CRM Models - Customer/Lead Management
"""
from decimal import Decimal
from django.db import models
from apps.core.models import BaseModel
from apps.core.utils import generate_number


class Customer(BaseModel):
    """
    Customer/Lead model for CRM module.
    """
    CUSTOMER_TYPE_CHOICES = [
        ('lead', 'Lead'),
        ('customer', 'Customer'),
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
    
    customer_number = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200)
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
    job_type = models.CharField(max_length=120, blank=True)
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
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'
    
    def __str__(self):
        return f"{self.customer_number} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.customer_number:
            self.customer_number = generate_number('CUSTOMER', Customer, 'customer_number')
        super().save(*args, **kwargs)
    
    @property
    def display_name(self):
        """Return company name if available, otherwise contact name."""
        return self.company if self.company else self.name

    @property
    def scope_display_labels(self):
        """Labels for selected scope codes (FF, FA, EM, FLS, MEP)."""
        if not self.scope:
            return []
        labels = dict(self.SCOPE_CHOICES)
        return [labels.get(code, code) for code in self.scope]


