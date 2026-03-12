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
        ('service_request', 'Service Request'),
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
    Approval workflow configuration (legacy - use ApprovalConfiguration for new modules).
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


# ============ APPROVAL CONFIGURATION ============

class ApprovalConfiguration(BaseModel):
    """
    Configures who approves what for each request module.
    Supports Single Level (one approver) or Multi Level (sequential by amount).
    """
    APPROVAL_TYPE_CHOICES = [
        ('single', 'Single Level'),
        ('multi', 'Multi Level'),
    ]
    
    MODULE_CHOICES = [
        ('purchase_request', 'Purchase Request'),
        ('inventory_request', 'Consumable / Inventory Request'),
        ('service_request', 'Service Request'),
    ]
    
    module = models.CharField(max_length=50, choices=MODULE_CHOICES, unique=True)
    approval_type = models.CharField(max_length=20, choices=APPROVAL_TYPE_CHOICES, default='single')
    
    # Single level: one approver
    default_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approval_configs_single'
    )
    
    # If no config, use first superuser as fallback
    @classmethod
    def get_approver_for_amount(cls, module, amount):
        """
        Get the approver for a given module and amount (AED).
        For single level: returns default_approver.
        For multi level: returns approver for the matching amount threshold.
        """
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        config = cls.objects.filter(module=module, is_active=True).first()
        if not config:
            # Default: first active superuser
            return User.objects.filter(is_superuser=True, is_active=True).first()
        
        if config.approval_type == 'single':
            return config.default_approver or User.objects.filter(is_superuser=True, is_active=True).first()
        
        # Multi level: find matching level (levels ordered by amount ascending)
        level = config.levels.filter(is_active=True).order_by('amount_threshold').filter(
            amount_threshold__gte=amount
        ).first()
        if not level:
            # Amount exceeds all levels - use highest level's approver
            level = config.levels.filter(is_active=True).order_by('-amount_threshold').first()
        return level.approver if level else config.default_approver
    
    @classmethod
    def notify_approver(cls, request_obj, module):
        """Create in-app notification for approver when action is needed."""
        amount = getattr(request_obj, 'total_amount', 0) or getattr(request_obj, 'total_cost', 0) or 0
        approver = cls.get_approver_for_amount(module, amount)
        if approver:
            ref = getattr(request_obj, 'sr_number', None) or getattr(request_obj, 'pr_number', None) or getattr(request_obj, 'request_number', None) or str(request_obj.pk)
            pk = getattr(request_obj, 'pk', None)
            link_map = {
                'service_request': f'/service-request/{pk}/' if pk else '',
                'purchase_request': f'/purchase/requests/{pk}/' if pk else '',
                'inventory_request': f'/inventory/consumables/{pk}/' if pk else '',
            }
            link = link_map.get(module, str(pk) if pk else '')
            Notification.create(
                user=approver,
                title=f'Approval Required: {module.replace("_", " ").title()}',
                message=f'{ref} requires your approval. Amount: AED {amount:,.2f}',
                link=link,
            )


class ApprovalConfigurationLevel(models.Model):
    """
    Multi-level approval: amount threshold (AED) and approver.
    Levels are evaluated in order of amount_threshold ascending.
    """
    configuration = models.ForeignKey(
        ApprovalConfiguration,
        on_delete=models.CASCADE,
        related_name='levels'
    )
    amount_threshold = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text='Amount up to (AED) - requests at or below this go to this approver'
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approval_config_levels'
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['order', 'amount_threshold']
    
    def __str__(self):
        return f"Up to AED {self.amount_threshold} → {self.approver}"


class ApprovalAuditLog(models.Model):
    """
    Full audit trail: approver name, action, timestamp, comment.
    """
    ACTION_CHOICES = [
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ('return', 'Returned for Revision'),
    ]
    
    module = models.CharField(max_length=50)
    reference = models.CharField(max_length=100)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='approval_audit_logs'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    comment = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.reference} - {self.get_action_display()} by {self.approver}"


class Notification(models.Model):
    """In-app notification for users."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    @classmethod
    def create(cls, user, title, message, link=None):
        if link and not isinstance(link, str):
            link = str(link)
        return cls.objects.create(user=user, title=title, message=message, link=link or '')

