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
    
    employee_code = models.CharField(max_length=50, unique=True, editable=True)
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

    company = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees',
    )
    LOCATION_CHOICES = [('uae', 'UAE'), ('ksa', 'KSA'), ('other', 'Other')]
    location = models.CharField(max_length=10, choices=LOCATION_CHOICES, default='uae')
    
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
    """Leave types — UAE/KSA rules (extended fields; legacy fields retained)."""

    LOCATION_SCOPE = [
        ('uae', 'UAE'),
        ('ksa', 'KSA'),
        ('both', 'Both'),
    ]
    PAY_TYPE_CHOICES = [
        ('full', 'Full pay'),
        ('half', 'Half pay'),
        ('unpaid', 'Unpaid'),
        ('tiered', 'Tiered'),
    ]
    GENDER_RESTRICT_CHOICES = [
        ('', 'None'),
        ('male', 'Male'),
        ('female', 'Female'),
    ]

    name = models.CharField(max_length=100)
    days_allowed = models.PositiveIntegerField(default=0, null=True, blank=True)  # null / 0 = unlimited or policy-driven
    code = models.CharField(max_length=50, unique=True, blank=True)
    is_probation_only = models.BooleanField(default=False)
    is_gender_specific = models.BooleanField(default=False)
    gender_required = models.CharField(max_length=10, choices=Employee.GENDER_CHOICES, blank=True)
    requires_medical_certificate = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    location = models.CharField(max_length=10, choices=LOCATION_SCOPE, default='both')
    pay_type = models.CharField(max_length=10, choices=PAY_TYPE_CHOICES, default='full')
    gender_restricted = models.CharField(max_length=10, choices=GENDER_RESTRICT_CHOICES, blank=True)
    religion_restricted = models.BooleanField(default=False)
    probation_allowed = models.BooleanField(default=True)
    min_service_days = models.PositiveIntegerField(default=0)
    once_in_service = models.BooleanField(default=False)
    carry_forward_allowed = models.BooleanField(default=False)
    carry_forward_cap = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Maximum days that may carry from prior year (e.g. 15 UAE annual, 30 KSA annual).',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class LeaveBalance(BaseModel):
    """Per-employee leave balance for a calendar year."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='leave_balances')
    year = models.PositiveIntegerField()
    entitled_days = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    used_days = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    pending_days = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    carried_forward = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['-year', 'leave_type__name']
        unique_together = [('employee', 'leave_type', 'year')]
        indexes = [
            models.Index(fields=['employee', 'year']),
        ]

    def __str__(self):
        return f'{self.employee.employee_code} · {self.leave_type.name} · {self.year}'

    @property
    def remaining_days(self) -> Decimal:
        raw = self.entitled_days + self.carried_forward - self.used_days - self.pending_days
        return max(Decimal('0.00'), raw.quantize(Decimal('0.01')))


class LeaveRequest(BaseModel):
    STATUS_CHOICES = [
        ('pending_manager', 'Pending manager'),
        ('pending_hr', 'Pending HR'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending_manager')

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leave_requests_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    medical_certificate_uploaded = models.BooleanField(default=False)
    medical_certificate = models.FileField(upload_to='leave/medical/%Y/%m/', blank=True, null=True)

    covering_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='covered_leave_requests',
    )
    return_date = models.DateField(null=True, blank=True)
    is_half_day = models.BooleanField(default=False)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    requested_working_days = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))

    reference_number = models.CharField(max_length=40, unique=True, blank=True, null=True)
    submitted_publicly = models.BooleanField(default=False)
    split_group_id = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee.full_name} - {self.leave_type.name}"

    @property
    def days(self):
        """Calendar span (inclusive)."""
        return (self.end_date - self.start_date).days + 1

    def save(self, *args, **kwargs):
        from apps.hr.leave_utils import compute_return_date, count_uae_working_days, ensure_leave_reference

        if self.start_date and self.end_date:
            self.requested_working_days = count_uae_working_days(
                self.start_date, self.end_date, half_day=self.is_half_day
            )
            self.return_date = compute_return_date(self.end_date)
        super().save(*args, **kwargs)
        ensure_leave_reference(self)


class Payroll(BaseModel):
    """
    Payroll model with SAP/Oracle-style accounting integration.
    
    When Processed: Dr Salary Expense, Cr Salary Payable
    When Paid: Dr Salary Payable, Cr Bank
    """
    STATUS_CHOICES = [('draft', 'Draft'), ('processed', 'Processed'), ('paid', 'Paid')]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payrolls')
    company = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payrolls',
        help_text='Legal entity for reporting/WPS/GOSI filtering; defaults from employee when blank.',
    )
    payslip_email_sent = models.BooleanField(default=False)
    month = models.DateField()  # First day of month
    basic_salary = models.DecimalField(max_digits=15, decimal_places=2)
    allowances = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Total allowances (sum of allowance lines; kept for net salary / journals).',
    )
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

        from apps.hr.payroll_processing import finalize_advance_repayments_for_payroll

        finalize_advance_repayments_for_payroll(self)
        
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


# Extended HR models (attendance, compliance, payroll lines — separate definitions).
from apps.hr.models_extended import (  # noqa: E402
    AdvanceRepayment,
    AttendanceRecord,
    AttendanceSettings,
    AttendanceSummary,
    EmployeeAdvance,
    Holiday,
    EmployeeBankDetail,
    EmployeeHRProfile,
    GOSIRecord,
    GratuityRecord,
    KSACompliance,
    PayrollAllowanceLine,
    PayrollDeductionLine,
    PayrollEmployerContribution,
    PayrollSettings,
    PayrollTemplate,
    UAECompliance,
    WPSMonthlyFile,
    WPSRecord,
)
