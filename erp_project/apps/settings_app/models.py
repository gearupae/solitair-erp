"""
Settings app models - Users, Roles, Permissions, Company Settings.
"""
from decimal import Decimal

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
        ('contracts', 'Contracts'),
        ('support', 'Support'),
        ('fleet', 'Fleet'),
        ('reports', 'Reports'),
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
        ('contracts', 'Contracts'),
        ('support', 'Support'),
        ('fleet', 'Fleet'),
        ('reports', 'Reports'),
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


class Company(BaseModel):
    """
    Legal entity / employing company (employees reference this; distinct from singleton Company Settings).
    """

    COUNTRY_CHOICES = [
        ('uae', 'UAE'),
        ('ksa', 'KSA'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=200)
    trade_license_number = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=10, choices=COUNTRY_CHOICES, default='uae')
    mol_number = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='MOL number',
        help_text='UAE Ministry of Labour employer registration (WPS SCR).',
    )
    bank_iban = models.CharField(max_length=34, blank=True, help_text='Company bank IBAN (WPS SCR).')
    bank_routing_code = models.CharField(
        max_length=20,
        blank=True,
        help_text='Company bank routing / agent ID (WPS SCR).',
    )
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to='company_entities/', blank=True, null=True)
    trn = models.CharField(max_length=20, blank=True, verbose_name='Tax Registration Number (TRN)')
    base_currency = models.CharField(max_length=10, default='AED')
    intercompany_receivable_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='legal_entities_interco_recv',
    )
    intercompany_payable_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='legal_entities_interco_pay',
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Companies'

    def __str__(self):
        return self.name


class CompanySettings(models.Model):
    """
    Company-wide settings and information.
    """
    company_name = models.CharField(max_length=200)
    logo = models.ImageField(upload_to='company/', blank=True, null=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    smtp_host = models.CharField(
        max_length=200,
        blank=True,
        help_text='SMTP server (e.g. smtp.office365.com). Leave blank to use server default email settings.',
    )
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=200, blank=True)
    smtp_password = models.CharField(
        max_length=200,
        blank=True,
        help_text='SMTP password. Leave blank when saving to keep the existing password.',
    )
    smtp_use_tls = models.BooleanField(default=True)
    smtp_from_email = models.EmailField(
        blank=True,
        help_text='From address for outbound mail. If empty, Company email is used.',
    )
    website = models.URLField(blank=True, help_text='Company website (shown on PDFs if set)')
    tax_id = models.CharField(max_length=50, blank=True, verbose_name='Tax ID / TRN')
    fiscal_year_start = models.IntegerField(default=1, help_text='Month (1-12)')
    currency = models.CharField(max_length=10, default='AED')
    date_format = models.CharField(max_length=20, default='%d/%m/%Y')
    timezone = models.CharField(max_length=50, default='Asia/Dubai')
    INVENTORY_VALUATION_CHOICES = [
        ('fifo', 'FIFO'),
        ('weighted_average', 'Weighted Average'),
    ]
    inventory_valuation_method = models.CharField(
        max_length=30,
        choices=INVENTORY_VALUATION_CHOICES,
        default='weighted_average',
        help_text='Shown on inventory valuation reports.',
    )
    grn_over_receipt_tolerance_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Allow receipt up to this % over PO qty (0 = strict).',
    )

    # Defaults for new sales estimates (editable per estimate; users append text here over time)
    estimate_default_client_note = models.TextField(
        blank=True,
        help_text='Default client note appended to new estimates. Edit in Company Settings.',
    )
    estimate_default_terms = models.TextField(
        blank=True,
        help_text='Default terms & conditions for new estimates. Edit here; each estimate can still be customized.',
    )
    contract_default_terms = models.TextField(
        blank=True,
        help_text='Default terms & conditions for new contracts. Edit here; each contract can still be customized.',
    )
    estimate_to_project_prompt_include_lines = models.BooleanField(
        default=True,
        help_text=(
            'If on: converting an estimate to a project asks whether to copy all estimate lines '
            'into the project Items scope table (not Tasks). If off: only the empty project shell is created.'
        ),
    )
    estimate_default_authorized_signature = models.ImageField(
        upload_to='company/estimate_signatures/',
        blank=True,
        null=True,
        help_text='Default authorized signatory image for new estimates.',
    )
    estimate_default_customer_signature = models.ImageField(
        upload_to='company/estimate_signatures/',
        blank=True,
        null=True,
        help_text='Default customer signature image for new estimates.',
    )
    estimate_pdf_stamp_image = models.ImageField(
        upload_to='company/estimate_pdf/',
        blank=True,
        null=True,
        help_text='Image 1 — shown under company VAT / TRN on estimate quotation PDFs (left).',
    )
    estimate_pdf_footer_image = models.ImageField(
        upload_to='company/estimate_pdf/',
        blank=True,
        null=True,
        help_text='Image 2 — shown under company VAT / TRN on estimate quotation PDFs (right).',
    )
    openai_api_key = models.CharField(
        max_length=512,
        blank=True,
        help_text='Encrypted OpenAI API key for inventory AI forecasting.',
    )
    ai_token_limit = models.BigIntegerField(
        default=0,
        help_text='Total AI tokens purchased / allocated for this company.',
    )
    ai_tokens_used = models.BigIntegerField(
        default=0,
        help_text='AI tokens consumed across all ERP AI features.',
    )

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

    def set_openai_api_key(self, raw_key: str) -> None:
        from apps.inventory.crypto import encrypt_value

        raw_key = (raw_key or '').strip()
        if raw_key:
            self.openai_api_key = encrypt_value(raw_key)

    def get_openai_api_key_decrypted(self) -> str:
        from apps.inventory.crypto import decrypt_value

        return decrypt_value(self.openai_api_key or '')

    def openai_api_key_masked(self) -> str:
        from apps.inventory.utils import mask_secret

        return mask_secret(self.get_openai_api_key_decrypted())

    @property
    def ai_tokens_remaining(self) -> int:
        return max(0, int(self.ai_token_limit or 0) - int(self.ai_tokens_used or 0))


class AiCreditPurchase(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='AED')
    tokens_granted = models.BigIntegerField(default=0)
    stripe_checkout_session_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_credit_purchases',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.amount} {self.currency} → {self.tokens_granted} tokens ({self.status})'


class AiTokenUsageLog(models.Model):
    tokens = models.PositiveIntegerField()
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    model = models.CharField(max_length=80, blank=True)
    feature = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.tokens} tokens ({self.feature})'


class ItemSubGroupExpenseType(models.Model):
    """
    Configurable expense categories for inventory sub-groups (e.g. Labour, Other).
    Managed in Settings; optional on each sub-group, not on base groups.
    """

    name = models.CharField(max_length=120, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Sub-group expense type'
        verbose_name_plural = 'Sub-group expense types'

    def __str__(self):
        return self.name

    @classmethod
    def active_choices(cls):
        return cls.objects.filter(is_active=True).order_by('sort_order', 'name')


class EstimateTextTemplate(models.Model):
    """Reusable payment terms or terms & conditions templates for sales estimates."""

    CLIENT_NOTE = 'client_note'
    TERMS = 'terms'
    TEMPLATE_TYPE_CHOICES = [
        (CLIENT_NOTE, 'Payment terms'),
        (TERMS, 'Terms & conditions'),
    ]

    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPE_CHOICES)
    name = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    is_default = models.BooleanField(
        default=False,
        help_text='Pre-selected when creating a new estimate (one default per type).',
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Estimate text template'
        verbose_name_plural = 'Estimate text templates'

    def __str__(self):
        return f'{self.get_template_type_display()}: {self.name}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            EstimateTextTemplate.objects.filter(
                template_type=self.template_type,
                is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)

    @classmethod
    def get_default_body(cls, template_type):
        """Return body text for the default template, with legacy CompanySettings fallback."""
        template = (
            cls.objects.filter(template_type=template_type, is_active=True, is_default=True)
            .order_by('sort_order', 'name')
            .first()
        )
        if not template:
            template = (
                cls.objects.filter(template_type=template_type, is_active=True)
                .order_by('sort_order', 'name')
                .first()
            )
        if template:
            return template.body
        cs = CompanySettings.get_settings()
        if template_type == cls.CLIENT_NOTE:
            return cs.estimate_default_client_note or ''
        if template_type == cls.TERMS:
            return cs.estimate_default_terms or ''
        return ''


class PurchaseOrderTermsTemplate(models.Model):
    """Reusable terms & conditions templates for purchase orders."""

    name = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    is_default = models.BooleanField(
        default=False,
        help_text='Pre-selected when creating a new purchase order.',
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Purchase order terms template'
        verbose_name_plural = 'Purchase order terms templates'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            PurchaseOrderTermsTemplate.objects.filter(
                is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)

    @classmethod
    def get_default_body(cls):
        template = (
            cls.objects.filter(is_active=True, is_default=True)
            .order_by('sort_order', 'name')
            .first()
        )
        if not template:
            template = (
                cls.objects.filter(is_active=True)
                .order_by('sort_order', 'name')
                .first()
            )
        return template.body if template else ''


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
        ('estimate', 'Sales Estimate'),
        ('project', 'Project'),
        ('project_conversion', 'Project from estimate (draft)'),
        ('leave', 'Leave Request'),
        ('recruitment_request', 'Recruitment Request'),
        ('vendor_bill', 'Vendor Bill'),
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
    # Leave only: first-level approver when employee department has no manager
    manager_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approval_configs_leave_manager',
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
        amount = (
            getattr(request_obj, 'total_amount', 0)
            or getattr(request_obj, 'total_cost', 0)
            or getattr(request_obj, 'contract_value', 0)
            or getattr(request_obj, 'openings', 0)
            or 0
        )
        approver = cls.get_approver_for_amount(module, amount)
        if approver:
            ref = (
                getattr(request_obj, 'reference_number', None)
                or getattr(request_obj, 'display_reference', None)
                or getattr(request_obj, 'estimate_number', None)
                or getattr(request_obj, 'project_code', None)
                or getattr(request_obj, 'sr_number', None)
                or getattr(request_obj, 'pr_number', None)
                or getattr(request_obj, 'bill_number', None)
                or getattr(request_obj, 'request_number', None)
                or str(request_obj.pk)
            )
            pk = getattr(request_obj, 'pk', None)
            link_map = {
                'service_request': f'/service-request/{pk}/' if pk else '',
                'purchase_request': f'/purchase/requests/{pk}/' if pk else '',
                'inventory_request': f'/inventory/consumables/{pk}/' if pk else '',
                'estimate': f'/sales/estimates/{pk}/' if pk else '',
                'project': f'/projects/{pk}/' if pk else '',
                'project_conversion': f'/projects/{pk}/' if pk else '',
                'leave': f'/hr/leave/{pk}/' if pk else '',
                'recruitment_request': f'/recruitment/requests/{pk}/' if pk else '',
                'vendor_bill': f'/purchase/bills/{pk}/' if pk else '',
            }
            link = link_map.get(module, str(pk) if pk else '')
            title = f'Approval Required: {module.replace("_", " ").title()}'
            if module == 'estimate':
                msg = f'{ref} was edited and needs your approval to clear the review queue.'
            elif module == 'project':
                msg = f'{ref} completion was requested and needs your approval.'
            elif module == 'project_conversion':
                msg = f'{ref} was created from a quotation and needs your approval to leave Draft status.'
            elif module == 'leave':
                msg = f'Leave request {ref} requires your approval.'
            elif module == 'recruitment_request':
                msg = f'Recruitment request {ref} requires your approval.'
            elif module == 'vendor_bill':
                msg = f'Vendor bill {ref} requires your approval before posting. Amount: AED {amount:,.2f}'
            else:
                msg = f'{ref} requires your approval. Amount: AED {amount:,.2f}'
            Notification.create(
                user=approver,
                title=title,
                message=msg,
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


class ModuleAccessRequest(BaseModel):
    """User request for access to an ERP module (email sent to ERP team)."""

    STATUS_SENT = 'sent'
    STATUS_CHOICES = [
        (STATUS_SENT, 'Request sent'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='module_access_requests',
    )
    module = models.CharField(max_length=50, choices=ModulePermission.MODULE_CHOICES)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SENT)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'module'],
                name='settings_unique_module_access_request',
            ),
        ]

    def __str__(self):
        return f'{self.user.username} → {self.get_module_display()} ({self.get_status_display()})'


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


class ForecastSalesAchievement(BaseModel):
    """Manual target-achieved entry per sales employee and month."""

    employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='forecast_achievements',
    )
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    achieved_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Actual value achieved for the month (AED).',
    )
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-year', '-month', 'employee__first_name']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'year', 'month'],
                name='settings_unique_forecast_achievement_per_month',
            ),
        ]
        verbose_name = 'Forecast sales achievement'
        verbose_name_plural = 'Forecast sales achievements'

    def __str__(self):
        return f'{self.employee} — {self.year}-{self.month:02d}'


class CashFlowMonthSheet(BaseModel):
    """One monthly cash-flow estimation workbook."""

    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    cash_bank_in_hand = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Cash/bank balance for summary (AED).',
    )

    class Meta:
        ordering = ['-year', '-month']
        constraints = [
            models.UniqueConstraint(
                fields=['year', 'month'],
                name='settings_unique_cashflow_sheet_per_month',
            ),
        ]
        verbose_name = 'Cash flow month sheet'
        verbose_name_plural = 'Cash flow month sheets'

    def __str__(self):
        return f'Cash flow {self.year}-{self.month:02d}'

    @property
    def month_label(self):
        from datetime import date

        return date(self.year, self.month, 1).strftime('%B %Y')


class CashFlowIncomeLine(BaseModel):
    LINE_SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('auto_quotation', 'Quotation'),
        ('auto_amc', 'AMC renewal'),
    ]

    INCOME_CATEGORY_CHOICES = [
        ('maintenance', 'Maintenance'),
        ('amc', 'AMC'),
        ('project', 'Project'),
        ('decor', 'Decor'),
        ('office', 'Office'),
    ]
    PAYMENT_TYPE_CHOICES = [
        ('bank_adcb', 'Bank/ADCB'),
        ('cheque', 'Cheque'),
        ('cash', 'Cash'),
        ('online', 'Online'),
    ]
    LINE_KIND_CHOICES = [
        ('normal', 'Normal'),
        ('unexpected_income', 'Unexpected Income'),
    ]

    sheet = models.ForeignKey(CashFlowMonthSheet, on_delete=models.CASCADE, related_name='income_lines')
    line_date = models.DateField(null=True, blank=True)
    customer = models.ForeignKey(
        'crm.Customer',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='cashflow_income_lines',
    )
    category = models.CharField(max_length=30, choices=INCOME_CATEGORY_CHOICES, default='project')
    details = models.CharField(max_length=500, blank=True)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='bank_adcb')
    sales_man = models.CharField(max_length=200, blank=True)
    employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_income_lines',
    )
    income_expected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    invoice = models.ForeignKey(
        'sales.Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_income_lines',
    )
    estimate = models.ForeignKey(
        'sales.Estimate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_income_lines',
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_income_lines',
    )
    amc_contract = models.ForeignKey(
        'contracts.Contract',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_income_lines',
    )
    line_kind = models.CharField(max_length=30, choices=LINE_KIND_CHOICES, default='normal')
    line_source = models.CharField(max_length=30, choices=LINE_SOURCE_CHOICES, default='manual')
    sync_suppressed = models.BooleanField(
        default=False,
        help_text='When set, auto-sync will not recreate this line after the user removes it.',
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'line_date', 'pk']


class CashFlowChequeLine(BaseModel):
    LINE_SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('auto_pdc', 'PDC'),
    ]

    CATEGORY_CHOICES = CashFlowIncomeLine.INCOME_CATEGORY_CHOICES

    sheet = models.ForeignKey(CashFlowMonthSheet, on_delete=models.CASCADE, related_name='cheque_lines')
    line_date = models.DateField(null=True, blank=True)
    customer = models.ForeignKey(
        'crm.Customer',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='cashflow_cheque_lines',
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='maintenance')
    details = models.CharField(max_length=500, blank=True)
    income_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    invoice = models.ForeignKey(
        'sales.Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_cheque_lines',
    )
    pdc_cheque = models.ForeignKey(
        'property.PDCCheque',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_cheque_lines',
    )
    line_source = models.CharField(max_length=30, choices=LINE_SOURCE_CHOICES, default='manual')
    sync_suppressed = models.BooleanField(
        default=False,
        help_text='When set, auto-sync will not recreate this line after the user removes it.',
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'line_date', 'pk']


class CashFlowExpenseLine(BaseModel):
    LINE_SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('auto_vendor_bill', 'Vendor bill'),
    ]

    ACCOUNT_CHOICES = [
        ('purchase', 'Purchase'),
        ('salary', 'Salary'),
        ('loan', 'Loan'),
        ('vehicle_loan_emi', 'Vehicle Loan / EMI'),
        ('visa_exp', 'Visa Exp'),
        ('office', 'Office'),
        ('utility', 'Utility'),
        ('labor', 'Labor'),
        ('settlement', 'Settlement'),
        ('civil_defence_fee', 'Civil Defence Fee'),
        ('reserve_fund', 'Reserve Fund'),
        ('pdc_cheques', 'PDC Cheques'),
        ('manpower', 'Manpower'),
    ]
    PAYMENT_TYPE_CHOICES = [
        ('pdc', 'PDC'),
        ('cheque', 'Cheque'),
        ('cash', 'Cash'),
        ('bank', 'Bank'),
        ('emi', 'EMI'),
        ('online', 'Online'),
    ]
    LINE_KIND_CHOICES = [
        ('normal', 'Normal'),
        ('vehicle_petrol', 'Vehicle Petrol'),
        ('unexpected_expense', 'Unexpected Expense'),
    ]

    sheet = models.ForeignKey(CashFlowMonthSheet, on_delete=models.CASCADE, related_name='expense_lines')
    line_date = models.DateField(null=True, blank=True)
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='cashflow_expense_lines',
    )
    account = models.CharField(max_length=30, choices=ACCOUNT_CHOICES, default='purchase')
    details = models.CharField(max_length=500, blank=True)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='bank')
    expense = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    vendor_bill = models.ForeignKey(
        'purchase.VendorBill',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashflow_expense_lines',
    )
    line_kind = models.CharField(max_length=30, choices=LINE_KIND_CHOICES, default='normal')
    line_source = models.CharField(max_length=30, choices=LINE_SOURCE_CHOICES, default='manual')
    sync_suppressed = models.BooleanField(
        default=False,
        help_text='When set, auto-sync will not recreate this line after the user removes it.',
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'line_date', 'pk']

