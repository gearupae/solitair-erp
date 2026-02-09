"""Documents Models - Document Expiry Tracking"""
from django.db import models
from django.conf import settings
from datetime import date
from apps.core.models import BaseModel


class DocumentType(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    alert_days_before = models.PositiveIntegerField(default=30)  # Days before expiry to alert
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Document(BaseModel):
    ENTITY_CHOICES = [
        ('company', 'Company'),
        ('employee', 'Employee'),
        ('vendor', 'Vendor'),
        ('customer', 'Customer'),
        ('vehicle', 'Vehicle'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('expiring', 'Expiring Soon'),
    ]
    
    document_type = models.ForeignKey(DocumentType, on_delete=models.CASCADE, related_name='documents')
    entity_type = models.CharField(max_length=20, choices=ENTITY_CHOICES)
    entity_name = models.CharField(max_length=200)  # Name of employee, vendor, etc.
    entity_id = models.PositiveIntegerField(null=True, blank=True)  # FK to related entity
    document_number = models.CharField(max_length=100, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    notes = models.TextField(blank=True)
    file = models.FileField(upload_to='documents/', null=True, blank=True)
    
    class Meta:
        ordering = ['expiry_date']
    
    def __str__(self):
        return f"{self.document_type.name} - {self.entity_name}"
    
    @property
    def days_until_expiry(self):
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return None
    
    @property
    def status(self):
        days = self.days_until_expiry
        if days is None:
            return 'active'
        if days < 0:
            return 'expired'
        if days <= self.document_type.alert_days_before:
            return 'expiring'
        return 'active'
    
    @property
    def is_expired(self):
        return self.status == 'expired'
    
    @property
    def is_expiring_soon(self):
        return self.status == 'expiring'





