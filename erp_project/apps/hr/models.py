"""HR Models - Departments, Employees, Leave, Payroll"""
from django.db import models
from django.conf import settings
from decimal import Decimal
from apps.core.models import BaseModel
from apps.core.utils import generate_number


class Department(BaseModel):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_departments')
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Designation(BaseModel):
    name = models.CharField(max_length=200)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='designations')
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.department.name})"


class Employee(BaseModel):
    STATUS_CHOICES = [('active', 'Active'), ('inactive', 'Inactive'), ('terminated', 'Terminated')]
    GENDER_CHOICES = [('male', 'Male'), ('female', 'Female'), ('other', 'Other')]
    
    employee_code = models.CharField(max_length=50, unique=True, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_profile')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='employees')
    designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, related_name='employees')
    date_of_birth = models.DateField(null=True, blank=True)
    date_of_joining = models.DateField(null=True, blank=True)
    probation_period_days = models.PositiveIntegerField(default=90)  # UAE default is 90 days
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    basic_salary = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # UAE Specific
    emirates_id = models.CharField(max_length=50, blank=True)
    visa_number = models.CharField(max_length=50, blank=True)
    visa_expiry = models.DateField(null=True, blank=True)
    
    class Meta:
        ordering = ['first_name', 'last_name']
    
    def __str__(self):
        return f"{self.employee_code} - {self.first_name} {self.last_name}"
    
    def save(self, *args, **kwargs):
        if not self.employee_code:
            self.employee_code = generate_number('EMPLOYEE', Employee, 'employee_code')
        super().save(*args, **kwargs)
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def is_in_probation(self):
        """Check if employee is still in probation period."""
        if not self.date_of_joining:
            return False
        from datetime import date, timedelta
        probation_end_date = self.date_of_joining + timedelta(days=self.probation_period_days)
        return date.today() <= probation_end_date


class LeaveType(BaseModel):
    """Leave types according to UAE Labor Law."""
    name = models.CharField(max_length=100)
    days_allowed = models.PositiveIntegerField(default=0)  # 0 means unlimited
    code = models.CharField(max_length=50, unique=True, blank=True)  # e.g., 'MATERNITY', 'SICK_PROBATION'
    is_probation_only = models.BooleanField(default=False)  # Only available during probation
    is_gender_specific = models.BooleanField(default=False)  # e.g., Maternity leave
    gender_required = models.CharField(max_length=10, choices=Employee.GENDER_CHOICES, blank=True)  # 'female' for maternity
    requires_medical_certificate = models.BooleanField(default=False)  # For sick leave
    is_paid = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class LeaveRequest(BaseModel):
    STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.employee.full_name} - {self.leave_type.name}"
    
    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1


class Payroll(BaseModel):
    """
    Payroll model with SAP/Oracle-style accounting integration.
    
    When Processed: Dr Salary Expense, Cr Salary Payable
    When Paid: Dr Salary Payable, Cr Bank
    """
    STATUS_CHOICES = [('draft', 'Draft'), ('processed', 'Processed'), ('paid', 'Paid')]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payrolls')
    month = models.DateField()  # First day of month
    basic_salary = models.DecimalField(max_digits=15, decimal_places=2)
    allowances = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    deductions = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    net_salary = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Journal entry created on process
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_entries'
    )
    
    # Payment journal entry
    payment_journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_payments'
    )
    
    # Payment details
    paid_from_bank = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    paid_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ['-month']
        unique_together = ['employee', 'month']
    
    def __str__(self):
        return f"{self.employee.full_name} - {self.month.strftime('%B %Y')}"
    
    def calculate_net(self):
        self.net_salary = self.basic_salary + self.allowances - self.deductions
        self.save(update_fields=['net_salary'])
    
    def post_to_accounting(self, user=None):
        """
        Post payroll to accounting when processed.
        Uses Account Mapping (SAP/Oracle-style Account Determination).
        
        Dr Salary Expense (gross salary)
        Cr Salary Payable (net salary)
        Cr Other Deductions (if any)
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account, AccountType, AccountMapping, FiscalYear
        from django.core.exceptions import ValidationError

        if self.status != 'draft':
            raise ValidationError("Only draft payrolls can be processed.")

        FiscalYear.validate_posting_allowed(self.month)

        if self.journal_entry:
            raise ValidationError("Journal entry already exists for this payroll.")
        
        # Account determination: Account Mapping first, then hard-coded defaults.
        # NO generic fallback — posting to the wrong account is worse than failing.
        salary_expense = AccountMapping.get_account_or_default('payroll_salary_expense', '5300')
        if not salary_expense:
            raise ValidationError(
                "Salary Expense account not configured. "
                "Expected account 5300 or set up 'payroll_salary_expense' in Finance → Account Mapping."
            )

        salary_payable = AccountMapping.get_account_or_default('payroll_salary_payable', '2200')
        if not salary_payable:
            raise ValidationError(
                "Salary Payable account not configured. "
                "Expected account 2200 or set up 'payroll_salary_payable' in Finance → Account Mapping."
            )
        
        gross_salary = self.basic_salary + self.allowances
        
        # Create journal entry
        journal = JournalEntry.objects.create(
            date=self.month,
            reference=f"PAYROLL-{self.pk}",
            description=f"Payroll: {self.employee.full_name} - {self.month.strftime('%B %Y')}",
            entry_type='standard',
            source_module='payroll',
        )
        
        # Debit Salary Expense (gross salary)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=salary_expense,
            description=f"Salary Expense - {self.employee.full_name}",
            debit=gross_salary,
            credit=Decimal('0.00'),
        )
        
        # Credit Salary Payable (net salary)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=salary_payable,
            description=f"Salary Payable - {self.employee.full_name}",
            debit=Decimal('0.00'),
            credit=self.net_salary,
        )
        
        # Credit deductions (if any) - simplified: goes to salary payable
        if self.deductions > 0:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=salary_payable,
                description=f"Deductions - {self.employee.full_name}",
                debit=Decimal('0.00'),
                credit=self.deductions,
            )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.journal_entry = journal
        self.status = 'processed'
        self.save(update_fields=['journal_entry', 'status'])
        
        return journal
    
    def post_payment_journal(self, bank_account, payment_date, reference='', user=None):
        """
        Post payment journal when salary is paid.
        Uses Account Mapping (SAP/Oracle-style Account Determination).
        
        Dr Salary Payable
        Cr Bank
        """
        from apps.finance.models import JournalEntry, JournalEntryLine, Account, AccountType, AccountMapping
        from django.core.exceptions import ValidationError
        
        if self.status != 'processed':
            raise ValidationError("Only processed payrolls can be paid.")
        
        if self.payment_journal_entry:
            raise ValidationError("Payment journal already exists for this payroll.")
        
        # Account determination: Account Mapping first, then hard-coded default.
        # NO generic fallback — posting to the wrong account is worse than failing.
        salary_payable = AccountMapping.get_account_or_default('payroll_payment_clear', '2200')
        if not salary_payable:
            salary_payable = AccountMapping.get_account_or_default('payroll_salary_payable', '2200')
        if not salary_payable:
            raise ValidationError(
                "Salary Payable account not configured. "
                "Expected account 2200 or set up 'payroll_salary_payable' in Finance → Account Mapping."
            )
        
        if not bank_account.gl_account:
            raise ValidationError("Bank account has no linked GL account.")
        
        # Create payment journal entry
        journal = JournalEntry.objects.create(
            date=payment_date,
            reference=reference or f"PAY-PAYROLL-{self.pk}",
            description=f"Salary Payment: {self.employee.full_name} - {self.month.strftime('%B %Y')}",
            entry_type='standard',
            source_module='payment',
        )
        
        # Debit Salary Payable (clear liability)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=salary_payable,
            description=f"Clear Salary Payable - {self.employee.full_name}",
            debit=self.net_salary,
            credit=Decimal('0.00'),
        )
        
        # Credit Bank Account
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account.gl_account,
            description=f"Salary to {self.employee.full_name}",
            debit=Decimal('0.00'),
            credit=self.net_salary,
        )
        
        journal.calculate_totals()
        journal.post(user)
        
        self.payment_journal_entry = journal
        self.paid_from_bank = bank_account
        self.paid_date = payment_date
        self.payment_reference = reference
        self.status = 'paid'
        self.save(update_fields=['payment_journal_entry', 'paid_from_bank', 'paid_date', 'payment_reference', 'status'])
        
        return journal

