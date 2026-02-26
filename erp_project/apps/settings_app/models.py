"""
Settings app models - Users, Roles, Permissions, Company Settings.
"""
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from apps.core.models import BaseModel, TimeStampedModel


class Role(BaseModel):
    """
    User roles for the system.
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    is_system_role = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Permission(models.Model):
    """
    System permissions (legacy - kept for backwards compatibility).
    """
    MODULE_CHOICES = [
        ('crm', 'CRM'),
        ('sales', 'Sales'),
        ('purchase', 'Purchase'),
        ('inventory', 'Inventory'),
        ('finance', 'Finance'),
        ('projects', 'Projects'),
        ('hr', 'HR'),
        ('documents', 'Documents'),
        ('assets', 'Fixed Assets'),
        ('property', 'Property Management'),
        ('settings', 'Settings'),
    ]
    
    PERMISSION_TYPE_CHOICES = [
        ('view', 'View'),
        ('create', 'Create'),
        ('edit', 'Edit'),
        ('delete', 'Delete'),
        ('approve', 'Approve'),
    ]
    
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100, unique=True)
    permission_type = models.CharField(max_length=20, choices=PERMISSION_TYPE_CHOICES)
    
    class Meta:
        ordering = ['module', 'name']
        unique_together = ['module', 'permission_type']
    
    def __str__(self):
        return f"{self.get_module_display()} - {self.name}"


class RolePermission(models.Model):
    """
    Links roles to permissions with specific access levels (legacy).
    """
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_permissions')
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='role_permissions')
    can_create = models.BooleanField(default=False)
    can_read = models.BooleanField(default=True)
    can_update = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    
    # Alias for backward compatibility
    @property
    def can_view(self):
        return self.can_read
    
    class Meta:
        unique_together = ['role', 'permission']
    
    def __str__(self):
        return f"{self.role.name} - {self.permission.name}"


class ModulePermission(models.Model):
    """
    Simplified module-level permissions for roles.
    Each role can have specific permissions (view, create, edit, delete) per module.
    """
    MODULE_CHOICES = [
        ('crm', 'CRM'),
        ('sales', 'Sales'),
        ('purchase', 'Purchase'),
        ('inventory', 'Inventory'),
        ('finance', 'Finance'),
        ('projects', 'Projects'),
        ('hr', 'HR'),
        ('documents', 'Documents'),
        ('assets', 'Fixed Assets'),
        ('property', 'Property Management'),
        ('settings', 'Settings'),
    ]
    
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='module_permissions')
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    can_view = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ['role', 'module']
        ordering = ['role', 'module']
    
    def __str__(self):
        return f"{self.role.name} - {self.get_module_display()}"
    
    @classmethod
    def get_modules(cls):
        """Return all available modules."""
        return cls.MODULE_CHOICES


class UserRole(BaseModel):
    """
    Links users to roles.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_roles')
    assigned_date = models.DateField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'role']
    
    def __str__(self):
        return f"{self.user.username} - {self.role.name}"


class UserProfile(BaseModel):
    """
    Extended user profile information.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    timezone = models.CharField(max_length=50, default='Asia/Dubai')
    preferred_language = models.CharField(max_length=10, default='en')
    
    def __str__(self):
        return f"{self.user.username}'s Profile"


class CompanySettings(models.Model):
    """
    Company-wide settings and information.
    """
    company_name = models.CharField(max_length=200)
    logo = models.ImageField(upload_to='company/', blank=True, null=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    tax_id = models.CharField(max_length=50, blank=True, verbose_name='Tax ID / TRN')
    fiscal_year_start = models.IntegerField(default=1, help_text='Month (1-12)')
    currency = models.CharField(max_length=10, default='AED')
    date_format = models.CharField(max_length=20, default='%d/%m/%Y')
    timezone = models.CharField(max_length=50, default='Asia/Dubai')
    
    class Meta:
        verbose_name = 'Company Settings'
        verbose_name_plural = 'Company Settings'
    
    def __str__(self):
        return self.company_name
    
    @classmethod
    def get_settings(cls):
        """Get or create company settings."""
        settings, _ = cls.objects.get_or_create(pk=1, defaults={'company_name': 'My Company'})
        return settings


class NumberSeries(models.Model):
    """
    Document number series configuration.
    """
    document_type = models.CharField(max_length=50, unique=True)
    prefix = models.CharField(max_length=20)
    next_number = models.IntegerField(default=1)
    padding = models.IntegerField(default=4)
    
    class Meta:
        verbose_name_plural = 'Number Series'
    
    def __str__(self):
        return f"{self.document_type}: {self.prefix}"
    
    def get_next_number(self):
        """Generate and return the next number in the series."""
        from datetime import datetime
        year = datetime.now().year
        number = f"{self.prefix}-{year}-{str(self.next_number).zfill(self.padding)}"
        self.next_number += 1
        self.save(update_fields=['next_number'])
        return number


class AuditLog(models.Model):
    """
    System audit log for tracking all changes.
    UAE VAT & Corporate Tax compliant audit trail.
    """
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('view', 'View'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('post', 'Post'),
        ('post_bypass', 'Post (Closed Period Bypass)'),
        ('reverse', 'Reverse'),
        ('approve', 'Approve'),
        ('reject', 'Reject'),
        ('reconcile', 'Reconcile'),
        ('import', 'Import'),
        ('export', 'Export'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model = models.CharField(max_length=100)
    record_id = models.CharField(max_length=50, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.user} - {self.action} - {self.model}"


class ApprovalWorkflow(BaseModel):
    """
    Approval workflow configuration.
    """
    MODULE_CHOICES = [
        ('purchase_request', 'Purchase Request'),
    ]
    
    module = models.CharField(max_length=50, choices=MODULE_CHOICES, unique=True)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='approval_workflows'
    )
    auto_approve = models.BooleanField(default=True, help_text='Auto approve if no approver set')
    
    def __str__(self):
        return f"{self.get_module_display()} - {self.approver or 'Auto Approve'}"

