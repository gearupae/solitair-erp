"""
Projects Models - Projects, Tasks, Timesheets, Project Expenses
With full accounting integration:
- Project Expenses → Project Expense Ledger
- Project Revenue → Project Revenue Ledger
- All postings flow automatically to GL with project/cost center tracking
"""
from django.db import models
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
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('in_progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
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
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    
    # Budget & Billing
    billing_type = models.CharField(max_length=20, choices=BILLING_TYPE_CHOICES, default='fixed')
    budget = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    contract_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
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
    
    @property
    def total_tasks(self):
        return self.tasks.count()
    
    @property
    def completed_tasks(self):
        return self.tasks.filter(status='completed').count()
    
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
        from django.db.models import Sum
        
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
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    due_date = models.DateField(null=True, blank=True)
    estimated_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['priority', 'due_date']
    
    def __str__(self):
        return f"{self.project.project_code} - {self.name}"


class Timesheet(BaseModel):
    """Timesheet entry model."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='timesheets')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='timesheets')
    date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    description = models.TextField(blank=True)
    billable = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-date']
    
    def __str__(self):
        return f"{self.user.username} - {self.task.name} - {self.hours}h"
    
    def save(self, *args, **kwargs):
        self.total_cost = self.hours * self.hourly_rate
        super().save(*args, **kwargs)


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


