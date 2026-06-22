"""
Extended HR models (attendance, compliance, payroll lines, WPS).
Existing Employee/Payroll models are not altered — relations use ForeignKeys here.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import BaseModel
from apps.hr.compliance_utils import UNKNOWN, expiry_band


class EmployeeHRProfile(BaseModel):
    """Entity + nationality used for UAE/KSA payroll rules (extends Employee without changing Employee)."""

    EMPLOYMENT_ENTITY_CHOICES = [
        ('uae', 'UAE'),
        ('ksa', 'KSA'),
        ('other', 'Other'),
    ]
    GOSI_CATEGORY_CHOICES = [
        ('saudi', 'Saudi national'),
        ('non_saudi', 'Non-Saudi / expat'),
    ]

    employee = models.OneToOneField(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='hr_profile',
    )
    employment_entity = models.CharField(max_length=10, choices=EMPLOYMENT_ENTITY_CHOICES, default='uae')
    gosi_employee_category = models.CharField(
        max_length=20,
        choices=GOSI_CATEGORY_CHOICES,
        default='non_saudi',
        help_text='For KSA GOSI split (Saudi vs expat rates).',
    )
    nationality_display = models.CharField(
        max_length=120,
        blank=True,
        help_text='Shown on payslip (e.g. Indian, Saudi).',
    )
    COMMISSION_TYPE_NONE = ''
    COMMISSION_TYPE_PERCENTAGE = 'percentage'
    COMMISSION_TYPE_FIXED = 'fixed'
    COMMISSION_TYPE_CHOICES = [
        (COMMISSION_TYPE_NONE, 'None'),
        (COMMISSION_TYPE_PERCENTAGE, 'Percentage of sales'),
        (COMMISSION_TYPE_FIXED, 'Fixed amount'),
    ]
    commission_type = models.CharField(
        max_length=20,
        choices=COMMISSION_TYPE_CHOICES,
        blank=True,
        default='',
        help_text='How payroll commissions are calculated for this employee.',
    )
    commission_percentage = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Used when commission type is Percentage (e.g. 5.00 = 5% of monthly sales).',
    )
    commission_fixed_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Used when commission type is Fixed (flat monthly commission when sales exist).',
    )

    class Meta:
        verbose_name = 'Employee HR profile'
        verbose_name_plural = 'Employee HR profiles'

    def __str__(self):
        return f'HR profile: {self.employee}'


class PayrollSettings(BaseModel):
    """Singleton row (pk=1) — payroll calculation defaults."""

    late_deduction_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    working_days_in_month = models.PositiveIntegerField(default=26)
    overtime_rate_multiplier = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('1.50'))
    hr_notification_email = models.EmailField(
        blank=True,
        help_text='Daily/monthly HR alerts; falls back to company email if empty.',
    )
    iloe_deduct_via_payroll = models.BooleanField(
        default=True,
        help_text=(
            'If enabled, UAE ILOE (premium plus 5% VAT) is deducted from net salary. '
            'If disabled, the payslip shows the amount as a reminder only; employees typically pay via iloe.ae.'
        ),
    )

    class Meta:
        verbose_name = 'Payroll settings'
        verbose_name_plural = 'Payroll settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class AttendanceSettings(BaseModel):
    """Singleton (pk=1) — shift rules for attendance auto-calculations and payroll hooks."""

    shift_start = models.TimeField(default=time(9, 0))
    shift_end = models.TimeField(default=time(18, 0))
    working_hours_per_day = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('9.00'))
    late_threshold_minutes = models.PositiveIntegerField(default=15)
    half_day_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4.50'))
    overtime_threshold_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('9.00'))
    late_deduction_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    overtime_rate_multiplier = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('1.50'),
        help_text='Legacy single multiplier (non-UAE payroll path only).',
    )
    overtime_rate_normal = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('1.25'),
        help_text='Daytime OT multiplier (UAE payroll). Hourly rate = (basic × 12) / 365 / 8.',
    )
    overtime_rate_night = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('1.50'),
        help_text='Night OT multiplier (check-out 22:00–04:00, or set manually on the record).',
    )
    overtime_rate_holiday = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('1.50'),
        help_text='Worked time on a public holiday (all hours treated as OT with this multiplier).',
    )
    auto_mark_absent = models.BooleanField(default=True)
    working_days_in_month = models.PositiveIntegerField(
        default=22,
        help_text='Default denominator for per-day salary when calendar working-day count is not used.',
    )

    class Meta:
        verbose_name = 'Attendance settings'
        verbose_name_plural = 'Attendance settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return 'Attendance settings'


class Holiday(BaseModel):
    LOCATION_SCOPE = [
        ('uae', 'UAE'),
        ('ksa', 'KSA'),
        ('both', 'Both'),
    ]

    name = models.CharField(max_length=200)
    date = models.DateField(db_index=True)
    location = models.CharField(max_length=10, choices=LOCATION_SCOPE, default='both')
    is_recurring = models.BooleanField(default=False)

    class Meta:
        ordering = ['date', 'name']
        verbose_name = 'Holiday'

    def __str__(self):
        return f'{self.name} ({self.date})'


class AttendanceRecord(BaseModel):
    OVERTIME_TYPE_CHOICES = [
        ('normal', 'Normal (daytime)'),
        ('night', 'Night (22:00–04:00)'),
        ('holiday', 'Public holiday'),
    ]
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('import', 'Import'),
        ('biometric', 'Biometric'),
        ('public_link', 'Public link'),
        ('self_service', 'Self-service'),
    ]
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half day'),
        ('weekend', 'Weekend'),
        ('holiday', 'Holiday'),
    ]

    employee = models.ForeignKey('hr.Employee', on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField(db_index=True)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    check_in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    notes = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_records',
        help_text='Optional job / site — use for technician labour on a project.',
    )

    working_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    late_minutes = models.PositiveIntegerField(default=0)
    overtime_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    overtime_type = models.CharField(
        max_length=20,
        choices=OVERTIME_TYPE_CHOICES,
        default='normal',
        help_text='Used for payroll OT rate (normal / night / holiday).',
    )

    class Meta:
        ordering = ['-date', '-check_in', '-pk']

    def __str__(self):
        return f'{self.employee.employee_code} {self.date}'

    def save(self, *args, **kwargs):
        from apps.hr.attendance_utils import apply_auto_calculations_to_record

        apply_auto_calculations_to_record(self)
        super().save(*args, **kwargs)


class AttendanceSummary(BaseModel):
    employee = models.ForeignKey('hr.Employee', on_delete=models.CASCADE, related_name='attendance_summaries')
    month = models.DateField(help_text='First day of calendar month')
    year = models.PositiveIntegerField(editable=False)
    total_working_days = models.PositiveIntegerField(default=0)
    total_present = models.PositiveIntegerField(default=0)
    total_absent = models.PositiveIntegerField(default=0)
    total_late = models.PositiveIntegerField(default=0)
    total_half_day = models.PositiveIntegerField(default=0)
    total_holidays = models.PositiveIntegerField(default=0)
    total_overtime_hours = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_late_minutes = models.PositiveIntegerField(default=0)
    total_working_hours = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    absent_deduction_days = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    is_finalized = models.BooleanField(default=False)

    class Meta:
        ordering = ['-month']
        unique_together = [['employee', 'month']]

    def save(self, *args, **kwargs):
        self.year = self.month.year
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.employee_id} {self.month:%Y-%m}'


class PayrollAllowanceLine(BaseModel):
    """Itemized allowances; Payroll.allowances should equal the sum of amounts."""

    SOURCE_MANUAL = 'manual'
    SOURCE_AUTO = 'auto'
    SOURCE_ATTENDANCE = 'attendance'
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, 'Manual'),
        (SOURCE_AUTO, 'Auto'),
        (SOURCE_ATTENDANCE, 'Attendance'),
    ]

    CODE_HOUSING = 'HOUSING'
    CODE_TRANSPORT = 'TRANSPORT'
    CODE_FOOD = 'FOOD'
    CODE_PHONE = 'PHONE'
    CODE_EDUCATION = 'EDUCATION'
    CODE_CAR = 'CAR'
    CODE_CLOTHING = 'CLOTHING'
    CODE_OTHER = 'OTHER'
    CODE_OVERTIME = 'OVERTIME'
    CODE_COMMISSION = 'COMMISSION'
    CODE_ALLOWANCE_EXPENSE = 'PAYROLL_ALLOW_EXP'

    payroll = models.ForeignKey('hr.Payroll', on_delete=models.CASCADE, related_name='allowance_lines')
    code = models.CharField(max_length=40)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    is_taxable = models.BooleanField(default=False)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)

    class Meta:
        ordering = ['payroll_id', 'pk']

    def __str__(self):
        return f'{self.code}: {self.amount}'


class EmployeeAdvance(BaseModel):
    """Salary advance / loan to be recovered via payroll deductions."""

    TYPE_SALARY_ADVANCE = 'salary_advance'
    TYPE_LOAN = 'loan'
    TYPE_OTHER = 'other'
    ADVANCE_TYPE_CHOICES = [
        (TYPE_SALARY_ADVANCE, 'Salary Advance'),
        (TYPE_LOAN, 'Loan'),
        (TYPE_OTHER, 'Other'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_FULLY_REPAID = 'fully_repaid'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_FULLY_REPAID, 'Fully repaid'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    FREQ_MONTHLY = 'monthly'
    FREQ_3_MONTH = '3_month'
    FREQ_6_MONTH = '6_month'
    FREQ_YEARLY = 'yearly'
    FREQ_ONE_TIME = 'one_time'
    FREQ_OTHER = 'other'
    REPAYMENT_FREQUENCY_CHOICES = [
        (FREQ_MONTHLY, 'Monthly'),
        (FREQ_3_MONTH, 'Every 3 months'),
        (FREQ_6_MONTH, 'Every 6 months'),
        (FREQ_YEARLY, 'Yearly'),
        (FREQ_ONE_TIME, 'One time'),
        (FREQ_OTHER, 'Other'),
    ]
    REPAYMENT_INTERVAL_BY_FREQUENCY = {
        FREQ_MONTHLY: 1,
        FREQ_3_MONTH: 3,
        FREQ_6_MONTH: 6,
        FREQ_YEARLY: 12,
        FREQ_ONE_TIME: 0,
    }

    employee = models.ForeignKey('hr.Employee', on_delete=models.CASCADE, related_name='advances')
    advance_type = models.CharField(max_length=20, choices=ADVANCE_TYPE_CHOICES, default=TYPE_SALARY_ADVANCE)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_employee_advances',
    )
    date_issued = models.DateField()
    repayment_frequency = models.CharField(
        max_length=20,
        choices=REPAYMENT_FREQUENCY_CHOICES,
        default=FREQ_MONTHLY,
    )
    repayment_period = models.PositiveIntegerField(
        default=1,
        help_text='Number of installments (e.g. 5 monthly deductions).',
    )
    repayment_interval_months = models.PositiveIntegerField(
        default=1,
        help_text='Months between each installment (auto-set from frequency; editable for Other).',
    )
    repayment_months = models.PositiveIntegerField(default=1)
    monthly_deduction = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    amount_repaid = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    amount_remaining = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_issued', '-pk']

    def __str__(self):
        return f'{self.employee.employee_code} {self.get_advance_type_display()} {self.amount}'

    @staticmethod
    def _month_first(d: date) -> date:
        return date(d.year, d.month, 1)

    @staticmethod
    def _months_between(start: date, end: date) -> int:
        return (end.year - start.year) * 12 + (end.month - start.month)

    def _sync_repayment_schedule(self) -> None:
        freq = self.repayment_frequency or self.FREQ_MONTHLY
        if freq == self.FREQ_ONE_TIME:
            self.repayment_period = 1
            self.repayment_interval_months = 0
            self.repayment_months = 1
            self.monthly_deduction = (self.amount or Decimal('0')).quantize(Decimal('0.01'))
            return

        period = max(1, int(self.repayment_period or 1))
        self.repayment_period = period

        if freq == self.FREQ_OTHER:
            interval = max(1, int(self.repayment_interval_months or 1))
        else:
            interval = self.REPAYMENT_INTERVAL_BY_FREQUENCY.get(freq, 1)
        self.repayment_interval_months = interval
        self.repayment_months = (period - 1) * interval + 1
        self.monthly_deduction = (
            (self.amount or Decimal('0')) / Decimal(period)
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def is_due_for_payroll_month(self, payroll_month: date) -> bool:
        if self.status != self.STATUS_ACTIVE or (self.amount_remaining or Decimal('0')) <= 0:
            return False

        start = self._month_first(self.date_issued)
        month = self._month_first(payroll_month)
        offset = self._months_between(start, month)
        if offset < 0:
            return False

        paid_installments = self.repayments.count()
        period = max(1, int(self.repayment_period or 1))
        if paid_installments >= period:
            return False

        if self.repayment_frequency == self.FREQ_ONE_TIME:
            return paid_installments == 0

        interval = max(1, int(self.repayment_interval_months or 1))
        expected_offset = paid_installments * interval
        return offset == expected_offset

    def installment_amount_for_payroll(self) -> Decimal:
        rem = (self.amount_remaining or Decimal('0')).quantize(Decimal('0.01'))
        inst = (self.monthly_deduction or Decimal('0')).quantize(Decimal('0.01'))
        if inst <= 0:
            return rem
        return min(inst, rem)

    def save(self, *args, **kwargs):
        self._sync_repayment_schedule()
        if self.pk is None:
            self.amount_remaining = (self.amount - (self.amount_repaid or Decimal('0'))).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class AdvanceRepayment(BaseModel):
    """One payroll (or manual) recovery against an advance."""

    advance = models.ForeignKey(EmployeeAdvance, on_delete=models.CASCADE, related_name='repayments')
    payroll = models.ForeignKey(
        'hr.Payroll',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='advance_repayments',
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date', '-pk']

    def __str__(self):
        return f'Repay {self.advance_id} {self.amount}'


class EmployeeSalaryDeduction(BaseModel):
    """Fines, penalties, and similar salary cuts — not loans or advances."""

    CATEGORY_FINE = 'fine'
    CATEGORY_PENALTY = 'penalty'
    CATEGORY_DAMAGE = 'damage'
    CATEGORY_OTHER = 'other'
    CATEGORY_CHOICES = [
        (CATEGORY_FINE, 'Fine'),
        (CATEGORY_PENALTY, 'Penalty'),
        (CATEGORY_DAMAGE, 'Damage / loss'),
        (CATEGORY_OTHER, 'Other'),
    ]

    FREQ_MONTHLY = 'monthly'
    FREQ_ONE_TIME = 'one_time'
    FREQUENCY_CHOICES = [
        (FREQ_MONTHLY, 'Monthly'),
        (FREQ_ONE_TIME, 'One-time'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_CANCELLED = 'cancelled'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='salary_deductions',
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_FINE)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    description = models.TextField(blank=True)
    payment_frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default=FREQ_MONTHLY,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_salary_deductions',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.employee.employee_code} {self.get_category_display()} {self.amount}'

    @staticmethod
    def _month_first(d: date) -> date:
        return date(d.year, d.month, 1)

    def is_applicable_for_payroll_month(self, month_first: date) -> bool:
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.effective_from and month_first < self._month_first(self.effective_from):
            return False
        if self.effective_to and month_first > self._month_first(self.effective_to):
            return False
        if self.payment_frequency == self.FREQ_ONE_TIME and self.applications.exists():
            return False
        return True


class SalaryDeductionApplication(BaseModel):
    """Payroll recovery against a salary deduction record."""

    salary_deduction = models.ForeignKey(
        EmployeeSalaryDeduction,
        on_delete=models.CASCADE,
        related_name='applications',
    )
    payroll = models.ForeignKey(
        'hr.Payroll',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='salary_deduction_applications',
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date', '-pk']

    def __str__(self):
        return f'Salary deduction {self.salary_deduction_id} {self.amount}'


class EmployeeAllowanceExpense(BaseModel):
    """Recurring allowances and expense reimbursements paid via payroll."""

    CATEGORY_ALLOW_HOUSING = 'allow_housing'
    CATEGORY_ALLOW_TRANSPORT = 'allow_transport'
    CATEGORY_ALLOW_FOOD = 'allow_food'
    CATEGORY_ALLOW_PHONE = 'allow_phone'
    CATEGORY_ALLOW_OTHER = 'allow_other'
    CATEGORY_EXP_TRAVEL = 'exp_travel'
    CATEGORY_EXP_FUEL = 'exp_fuel'
    CATEGORY_EXP_MEALS = 'exp_meals'
    CATEGORY_EXP_ACCOMMODATION = 'exp_accommodation'
    CATEGORY_EXP_SUPPLIES = 'exp_supplies'
    CATEGORY_EXP_OTHER = 'exp_other'
    CATEGORY_CHOICES = [
        (CATEGORY_ALLOW_HOUSING, 'Allowance — Housing'),
        (CATEGORY_ALLOW_TRANSPORT, 'Allowance — Transport'),
        (CATEGORY_ALLOW_FOOD, 'Allowance — Food'),
        (CATEGORY_ALLOW_PHONE, 'Allowance — Phone'),
        (CATEGORY_ALLOW_OTHER, 'Allowance — Other'),
        (CATEGORY_EXP_TRAVEL, 'Expense — Travel'),
        (CATEGORY_EXP_FUEL, 'Expense — Fuel'),
        (CATEGORY_EXP_MEALS, 'Expense — Meals'),
        (CATEGORY_EXP_ACCOMMODATION, 'Expense — Accommodation'),
        (CATEGORY_EXP_SUPPLIES, 'Expense — Supplies'),
        (CATEGORY_EXP_OTHER, 'Expense — Other'),
    ]
    EXPENSE_CATEGORY_PREFIX = 'exp_'

    FREQ_MONTHLY = 'monthly'
    FREQ_ONE_TIME = 'one_time'
    FREQUENCY_CHOICES = [
        (FREQ_MONTHLY, 'Monthly'),
        (FREQ_ONE_TIME, 'One-time'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_CANCELLED = 'cancelled'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='allowance_expenses',
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default=CATEGORY_ALLOW_OTHER)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    description = models.TextField(blank=True)
    payment_frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default=FREQ_MONTHLY,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    start_date = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_allowance_expenses',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.employee.employee_code} {self.get_category_display()} {self.amount}'

    @property
    def is_expense(self) -> bool:
        return (self.category or '').startswith(self.EXPENSE_CATEGORY_PREFIX)

    @staticmethod
    def _month_first(d: date) -> date:
        return date(d.year, d.month, 1)

    @staticmethod
    def payroll_month_for_expense(d: date) -> date:
        """Expenses before the 15th pay in that month; on/after the 15th roll to next month."""
        if d.day < 15:
            return date(d.year, d.month, 1)
        y, m = d.year, d.month
        if m == 12:
            return date(y + 1, 1, 1)
        return date(y, m + 1, 1)

    def first_payroll_month(self) -> date | None:
        if not self.start_date:
            return None
        if self.is_expense:
            return self.payroll_month_for_expense(self.start_date)
        return self._month_first(self.start_date)

    def is_applicable_for_payroll_month(self, payroll_month: date) -> bool:
        if self.status != self.STATUS_ACTIVE:
            return False
        month = self._month_first(payroll_month)
        if self.effective_to and month > self._month_first(self.effective_to):
            return False

        first = self.first_payroll_month()
        if first and month < first:
            return False

        if self.payment_frequency == self.FREQ_ONE_TIME:
            if self.applications.exists():
                return False
            if first:
                return month == first
            return True

        if self.applications.filter(payroll__month=month).exists():
            return False
        return True


class AllowanceExpenseApplication(BaseModel):
    """Payroll payment against an allowance / expense record."""

    allowance_expense = models.ForeignKey(
        EmployeeAllowanceExpense,
        on_delete=models.CASCADE,
        related_name='applications',
    )
    payroll = models.ForeignKey(
        'hr.Payroll',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='allowance_expense_applications',
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date', '-pk']

    def __str__(self):
        return f'Allowance/expense {self.allowance_expense_id} {self.amount}'


class EmployeeCommission(BaseModel):
    """Monthly sales commission for payroll."""

    STATUS_ACTIVE = 'active'
    STATUS_PAID = 'paid'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PAID, 'Paid via payroll'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='commissions',
    )
    month = models.DateField(help_text='First day of the commission month.')
    total_sales = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    commission_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_employee_commissions',
    )
    payroll = models.ForeignKey(
        'hr.Payroll',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_commissions',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-month', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'month'],
                condition=models.Q(is_active=True),
                name='hr_employeecommission_unique_active_employee_month',
            ),
        ]

    def __str__(self):
        return f'{self.employee_id} {self.month:%Y-%m} commission {self.commission_amount}'

    @staticmethod
    def month_first(d: date) -> date:
        return date(d.year, d.month, 1)


class PayrollTemplate(BaseModel):
    """Reusable salary structure for draft payroll generation."""

    LOCATION_BOTH = 'both'
    LOCATION_UAE = 'uae'
    LOCATION_KSA = 'ksa'
    LOCATION_CHOICES = [
        (LOCATION_UAE, 'UAE'),
        (LOCATION_KSA, 'KSA'),
        (LOCATION_BOTH, 'Both'),
    ]

    name = models.CharField(max_length=200)
    company = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_templates',
    )
    location = models.CharField(max_length=10, choices=LOCATION_CHOICES, default=LOCATION_BOTH)
    basic_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        blank=True,
        help_text='Optional reference amount on the template; employee basic is used when generating payroll.',
    )
    allowance_lines = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_allowances_amount(self) -> Decimal:
        from apps.hr.salary_payroll_utils import template_allowances_total

        return template_allowances_total(self)

    @property
    def total_package_amount(self) -> Decimal:
        b = self.basic_salary or Decimal('0')
        return (b + self.total_allowances_amount).quantize(Decimal('0.01'))


class PayrollDeductionLine(BaseModel):
    """Itemized deductions affecting net salary (stored separately; Payroll.deductions holds total)."""

    CODE_ABSENT = 'absent'
    CODE_LATE = 'late'
    CODE_UNPAID_LEAVE = 'unpaid_leave'
    CODE_HALF_PAY_LEAVE = 'HALF_PAY_LEAVE'
    CODE_SICK_TIERED = 'SICK_HALF_PAY'
    CODE_ILOE = 'ILOE'
    CODE_GOSI_EMPLOYEE = 'gosi_employee'
    CODE_OTHER = 'other'
    CODE_MANUAL = 'manual_misc'
    CODE_ADVANCE_REPAYMENT = 'advance_repayment'
    CODE_SALARY_DEDUCTION = 'salary_deduction'

    payroll = models.ForeignKey('hr.Payroll', on_delete=models.CASCADE, related_name='deduction_lines')
    code = models.CharField(max_length=40)
    label = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['payroll_id', 'code']

    def __str__(self):
        return f'{self.label}: {self.amount}'


class PayrollEmployerContribution(BaseModel):
    """Employer-side stats (e.g. GOSI employer) — informational on payslip, not net deductions."""

    CODE_GOSI_EMPLOYER = 'gosi_employer'

    payroll = models.ForeignKey('hr.Payroll', on_delete=models.CASCADE, related_name='employer_contributions')
    code = models.CharField(max_length=40, blank=True, db_index=True)
    label = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['payroll_id']


class UAECompliance(BaseModel):
    """UAE-specific documents & payroll flags (OneToOne — Emirates ID / visa stay on Employee)."""

    VISA_TYPE_CHOICES = [
        ('employment', 'Employment'),
        ('residence', 'Residence'),
        ('investor', 'Investor'),
        ('other', 'Other'),
    ]

    employee = models.OneToOneField('hr.Employee', on_delete=models.CASCADE, related_name='uae_compliance')
    emirates_id_expiry = models.DateField(null=True, blank=True)
    visa_type = models.CharField(max_length=20, choices=VISA_TYPE_CHOICES, blank=True)

    passport_number = models.CharField(max_length=80, blank=True)
    passport_expiry = models.DateField(null=True, blank=True)
    labour_card_number = models.CharField(max_length=80, blank=True)
    labour_card_expiry = models.DateField(null=True, blank=True)

    medical_insurance_provider = models.CharField(max_length=200, blank=True)
    medical_insurance_policy_number = models.CharField(max_length=120, blank=True)
    medical_insurance_expiry = models.DateField(null=True, blank=True)

    unified_number = models.CharField(
        max_length=15,
        blank=True,
        validators=[RegexValidator(r'^(\d{15})?$', 'Enter exactly 15 digits (UID), or leave blank.')],
        help_text='15-digit UAE UID',
    )
    unified_number_expiry = models.DateField(null=True, blank=True)

    iloe_insurance_provider = models.CharField(max_length=200, blank=True)
    iloe_insurance_policy_number = models.CharField(max_length=120, blank=True)
    iloe_insurance_expiry = models.DateField(null=True, blank=True)

    iloe_applicable = models.BooleanField(default=True)
    gratuity_applicable = models.BooleanField(default=True)

    bank_iban = models.CharField(
        max_length=34,
        blank=True,
        help_text='Employee bank IBAN for WPS (overrides HR bank profile if set).',
    )
    bank_routing_code = models.CharField(
        max_length=20,
        blank=True,
        help_text='Employee bank routing code for WPS (overrides HR bank profile if set).',
    )

    visa_expiry_alert_acknowledged = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'UAE compliance'

    def __str__(self):
        return f'UAE compliance: {self.employee}'

    @property
    def visa_expiry_status(self) -> str:
        emp = getattr(self, 'employee', None)
        if not emp:
            return UNKNOWN
        return expiry_band(emp.visa_expiry)

    @property
    def emirates_id_expiry_status(self) -> str:
        return expiry_band(self.emirates_id_expiry)

    @property
    def passport_expiry_status(self) -> str:
        return expiry_band(self.passport_expiry)

    @property
    def labour_card_expiry_status(self) -> str:
        return expiry_band(self.labour_card_expiry)

    @property
    def medical_insurance_expiry_status(self) -> str:
        return expiry_band(self.medical_insurance_expiry)


class KSACompliance(BaseModel):
    NITAQAT_CHOICES = [
        ('platinum', 'Platinum'),
        ('high_green', 'High Green'),
        ('mid_green', 'Mid Green'),
        ('low_green', 'Low Green'),
        ('yellow', 'Yellow'),
        ('red', 'Red'),
    ]
    WORK_PERMIT_CLASSIFICATION_CHOICES = [
        ('professional', 'Professional'),
        ('skilled', 'Skilled'),
        ('semi_skilled', 'Semi-Skilled'),
    ]
    NATIONALITY_CHOICES = [
        ('saudi', 'Saudi'),
        ('non_saudi', 'Non-Saudi'),
    ]

    employee = models.OneToOneField('hr.Employee', on_delete=models.CASCADE, related_name='ksa_compliance')
    iqama_number = models.CharField(
        max_length=9,
        blank=True,
        validators=[RegexValidator(r'^(\d{9})?$', 'Iqama number must be exactly 9 digits, or leave blank.')],
    )
    iqama_expiry = models.DateField(null=True, blank=True)
    iqama_profession = models.CharField(max_length=200, blank=True)

    work_permit_number = models.CharField(max_length=80, blank=True)
    work_permit_expiry = models.DateField(null=True, blank=True)
    work_permit_classification = models.CharField(
        max_length=20,
        choices=WORK_PERMIT_CLASSIFICATION_CHOICES,
        blank=True,
    )

    passport_number = models.CharField(max_length=80, blank=True)
    passport_expiry = models.DateField(null=True, blank=True)

    medical_insurance_provider = models.CharField(max_length=200, blank=True)
    medical_insurance_policy_number = models.CharField(max_length=120, blank=True)
    medical_insurance_expiry = models.DateField(null=True, blank=True)

    muqeem_number = models.CharField(max_length=80, blank=True)
    muqeem_expiry = models.DateField(null=True, blank=True)
    absher_id = models.CharField(max_length=80, blank=True)

    nationality = models.CharField(max_length=20, choices=NATIONALITY_CHOICES, default='non_saudi')
    gosi_number = models.CharField(max_length=80, blank=True)
    gosi_applicable = models.BooleanField(default=True)

    nitaqat_category = models.CharField(max_length=20, choices=NITAQAT_CHOICES, blank=True)
    qiwa_contract_registered = models.BooleanField(default=False)
    mudad_wps_enrolled = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'KSA compliance'

    def __str__(self):
        return f'KSA compliance: {self.employee}'

    @property
    def iqama_expiry_status(self) -> str:
        return expiry_band(self.iqama_expiry)

    @property
    def work_permit_expiry_status(self) -> str:
        return expiry_band(self.work_permit_expiry)

    @property
    def passport_expiry_status(self) -> str:
        return expiry_band(self.passport_expiry)

    @property
    def medical_insurance_expiry_status(self) -> str:
        return expiry_band(self.medical_insurance_expiry)


class GratuityRecord(BaseModel):
    employee = models.ForeignKey('hr.Employee', on_delete=models.CASCADE, related_name='gratuity_records')
    payroll = models.ForeignKey(
        'hr.Payroll',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gratuity_snapshots',
    )
    as_of_date = models.DateField()
    years_of_service = models.DecimalField(max_digits=8, decimal_places=2)
    provision_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-as_of_date']

    def __str__(self):
        return f'Gratuity {self.employee_id} {self.as_of_date}'


class GratuitySnapshot(BaseModel):
    """Optional audit trail for UAE end-of-service gratuity calculations."""

    employee = models.ForeignKey('hr.Employee', on_delete=models.CASCADE, related_name='gratuity_eos_snapshots')
    snapshot_date = models.DateField()
    years_of_service = models.DecimalField(max_digits=8, decimal_places=2)
    daily_rate = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    calculated_gratuity = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    adjustment_factor = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('1.0000'))
    final_gratuity = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-snapshot_date', '-pk']
        verbose_name = 'Gratuity snapshot'
        verbose_name_plural = 'Gratuity snapshots'

    def __str__(self):
        return f'EOSG snapshot {self.employee_id} {self.snapshot_date}'


class GOSIRecord(BaseModel):
    payroll = models.ForeignKey('hr.Payroll', on_delete=models.CASCADE, related_name='gosi_records')
    employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.CASCADE,
        related_name='gosi_records',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'settings_app.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gosi_records',
    )
    month = models.DateField(null=True, blank=True, help_text='First day of payroll month')
    basic_salary = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    nationality = models.CharField(max_length=20, blank=True)
    gosi_number = models.CharField(max_length=80, blank=True)
    iqama_number = models.CharField(max_length=20, blank=True)
    employee_rate = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('0'))
    employer_rate = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('0'))
    employee_contribution = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    employer_contribution = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_contribution = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    gross_up_basic_for_rates = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        unique_together = [['payroll']]


class EmployeeBankDetail(BaseModel):
    """Employee bank routing for WPS (UAE)."""

    employee = models.OneToOneField('hr.Employee', on_delete=models.CASCADE, related_name='bank_detail')
    bank_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=64, blank=True)
    iban = models.CharField(max_length=50, blank=True)
    routing_bank_code = models.CharField(max_length=20, blank=True, help_text='Agent ID / routing as required by bank')

    def __str__(self):
        return f'Bank {self.employee.employee_code}'


class WPSRecord(BaseModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('confirmed', 'Confirmed'),
    ]

    employee = models.ForeignKey('hr.Employee', on_delete=models.CASCADE, related_name='wps_records')
    payroll = models.OneToOneField('hr.Payroll', on_delete=models.CASCADE, related_name='wps_record')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField(null=True, blank=True)
    bank_account = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wps_records',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    batch_reference = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['-payment_date', '-pk']


class WPSMonthlyFile(BaseModel):
    """Generated SIF batch metadata per employer/month."""

    month = models.DateField(help_text='First day of month')
    file_content = models.TextField(blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    all_payrolls_paid = models.BooleanField(default=False)

    class Meta:
        unique_together = [['month']]
        ordering = ['-month']


def validate_emirates_id_format(value: str) -> None:
    """784-YYYY-XXXXXXX-X"""
    import re

    if not value or not value.strip():
        return
    s = value.strip()
    if not re.match(r'^784-\d{4}-\d{7}-\d$', s):
        raise ValidationError(
            'Emirates ID must match format 784-YYYY-XXXXXXX-X',
            code='invalid_eid',
        )

