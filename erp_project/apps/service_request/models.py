"""
Service Request models.
External vendor services: maintenance, IT support, transport, manpower, facility work.
"""
from django.db import models
from django.conf import settings
from decimal import Decimal
from apps.core.models import BaseModel
from apps.core.utils import generate_number


class ServiceRequest(BaseModel):
    """
    Service Request - raised when a department needs an external vendor to perform a service.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('returned', 'Returned for Revision'),
        ('converted', 'Converted to Service Order'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    sr_number = models.CharField(max_length=50, unique=True, editable=False)
    date = models.DateField()
    required_by_date = models.DateField(null=True, blank=True)
    department = models.ForeignKey(
        'hr.Department',
        on_delete=models.PROTECT,
        related_name='service_requests',
        null=True,
        blank=True
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='service_requests'
    )
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True, help_text='Notes / Justification')
    
    # Calculated
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Rejection/return comments
    rejection_reason = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.sr_number
    
    def save(self, *args, **kwargs):
        if not self.sr_number:
            self.sr_number = generate_number('SERVICE_REQUEST', ServiceRequest, 'sr_number')
        super().save(*args, **kwargs)
    
    def calculate_total(self):
        self.total_amount = sum(item.total_cost for item in self.items.all())
        self.save(update_fields=['total_amount'])


class ServiceRequestItem(models.Model):
    """
    Line items for service requests.
    """
    UNIT_CHOICES = [
        ('hours', 'Hours'),
        ('days', 'Days'),
        ('visit', 'Visit'),
        ('lumpsum', 'Lumpsum'),
    ]
    
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name='items'
    )
    service_description = models.CharField(max_length=500)
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_request_items',
        help_text='Optional at request stage'
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='hours')
    estimated_unit_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['id']
    
    def save(self, *args, **kwargs):
        self.total_cost = (self.quantity * self.estimated_unit_cost).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class ServiceRequestAttachment(models.Model):
    """Attachments for service requests."""
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    file = models.FileField(upload_to='service_request_attachments/%Y/%m/')
    filename = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    class Meta:
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return self.filename or self.file.name


class ServiceOrder(BaseModel):
    """
    Service Order - created when procurement converts an approved Service Request.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    so_number = models.CharField(max_length=50, unique=True, editable=False)
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.PROTECT,
        related_name='service_orders'
    )
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.PROTECT,
        related_name='service_orders'
    )
    order_date = models.DateField()
    expected_completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.so_number} - {self.vendor.name}"
    
    def save(self, *args, **kwargs):
        if not self.so_number:
            self.so_number = generate_number('SERVICE_ORDER', ServiceOrder, 'so_number')
        super().save(*args, **kwargs)
