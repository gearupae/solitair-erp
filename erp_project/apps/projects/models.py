"""
Projects Models - Projects, Tasks, Project Expenses
With full accounting integration:
- Project Expenses → Project Expense Ledger
- Project Revenue → Project Revenue Ledger
- All postings flow automatically to GL with project/cost center tracking
"""
from django.db import models
from django.db.models import Sum, Q
from django.conf import settings
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.core.models import BaseModel
from apps.core.utils import generate_number
from apps.crm.models import Customer


class Project(BaseModel):
    """
    Project model with cost center functionality.
    Acts as a cost center for tracking project-specific revenue and expenses.
    """
    EDIT_APPROVAL_STATUS_CHOICES = [
        ('none', 'No pending edit review'),
        ('pending', 'Pending edit approval'),
        ('rejected', 'Edit rejected'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('planning', 'Planning'),
        ('in_progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    CONVERSION_APPROVAL_STATUS_CHOICES = [
        ('none', 'No pending conversion approval'),
        ('pending', 'Pending conversion approval'),
        ('rejected', 'Conversion rejected'),
    ]
    
    BILLING_TYPE_CHOICES = [
        ('fixed', 'Fixed Price'),
        ('time_material', 'Time & Material'),
        ('milestone', 'Milestone Based'),
    ]
    
    project_code = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='projects')
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='managed_projects')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning')
    conversion_approval_status = models.CharField(
        max_length=20,
        choices=CONVERSION_APPROVAL_STATUS_CHOICES,
        default='none',
        help_text='When set from estimate conversion, project stays in Draft until approved.',
    )
    conversion_approval_submitted_at = models.DateTimeField(null=True, blank=True)
    conversion_approval_submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_conversion_approval_submissions',
    )
    edit_approval_status = models.CharField(
        max_length=20,
        choices=EDIT_APPROVAL_STATUS_CHOICES,
        default='none',
        help_text='Pending completion approval when a user requests status Completed.',
    )
    edit_approval_submitted_at = models.DateTimeField(null=True, blank=True)
    edit_approval_submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_edit_approval_submissions',
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    
    # Budget & Billing
    billing_type = models.CharField(max_length=20, choices=BILLING_TYPE_CHOICES, default='fixed')
    budget = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    estimated_cost = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Estimated cost',
        help_text='Expected cost to deliver this project',
    )
    contract_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='project_memberships',
        help_text='Team members assigned to this project',
    )
    technicians = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='technician_projects',
        help_text='Field technicians; clock in to this project on the public attendance link to allocate hours here.',
    )
    
    # Accounting Tracking
    total_expenses = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_billed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # GL Account overrides (optional - uses Account Mapping if not set)
    expense_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='project_expenses_account'
    )
    revenue_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='project_revenue_account'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.project_code} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.project_code:
            self.project_code = generate_number('PROJECT', Project, 'project_code')
        super().save(*args, **kwargs)

    def allows_edit_by(self, user):
        from apps.projects.approval_rules import user_can_edit_project

        return user_can_edit_project(user, self)

    @property
    def total_tasks(self):
        return self.tasks.filter(is_active=True).count()
    
    @property
    def completed_tasks(self):
        return self.tasks.filter(is_active=True, status='completed').count()
    
    @property
    def task_progress_percent(self):
        """Equal weight per task: completed / total * 100."""
        total = self.tasks.filter(is_active=True).count()
        if total == 0:
            return Decimal('0')
        done = self.tasks.filter(is_active=True, status='completed').count()
        return (Decimal(done) / Decimal(total) * Decimal('100')).quantize(Decimal('0.1'))
    
    @property
    def recorded_expenses_total(self):
        """Sum of expense amounts recorded for this project (excludes rejected)."""
        agg = self.project_expenses.filter(is_active=True).exclude(status='rejected').aggregate(
            s=Sum('total_amount')
        )
        return agg['s'] if agg['s'] is not None else Decimal('0.00')
    
    @property
    def profit_margin(self):
        """Calculate project profit margin."""
        if self.total_revenue > 0:
            return ((self.total_revenue - self.total_expenses) / self.total_revenue * 100).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    @property
    def budget_utilization(self):
        """Calculate budget utilization percentage."""
        if self.budget > 0:
            return (self.total_expenses / self.budget * 100).quantize(Decimal('0.01'))
        return Decimal('0.00')
    
    def update_totals(self):
        """Recalculate project totals from expenses and revenue entries."""
        # Sum expenses
        expense_total = self.project_expenses.filter(
            is_active=True, posted=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Sum revenue (from invoices linked to project via ProjectInvoice)
        # Access the invoice through the ProjectInvoice link
        revenue_total = Decimal('0.00')
        for project_invoice in self.invoices.filter(is_active=True).select_related('invoice'):
            if project_invoice.invoice and project_invoice.invoice.status in ['posted', 'paid', 'partial']:
                revenue_total += project_invoice.invoice.total_amount or Decimal('0.00')
        
        self.total_expenses = expense_total
        self.total_revenue = revenue_total
        self.save(update_fields=['total_expenses', 'total_revenue'])


class Task(BaseModel):
    """Task model."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='tasks',
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='tasks',
        null=True,
        blank=True,
        verbose_name='Customer / lead',
        help_text='CRM record when the task is not tied to a project.',
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    start_date = models.DateField(null=True, blank=True, verbose_name='Start date')
    due_date = models.DateField(null=True, blank=True, verbose_name='End date')
    estimated_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['due_date', 'start_date', 'priority', 'name']

    def clean(self):
        super().clean()
        if not self.project_id and not self.customer_id:
            raise ValidationError('Task must be linked to a project or a customer/lead.')

    def __str__(self):
        if self.project_id:
            prefix = self.project.project_code
        elif self.customer_id:
            prefix = self.customer.customer_number
        else:
            prefix = 'Unlinked'
        return f"{prefix} - {self.name}"

    @property
    def context_code(self):
        if self.project_id:
            return self.project.project_code
        if self.customer_id:
            return self.customer.customer_number
        return '—'

    @property
    def context_name(self):
        if self.project_id:
            return self.project.name
        if self.customer_id:
            return self.customer.name
        return ''

    @property
    def context_type_label(self):
        if self.project_id:
            return 'Project'
        if self.customer_id:
            return 'Lead' if self.customer.customer_type == 'lead' else 'Customer'
        return ''


class ProjectItemLine(models.Model):
    """
    Commercial / scope lines copied from an estimate when converting to a project.
    Distinct from Task (operational work items).
    """
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='item_lines')
    sort_order = models.PositiveIntegerField(default=0)
    group_name = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=500)
    inventory_item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_item_lines',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1'))
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    rate = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    line_net = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Line amount excluding VAT (matches estimate line total)',
    )
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Project item line'
        verbose_name_plural = 'Project item lines'

    def __str__(self):
        return f'{self.project.project_code}: {self.description[:50]}'

    @property
    def line_total_incl_vat(self):
        return (self.line_net or Decimal('0')) + (self.vat_amount or Decimal('0'))


class ProjectItemDelivery(models.Model):
    """Log of non-serial qty deliveries from inventory to a project."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='item_deliveries',
    )
    item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.PROTECT,
        related_name='project_item_deliveries',
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    delivered_date = models.DateField()
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_item_deliveries',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-delivered_date', '-pk']
        verbose_name = 'Project item delivery'
        verbose_name_plural = 'Project item deliveries'

    def __str__(self):
        return f'{self.project.project_code}: {self.item.name} × {self.quantity}'


class ProjectItemReturn(models.Model):
    """Log of inventory returned from a project back to stock."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='item_returns',
    )
    item = models.ForeignKey(
        'inventory.Item',
        on_delete=models.PROTECT,
        related_name='project_item_returns',
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('1'))
    returned_date = models.DateField()
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_item_returns',
    )
    serial_number = models.ForeignKey(
        'inventory.ItemSerialNumber',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_returns',
    )
    notes = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-returned_date', '-pk']
        verbose_name = 'Project item return'
        verbose_name_plural = 'Project item returns'

    def __str__(self):
        if self.serial_number_id:
            return f'{self.project.project_code}: {self.serial_number.model_number} returned'
        return f'{self.project.project_code}: {self.quantity} × {self.item.name} returned'


class ProjectGatepass(BaseModel):
    """Site / client gate pass for a project team member, with expiry tracking."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='gatepasses')
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='project_gatepasses',
    )
    start_date = models.DateField()
    expiry_date = models.DateField()
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-expiry_date', '-created_at']
        verbose_name = 'Project gate pass'
        verbose_name_plural = 'Project gate passes'
        indexes = [
            models.Index(fields=['project', 'is_active', 'expiry_date']),
        ]

    def __str__(self):
        return f'{self.project.project_code} — {self.member} (to {self.expiry_date})'

    def clean(self):
        super().clean()
        if self.start_date and self.expiry_date and self.start_date > self.expiry_date:
            raise ValidationError('Start date must be on or before expiry date.')
        if self.project_id and self.member_id:
            if not self.project.members.filter(pk=self.member_id).exists():
                raise ValidationError({'member': 'Selected user must be a member of this project.'})


class ProjectExpense(BaseModel):
    """
    Project-specific expense tracking with GL posting.
    Links expenses directly to projects for cost center reporting.
    
    Accounting:
    Dr Project Expense Account
    Cr AP / Bank / Cash
    """
    CATEGORY_CHOICES = [
        ('material', 'Materials'),
        ('labor', 'Labor'),
        ('subcontract', 'Subcontractor'),
        ('travel', 'Travel'),
        ('equipment', 'Equipment'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('posted', 'Posted'),
        ('rejected', 'Rejected'),
    ]
    
    expense_number = models.CharField(max_length=50, unique=True, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='project_expenses'
    )
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='other')
    description = models.CharField(max_length=500)
    expense_date = models.DateField()
    
    # Amount
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Vendor (if applicable)
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='project_expenses'
    )
    invoice_reference = models.CharField(max_length=100, blank=True)

    # Link to posted vendor bill (expense line mirrors bill; single JE via vendor bill)
    vendor_bill = models.ForeignKey(
        'purchase.VendorBill',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_project_expenses',
    )

    # Status & Approval
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_project_expenses'
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    
    # Accounting
    expense_account = models.ForeignKey(
        'finance.Account',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='project_expense_items'
    )
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='project_expenses'
    )
    posted = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-expense_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['vendor_bill'],
                condition=Q(vendor_bill__isnull=False),
                name='uniq_project_expense_per_vendor_bill',
            ),
        ]
    
    def __str__(self):
        return f"{self.expense_number} - {self.project.project_code}: {self.description}"
    
    def save(self, *args, **kwargs):
        if not self.expense_number:
            self.expense_number = generate_number('PROJ-EXP', ProjectExpense, 'expense_number')
        self.total_amount = self.amount + self.vat_amount
        super().save(*args, **kwargs)
    
    def post_to_accounting(self, user=None):
        """
        Post project expense to accounting.
        Dr Project Expense Account
        Dr VAT Recoverable (if applicable)
        Cr Accounts Payable / Accrued Expenses
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, AccountMapping, FiscalYear

        if self.posted:
            raise ValidationError("Expense already posted to accounting.")

        if self.vendor_bill_id:
            raise ValidationError(
                "This expense is created from a vendor bill. "
                "Amounts and posting are managed from Purchase → Vendor Bills."
            )

        if self.status != 'approved':
            raise ValidationError("Only approved expenses can be posted.")

        FiscalYear.validate_posting_allowed(self.expense_date)
        
        # Get accounts
        expense_account = self.expense_account or self.project.expense_account or \
                         AccountMapping.get_account_or_default('project_expense', '5000')
        ap_account = AccountMapping.get_account_or_default('project_expense_clearing', '2000')
        vat_recoverable = AccountMapping.get_account_or_default('vendor_bill_vat', '1300')
        
        if not expense_account:
            raise ValidationError("Project Expense account not configured.")
        if not ap_account:
            raise ValidationError("Expense Clearing/AP account not configured.")
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.expense_date,
            reference=self.expense_number,
            description=f"Project Expense: {self.project.project_code} - {self.description}",
            entry_type='standard',
            source_module='project',
        )
        
        # Debit Expense
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=expense_account,
            description=f"Project {self.project.project_code}: {self.get_category_display()} - {self.description}",
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        
        # Debit VAT (if applicable)
        if self.vat_amount > 0 and vat_recoverable:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_recoverable,
                description=f"Input VAT - {self.expense_number}",
                debit=self.vat_amount,
                credit=Decimal('0.00'),
            )
        
        # Credit AP/Clearing
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f"AP - {self.vendor.name if self.vendor else 'Accrued'}",
            debit=Decimal('0.00'),
            credit=self.total_amount,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.journal_entry = journal
        self.posted = True
        self.status = 'posted'
        self.save(update_fields=['journal_entry', 'posted', 'status'])
        
        # Update project totals
        self.project.update_totals()
        
        return journal


class ProjectPublicUpload(BaseModel):
    """
    File uploaded via the anonymous public project upload form.
    Appears on the project detail (overview) page for staff.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='public_uploads',
    )
    file = models.FileField(upload_to='project_public/%Y/%m/', max_length=500)
    original_filename = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.project.project_code}: {self.original_filename or self.file.name}'

    @property
    def is_probably_image(self):
        name = (self.original_filename or self.file.name or '').lower()
        return name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif'))


class ProjectInvoice(BaseModel):
    """
    Link between projects and sales invoices for revenue tracking.
    """
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    invoice = models.ForeignKey(
        'sales.Invoice',
        on_delete=models.CASCADE,
        related_name='project_links'
    )
    description = models.CharField(max_length=500, blank=True)
    
    class Meta:
        unique_together = ['project', 'invoice']
    
    def __str__(self):
        return f"{self.project.project_code} - {self.invoice.invoice_number}"


