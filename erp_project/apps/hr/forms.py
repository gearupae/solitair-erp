from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as CoreValidationError
from django.db.models import Q, Sum, F, IntegerField
from django.db import models
from datetime import datetime, date
from .models import Department, Designation, Employee, LeaveType, LeaveRequest, Payroll
from .models_extended import EmployeeBankDetail, PayrollTemplate
from .salary_payroll_utils import template_allowances_total
from apps.settings_app.models import Role, Company


class MonthInput(forms.DateInput):
    """Custom widget for month input that converts YYYY-MM to first day of month."""
    input_type = 'month'
    
    def value_from_datadict(self, data, files, name):
        value = data.get(name)
        if value:
            # Convert YYYY-MM format to YYYY-MM-01 (first day of month)
            try:
                # Parse the month value (YYYY-MM)
                if isinstance(value, str) and len(value) == 7 and value.count('-') == 1:
                    year, month = value.split('-')
                    # Validate year and month
                    year_int = int(year)
                    month_int = int(month)
                    if 1 <= month_int <= 12:
                        # Return first day of the month in YYYY-MM-DD format
                        return f"{year}-{month:0>2}-01"
            except (ValueError, AttributeError, TypeError):
                pass
        return value
    
    def format_value(self, value):
        """Format date value to YYYY-MM for month input."""
        if value:
            if isinstance(value, str):
                # If already in YYYY-MM-DD format, extract YYYY-MM
                if len(value) >= 7:
                    return value[:7]
            elif hasattr(value, 'strftime'):
                # If it's a date object, format as YYYY-MM
                return value.strftime('%Y-%m')
        return value

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'manager']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-select' if name == 'manager' else 'form-control'

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'employee_code',
            'user',
            'first_name',
            'last_name',
            'email',
            'phone',
            'gender',
            'department',
            'designation',
            'company',
            'location',
            'date_of_birth',
            'date_of_joining',
            'probation_period_days',
            'status',
            'basic_salary',
            'salary_template',
            'emirates_id',
            'visa_number',
            'visa_expiry',
        ]
        labels = {
            'user': 'ERP login',
        }
        widgets = {
            # Match contracts/finance: explicit form-control + ISO format for HTML5 date inputs
            'date_of_birth': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'},
                format='%Y-%m-%d',
            ),
            'date_of_joining': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'},
                format='%Y-%m-%d',
            ),
            'visa_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'},
                format='%Y-%m-%d',
            ),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter to only show active departments
        department_queryset = Department.objects.filter(is_active=True)
        
        # If editing, include the current department even if inactive
        if self.instance and self.instance.pk:
            if self.instance.department_id:
                department_queryset = Department.objects.filter(
                    Q(is_active=True) | Q(pk=self.instance.department_id)
                )
        
        self.fields['department'].queryset = department_queryset.order_by('name')
        self.fields['department'].empty_label = '-- Select Department --'

        self.fields['salary_template'].queryset = PayrollTemplate.objects.filter(is_active=True).order_by('name')
        self.fields['salary_template'].required = False
        self.fields['salary_template'].empty_label = '— None —'
        self.fields['salary_template'].widget.attrs['class'] = 'form-select'
        self.fields['salary_template'].help_text = (
            'Optional. Allowances will be pulled from the selected template when generating payroll.'
        )

        User = get_user_model()
        user_qs = User.objects.filter(is_active=True).order_by('username', 'email')
        if self.instance and self.instance.pk and self.instance.user_id:
            user_qs = User.objects.filter(Q(is_active=True) | Q(pk=self.instance.user_id)).order_by(
                'username', 'email'
            )
        self.fields['user'].queryset = user_qs
        self.fields['user'].required = False
        self.fields['user'].empty_label = '— None —'
        self.fields['user'].widget.attrs['class'] = 'form-select'
        self.fields['user'].help_text = (
            'Link this person’s Gearup login for clock in/out, self-service, and payslips.'
        )

        role_qs = Role.objects.filter(is_active=True).order_by('name')
        if not self.instance.pk or not self.instance.user_id:
            self.fields.pop('user', None)
            self.fields['portal_role'] = forms.ModelChoiceField(
                label='ERP access role',
                queryset=role_qs,
                required=False,
                empty_label='— Default (Employee role) —',
                widget=forms.Select(attrs={'class': 'form-select'}),
            )

        def _tpl_label(obj):
            tot = template_allowances_total(obj)
            return f'{obj.name} (AED {tot:,.2f} allowances)'

        self.fields['salary_template'].label_from_instance = _tpl_label
        
        # Sync Roles from settings_app to Designations
        # Fetch all active roles and create corresponding designations if they don't exist
        roles = Role.objects.filter(is_active=True).order_by('name')
        for role in roles:
            # Create designation if it doesn't exist (using a default department or None)
            # We'll use the first active department or create without department
            default_dept = Department.objects.filter(is_active=True).first()
            if default_dept:
                Designation.objects.get_or_create(
                    name=role.name,
                    defaults={'department': default_dept}
                )
        
        # Now fetch designations (which should include synced roles)
        designation_queryset = Designation.objects.filter(is_active=True)
        
        # If editing, include the current designation even if inactive
        if self.instance and self.instance.pk:
            if self.instance.designation_id:
                designation_queryset = Designation.objects.filter(
                    Q(is_active=True) | Q(pk=self.instance.designation_id)
                )
        
        self.fields['designation'].queryset = designation_queryset.order_by('name')
        self.fields['designation'].empty_label = '-- Select Designation --'

        company_qs = Company.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.company_id:
            company_qs = Company.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.company_id)
            )
        self.fields['company'].queryset = company_qs.order_by('name')
        self.fields['company'].empty_label = '-- Select Company --'

        self.fields['employee_code'].required = False

        for name, field in self.fields.items():
            if name in [
                'department',
                'designation',
                'status',
                'gender',
                'company',
                'location',
                'user',
                'portal_role',
            ]:
                field.widget.attrs['class'] = 'form-select'
            elif name in ('date_of_birth', 'date_of_joining', 'visa_expiry'):
                field.input_formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
            else:
                field.widget.attrs['class'] = 'form-control'

    def clean_employee_code(self):
        raw = (self.cleaned_data.get('employee_code') or '').strip()
        if not raw:
            if self.instance.pk:
                return self.instance.employee_code
            return ''
        qs = Employee.objects.filter(employee_code__iexact=raw)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This employee code is already in use.')
        return raw

    def clean_user(self):
        u = self.cleaned_data.get('user')
        if u is None:
            return u
        qs = Employee.objects.filter(user=u, is_active=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This login is already linked to another employee.')
        return u

    def clean_emirates_id(self):
        value = (self.cleaned_data.get('emirates_id') or '').strip()
        if not value:
            return value
        from apps.hr.models_extended import validate_emirates_id_format

        validate_emirates_id_format(value)
        return value


class EmployeeBankDetailForm(forms.ModelForm):
    """Optional bank details; persisted only when at least one field is filled."""

    class Meta:
        model = EmployeeBankDetail
        fields = ['bank_name', 'account_number', 'iban', 'routing_bank_code']
        labels = {
            'bank_name': 'Bank name',
            'account_number': 'Account number',
            'iban': 'IBAN',
            'routing_bank_code': 'Routing / agent ID',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.required = False
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['routing_bank_code'].help_text = EmployeeBankDetail._meta.get_field(
            'routing_bank_code'
        ).help_text

    def save_for_employee(self, employee):
        if not self.is_valid():
            raise ValueError('save_for_employee requires a valid form')
        cleaned = self.cleaned_data
        has_any = any((cleaned.get(f) or '').strip() for f in self.Meta.fields)
        existing = getattr(employee, 'bank_detail', None)
        if not has_any:
            if existing:
                existing.delete()
            return None
        obj = super().save(commit=False)
        obj.employee = employee
        obj.save()
        return obj


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = [
            'name',
            'code',
            'location',
            'days_allowed',
            'pay_type',
            'gender_restricted',
            'religion_restricted',
            'requires_medical_certificate',
            'probation_allowed',
            'min_service_days',
            'once_in_service',
            'carry_forward_allowed',
            'carry_forward_cap',
            'is_probation_only',
            'is_gender_specific',
            'gender_required',
            'is_paid',
            'description',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        select_fields = ('location', 'pay_type', 'gender_restricted', 'gender_required')
        for name, field in self.fields.items():
            if name in select_fields:
                field.widget.attrs['class'] = 'form-select'
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault('class', 'form-control')
                field.widget.attrs.setdefault('rows', 3)
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class LeaveRequestForm(forms.ModelForm):
    overflow_action = forms.ChoiceField(
        required=False,
        choices=[
            ('', ''),
            ('reduce', 'Reduce my leave to fit my balance (adjust end date)'),
            ('split', 'Split: paid balance days + remainder as Unpaid Leave'),
        ],
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = LeaveRequest
        fields = ['employee', 'leave_type', 'covering_employee', 'start_date', 'end_date', 'reason', 'medical_certificate']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 2}),
            'medical_certificate': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'covering_employee': 'Reliever',
            'medical_certificate': 'Attachment (e.g. medical certificate)',
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_admin = kwargs.pop('is_admin', False)
        super().__init__(*args, **kwargs)

        self.fields['leave_type'].queryset = LeaveType.objects.filter(is_active=True).order_by('name')
        self.fields['leave_type'].empty_label = '-- Select Leave Type --'

        self.fields['employee'].queryset = Employee.objects.filter(is_active=True).order_by('first_name', 'last_name')
        self.fields['employee'].empty_label = '-- Select Employee --'

        self.fields['covering_employee'].queryset = Employee.objects.filter(is_active=True).order_by(
            'first_name', 'last_name'
        )
        self.fields['covering_employee'].required = False
        self.fields['covering_employee'].empty_label = '— Reliever (optional) —'
        self.fields['covering_employee'].widget.attrs['class'] = 'form-select'

        if self.user and not self.is_admin:
            try:
                employee = Employee.objects.get(user=self.user, is_active=True)
                self.fields['employee'].initial = employee.pk
                self.fields['employee'].widget = forms.HiddenInput()
            except Employee.DoesNotExist:
                pass

        for name, field in self.fields.items():
            if name in ['employee', 'leave_type', 'covering_employee']:
                field.widget.attrs.setdefault('class', 'form-select')
            elif name == 'medical_certificate':
                field.widget.attrs.setdefault('class', 'form-control')
            elif name != 'overflow_action':
                field.widget.attrs['class'] = 'form-control'

    def clean(self):
        from apps.hr.leave_context_service import (
            adjusted_end_date_if_reduce,
            is_effectively_unpaid,
            validate_leave_request_dates_and_balance,
        )

        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        leave_type = cleaned_data.get('leave_type')
        employee = cleaned_data.get('employee')

        raw_overflow = (self.data.get('overflow_action') or '').strip().lower()
        if raw_overflow in ('reduce', 'split'):
            cleaned_data['overflow_action'] = raw_overflow
        else:
            cleaned_data['overflow_action'] = ''

        if not (start_date and end_date and leave_type and employee):
            return cleaned_data

        overflow_action = cleaned_data.get('overflow_action') or ''
        allow_past_start = bool(self.instance.pk)

        eff_end = end_date
        eff_overflow = overflow_action
        if overflow_action == 'reduce' and not is_effectively_unpaid(leave_type):
            eff_end = adjusted_end_date_if_reduce(employee, leave_type, start_date, end_date)
            cleaned_data['end_date'] = eff_end
            eff_overflow = ''

        api_overflow = overflow_action if overflow_action == 'split' else ''

        try:
            validate_leave_request_dates_and_balance(
                employee=employee,
                leave_type=leave_type,
                start_date=start_date,
                end_date=cleaned_data['end_date'],
                overflow_action=api_overflow,
                exclude_leave_pk=self.instance.pk if self.instance.pk else None,
                allow_past_start=allow_past_start,
            )
        except CoreValidationError as exc:
            if getattr(exc, 'message_dict', None):
                raise forms.ValidationError(exc.message_dict)
            raise forms.ValidationError(list(exc.messages))

        reliever = cleaned_data.get('covering_employee')
        if employee and reliever and reliever.pk == employee.pk:
            raise forms.ValidationError({'covering_employee': 'Reliever cannot be the same employee as the applicant.'})

        return cleaned_data


class PublicLeaveApplicationForm(forms.Form):
    employee_code = forms.CharField(max_length=80)
    leave_type = forms.ModelChoiceField(queryset=LeaveType.objects.none())
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}))
    overflow_action = forms.ChoiceField(
        required=False,
        choices=[
            ('', ''),
            ('reduce', 'reduce'),
            ('split', 'split'),
        ],
        widget=forms.HiddenInput(),
    )
    medical_certificate = forms.FileField(required=False, label='Attachment (e.g. medical certificate)')
    reliever = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        required=False,
        label='Reliever',
        empty_label='— Reliever (optional) —',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee_code'].widget.attrs.setdefault('class', 'form-control')
        self.fields['medical_certificate'].widget.attrs.setdefault('class', 'form-control')
        self.fields['leave_type'].empty_label = '— Select leave type —'
        self.fields['leave_type'].queryset = LeaveType.objects.filter(is_active=True).order_by('name')
        self.fields['leave_type'].widget.attrs.setdefault('class', 'form-select')
        self.fields['reliever'].queryset = Employee.objects.filter(is_active=True).order_by('first_name', 'last_name')
        self.fields['reliever'].widget.attrs.setdefault('class', 'form-select')

    def clean(self):
        from apps.hr.leave_context_service import (
            adjusted_end_date_if_reduce,
            is_effectively_unpaid,
            validate_leave_request_dates_and_balance,
        )

        cleaned_data = super().clean()
        code = (cleaned_data.get('employee_code') or '').strip()
        emp = Employee.objects.filter(employee_code__iexact=code, is_active=True).first()
        if not code:
            raise forms.ValidationError({'employee_code': 'Employee code is required.'})
        if not emp:
            raise forms.ValidationError({'employee_code': 'Employee not found.'})

        cleaned_data['employee'] = emp
        reliever = cleaned_data.get('reliever')
        if reliever and reliever.pk == emp.pk:
            raise forms.ValidationError({'reliever': 'Reliever cannot be the same person as the applicant.'})

        leave_type = cleaned_data.get('leave_type')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        raw_overflow = (self.data.get('overflow_action') or '').strip().lower()
        cleaned_data['overflow_action'] = raw_overflow if raw_overflow in ('reduce', 'split') else ''

        if not (leave_type and start_date and end_date):
            return cleaned_data

        overflow_action = cleaned_data['overflow_action']
        eff_end = end_date
        if overflow_action == 'reduce' and not is_effectively_unpaid(leave_type):
            eff_end = adjusted_end_date_if_reduce(emp, leave_type, start_date, end_date)
            cleaned_data['end_date'] = eff_end

        api_overflow = overflow_action if overflow_action == 'split' else ''

        try:
            validate_leave_request_dates_and_balance(
                employee=emp,
                leave_type=leave_type,
                start_date=start_date,
                end_date=cleaned_data['end_date'],
                overflow_action=api_overflow,
                exclude_leave_pk=None,
                allow_past_start=False,
            )
        except CoreValidationError as exc:
            if getattr(exc, 'message_dict', None):
                raise forms.ValidationError(exc.message_dict)
            raise forms.ValidationError(list(exc.messages))

        return cleaned_data


class PayrollForm(forms.ModelForm):
    class Meta:
        model = Payroll
        fields = ['employee', 'company', 'month', 'basic_salary', 'deductions', 'status']
        widgets = {
            'month': MonthInput(attrs={'type': 'month'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.settings_app.models import Company

        self.fields['employee'].queryset = Employee.objects.filter(is_active=True).order_by('first_name', 'last_name')
        self.fields['employee'].empty_label = '-- Select Employee --'
        self.fields['company'].queryset = Company.objects.filter(is_active=True).order_by('name')
        self.fields['company'].required = False
        self.fields['company'].empty_label = '(From employee)'

        for name, field in self.fields.items():
            if name in ['employee', 'status', 'company']:
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'
    
    def clean_month(self):
        """Ensure month is converted to first day of month if needed."""
        month_value = self.cleaned_data.get('month')
        if not month_value:
            return month_value
        
        # If it's a string in YYYY-MM format (from widget), convert to date
        if isinstance(month_value, str):
            if len(month_value) == 7 and month_value.count('-') == 1:
                try:
                    year, month = month_value.split('-')
                    return datetime(int(year), int(month), 1).date()
                except (ValueError, AttributeError):
                    raise forms.ValidationError('Please enter a valid month.')
            # If it's already in YYYY-MM-DD format, parse it
            elif len(month_value) == 10:
                try:
                    date_obj = datetime.strptime(month_value, '%Y-%m-%d').date()
                    # Ensure it's the first day of the month
                    return datetime(date_obj.year, date_obj.month, 1).date()
                except (ValueError, AttributeError):
                    pass
        
        # If it's already a date object, ensure it's the first day of the month
        if hasattr(month_value, 'day'):
            if month_value.day != 1:
                return datetime(month_value.year, month_value.month, 1).date()
        
        return month_value
    
    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

