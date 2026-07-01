from django.contrib import admin

from .models import (
    AdvanceRepayment,
    AttendanceRecord,
    AttendanceSettings,
    AttendanceSummary,
    Holiday,
    Department,
    Designation,
    Employee,
    EmployeeAdvance,
    EmployeeAllowanceExpense,
    EmployeeCommission,
    EmployeeSalaryDeduction,
    EmployeeBankDetail,
    EmployeeHRProfile,
    GOSIRecord,
    GratuityRecord,
    GratuitySnapshot,
    KSACompliance,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Payroll,
    PayrollAllowanceLine,
    PayrollDeductionLine,
    PayrollEmployerContribution,
    PayrollSettings,
    PayrollTemplate,
    SalaryDeductionApplication,
    AllowanceExpenseApplication,
    UAECompliance,
    WPSMonthlyFile,
    WPSRecord,
)

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'manager']

@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ['name', 'department']

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['employee_code', 'first_name', 'last_name', 'user', 'company', 'department', 'designation', 'status']
    list_filter = ['status', 'department', 'location']

@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'location', 'pay_type', 'days_allowed', 'is_active']
    list_filter = ['location', 'pay_type', 'is_active']


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ['employee', 'leave_type', 'year', 'entitled_days', 'used_days', 'pending_days', 'carried_forward']
    list_filter = ['year', 'leave_type']


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ['employee', 'leave_type', 'start_date', 'end_date', 'status', 'reference_number', 'approved_by']
    list_filter = ['status', 'leave_type']

@admin.register(PayrollAllowanceLine)
class PayrollAllowanceLineAdmin(admin.ModelAdmin):
    list_display = ['payroll', 'code', 'description', 'amount', 'source']
    list_filter = ['source']


@admin.register(PayrollTemplate)
class PayrollTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'company', 'location', 'basic_salary', 'is_active']
    list_filter = ['location', 'is_active']


@admin.register(EmployeeAdvance)
class EmployeeAdvanceAdmin(admin.ModelAdmin):
    list_display = [
        'employee',
        'advance_type',
        'amount',
        'amount_repaid',
        'amount_remaining',
        'repayment_frequency',
        'repayment_period',
        'monthly_deduction',
        'status',
        'date_issued',
    ]
    list_filter = ['status', 'advance_type', 'repayment_frequency', 'date_issued']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code']
    raw_id_fields = ['employee', 'approved_by']


@admin.register(AdvanceRepayment)
class AdvanceRepaymentAdmin(admin.ModelAdmin):
    list_display = ['advance', 'payroll', 'amount', 'date']
    list_filter = ['date']
    raw_id_fields = ['advance', 'payroll']


@admin.register(EmployeeSalaryDeduction)
class EmployeeSalaryDeductionAdmin(admin.ModelAdmin):
    list_display = [
        'employee',
        'category',
        'amount',
        'payment_frequency',
        'status',
        'effective_from',
        'effective_to',
    ]
    list_filter = ['status', 'category', 'payment_frequency']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code', 'description']
    raw_id_fields = ['employee', 'approved_by']


@admin.register(SalaryDeductionApplication)
class SalaryDeductionApplicationAdmin(admin.ModelAdmin):
    list_display = ['salary_deduction', 'payroll', 'amount', 'date']
    list_filter = ['date']
    raw_id_fields = ['salary_deduction', 'payroll']


@admin.register(EmployeeAllowanceExpense)
class EmployeeAllowanceExpenseAdmin(admin.ModelAdmin):
    list_display = [
        'employee',
        'category',
        'amount',
        'payment_frequency',
        'status',
        'start_date',
        'effective_to',
    ]
    list_filter = ['status', 'category', 'payment_frequency']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code', 'description']
    raw_id_fields = ['employee', 'approved_by']


@admin.register(AllowanceExpenseApplication)
class AllowanceExpenseApplicationAdmin(admin.ModelAdmin):
    list_display = ['allowance_expense', 'payroll', 'amount', 'date']
    list_filter = ['date']
    raw_id_fields = ['allowance_expense', 'payroll']


@admin.register(Payroll)
class PayrollAdmin(admin.ModelAdmin):
    list_display = ['employee', 'company', 'month', 'basic_salary', 'net_salary', 'status', 'payslip_email_sent']
    list_filter = ['status', 'month']


@admin.register(PayrollSettings)
class PayrollSettingsAdmin(admin.ModelAdmin):
    list_display = [
        'pk', 'late_deduction_amount', 'working_days_in_month', 'iloe_deduct_via_payroll',
        'hr_notification_email', 'birthday_email_enabled',
    ]


@admin.register(EmployeeHRProfile)
class EmployeeHRProfileAdmin(admin.ModelAdmin):
    list_display = [
        'employee',
        'employment_entity',
        'gosi_employee_category',
        'commission_type',
        'commission_percentage',
        'commission_fixed_amount',
    ]
    list_filter = ['employment_entity', 'commission_type']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code']
    raw_id_fields = ['employee']


@admin.register(EmployeeCommission)
class EmployeeCommissionAdmin(admin.ModelAdmin):
    list_display = ['employee', 'month', 'total_sales', 'commission_amount', 'status', 'approved_by', 'payroll']
    list_filter = ['status', 'month']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code']
    raw_id_fields = ['employee', 'approved_by', 'payroll']


@admin.register(AttendanceSettings)
class AttendanceSettingsAdmin(admin.ModelAdmin):
    list_display = ['pk', 'shift_start', 'shift_end', 'working_hours_per_day', 'auto_mark_absent']


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'location', 'is_recurring', 'is_active']
    list_filter = ['location', 'is_recurring', 'is_active']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = [
        'employee',
        'date',
        'project',
        'status',
        'check_in',
        'check_out',
        'working_hours',
        'late_minutes',
        'overtime_hours',
        'overtime_type',
        'source',
    ]
    list_filter = ['status', 'source', 'overtime_type']
    raw_id_fields = ['project']


@admin.register(AttendanceSummary)
class AttendanceSummaryAdmin(admin.ModelAdmin):
    list_display = [
        'employee',
        'month',
        'total_present',
        'total_absent',
        'total_late',
        'total_half_day',
        'total_holidays',
        'total_overtime_hours',
        'total_working_hours',
        'absent_deduction_days',
        'is_finalized',
    ]
    list_filter = ['is_finalized']


@admin.register(PayrollDeductionLine)
class PayrollDeductionLineAdmin(admin.ModelAdmin):
    list_display = ['payroll', 'code', 'label', 'amount']


@admin.register(PayrollEmployerContribution)
class PayrollEmployerContributionAdmin(admin.ModelAdmin):
    list_display = ['payroll', 'code', 'label', 'amount']


@admin.register(UAECompliance)
class UAEComplianceAdmin(admin.ModelAdmin):
    list_display = ['employee', 'passport_expiry', 'medical_insurance_expiry']


@admin.register(KSACompliance)
class KSAComplianceAdmin(admin.ModelAdmin):
    list_display = ['employee', 'iqama_expiry', 'nationality', 'gosi_number', 'nitaqat_category']


@admin.register(GratuityRecord)
class GratuityRecordAdmin(admin.ModelAdmin):
    list_display = ['employee', 'payroll', 'as_of_date', 'provision_amount']


@admin.register(GratuitySnapshot)
class GratuitySnapshotAdmin(admin.ModelAdmin):
    list_display = ['employee', 'snapshot_date', 'years_of_service', 'final_gratuity']
    raw_id_fields = ['employee']


@admin.register(GOSIRecord)
class GOSIRecordAdmin(admin.ModelAdmin):
    list_display = [
        'payroll',
        'employee',
        'month',
        'nationality',
        'basic_salary',
        'employee_contribution',
        'employer_contribution',
        'total_contribution',
    ]
    list_filter = ['month', 'nationality']
    raw_id_fields = ['payroll', 'employee', 'company']


@admin.register(EmployeeBankDetail)
class EmployeeBankDetailAdmin(admin.ModelAdmin):
    list_display = ['employee', 'bank_name', 'account_number', 'iban', 'routing_bank_code']


@admin.register(WPSRecord)
class WPSRecordAdmin(admin.ModelAdmin):
    list_display = ['employee', 'payroll', 'amount', 'status', 'payment_date']


@admin.register(WPSMonthlyFile)
class WPSMonthlyFileAdmin(admin.ModelAdmin):
    list_display = ['month', 'all_payrolls_paid', 'generated_at']

