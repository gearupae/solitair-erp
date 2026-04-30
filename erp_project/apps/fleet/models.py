from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Vehicle(BaseModel):
    """Company vehicle with registration and document expiries."""

    plate_number = models.CharField(max_length=50, blank=True, help_text='Plate / fleet ID')
    make = models.CharField(max_length=120)
    model = models.CharField(max_length=120)
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fleet_vehicles_driven',
    )
    mulkiya_expiry = models.DateField(null=True, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['make', 'model', 'plate_number']

    def __str__(self):
        bits = [self.plate_number, self.make, self.model]
        return ' '.join(b for b in bits if b).strip() or f'Vehicle #{self.pk}'


class VehicleOtherDocument(BaseModel):
    """Additional vehicle document with free-form name and expiry."""

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name='other_documents',
    )
    document_name = models.CharField(max_length=200)
    expiry_date = models.DateField()

    class Meta:
        ordering = ['expiry_date', 'document_name']

    def __str__(self):
        return f'{self.document_name} ({self.vehicle})'
