"""
Core models and mixins used across all apps.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone


class TimeStampedModel(models.Model):
    """
    Abstract base model with created_at and updated_at fields.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserTrackingModel(models.Model):
    """
    Abstract base model with created_by and updated_by fields.
    """
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_updated'
    )

    class Meta:
        abstract = True


class ActiveModel(models.Model):
    """
    Abstract base model with is_active field.
    """
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class BaseModel(TimeStampedModel, UserTrackingModel, ActiveModel):
    """
    Base model combining all common fields.
    Every model in the ERP should inherit from this.
    
    Fields:
    - created_at
    - updated_at
    - created_by
    - updated_by
    - is_active
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Get the current user from thread local storage
        from apps.core.middleware import get_current_user
        user = get_current_user()
        
        if not self.pk:
            # New record
            if user and user.is_authenticated:
                self.created_by = user
        
        if user and user.is_authenticated:
            self.updated_by = user
            
        super().save(*args, **kwargs)


class AiModuleKnowledge(models.Model):
    """Compliance / knowledge graph text per ERP module for AI evaluation prompts."""

    MODULE_PURCHASE_REQUEST = 'purchase_request'
    MODULE_PURCHASE_ORDER = 'purchase_order'
    MODULE_ESTIMATE = 'estimate'
    MODULE_PROJECT = 'project'
    MODULE_EMPLOYEE = 'employee'

    MODULE_CHOICES = [
        (MODULE_PURCHASE_REQUEST, 'Purchase request'),
        (MODULE_PURCHASE_ORDER, 'Purchase order'),
        (MODULE_ESTIMATE, 'Quotation / estimate'),
        (MODULE_PROJECT, 'Project'),
        (MODULE_EMPLOYEE, 'Employee'),
    ]

    module = models.CharField(max_length=40, choices=MODULE_CHOICES, unique=True)
    content = models.TextField(
        blank=True,
        help_text='Rules, compliance notes, and knowledge graph text for AI reviewers.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'AI module knowledge'
        verbose_name_plural = 'AI module knowledge'
        ordering = ['module']

    def __str__(self):
        return dict(self.MODULE_CHOICES).get(self.module, self.module)


class AiComplianceSettings(models.Model):
    """Global toggles for AI compliance behaviour (edited at /ajas/)."""

    auto_run_enabled = models.BooleanField(
        default=True,
        help_text='When enabled, compliance AI runs automatically in the background after a detail page loads.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'AI compliance settings'
        verbose_name_plural = 'AI compliance settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return 'AI compliance settings'

