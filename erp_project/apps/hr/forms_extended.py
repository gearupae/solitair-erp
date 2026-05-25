"""Additional HR forms (attendance, compliance, payroll settings)."""

import json
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from apps.hr.attendance_utils import attendance_overlap_message
from apps.hr.models import Employee
from apps.hr.models_extended import (
    AttendanceRecord,
    AttendanceSettings,
    EmployeeAdvance,
    Holiday,
    EmployeeHRProfile,
    KSACompliance,
    PayrollSettings,
    PayrollTemplate,
    UAECompliance,
)
from apps.hr.payroll_allowances import normalize_template_allowance_lines_json
from apps.projects.models import Project


class PayrollSettingsForm(forms.ModelForm):
    class Meta:
        model = PayrollSettings
        fields = [
            'late_deduction_amount',
            'working_days_in_month',
            'overtime_rate_multiplier',
            'hr_notification_email',
            'iloe_deduct_via_payroll',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'iloe_deduct_via_payroll':
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'


class PayrollTemplateForm(forms.ModelForm):
    """Allowance lines JSON is kept in hidden field `allowance_lines` (filled by JS on submit)."""

    allowance_lines = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'allowance-lines-json'}),
    )

    class Meta:
        model = PayrollTemplate
        fields = ['name', 'company', 'location', 'basic_salary', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['company'].required = False
        self.fields['company'].empty_label = '(Any company)'
        self.fields['basic_salary'] = forms.DecimalField(
            max_digits=12,
            decimal_places=2,
            required=False,
            widget=forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Optional'}
            ),
            help_text='Optional. Totals below use allowances only; add basic here if you want it included in the package preview.',
        )
        if self.instance and self.instance.pk:
            self.fields['basic_salary'].initial = self.instance.basic_salary
        al = normalize_template_allowance_lines_json(
            (self.instance.allowance_lines or []) if self.instance and self.instance.pk else []
        )
        self.fields['allowance_lines'].initial = json.dumps(al)

    def clean_basic_salary(self):
        v = self.cleaned_data.get('basic_salary')
        if v is None:
            return Decimal('0.00')
        return v.quantize(Decimal('0.01'))

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get('name') or '').strip()
        company = cleaned.get('company')
        if not name:
            return cleaned
        qs = PayrollTemplate.objects.filter(is_active=True, name=name, company=company)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(
                {'name': 'A template with this name already exists for this company.'}
            )
        return cleaned


class EmployeeAdvanceForm(forms.ModelForm):
    class Meta:
        model = EmployeeAdvance
        fields = [
            'employee',
            'advance_type',
            'amount',
            'reason',
            'approved_by',
            'date_issued',
            'repayment_months',
            'notes',
        ]
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'advance_type': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'approved_by': forms.Select(attrs={'class': 'form-select'}),
            'date_issued': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'repayment_months': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        from django.contrib.auth.models import User

        super().__init__(*args, **kwargs)
        from apps.hr.models import Employee

        self.fields['employee'].queryset = Employee.objects.filter(is_active=True).order_by(
            'first_name', 'last_name'
        )
        self.fields['approved_by'].queryset = User.objects.filter(is_active=True).order_by('username')
        self.fields['approved_by'].required = False
        self.fields['approved_by'].empty_label = '— None —'
        _df = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
        self.fields['date_issued'].input_formats = _df


class AttendanceSettingsForm(forms.ModelForm):
    class Meta:
        model = AttendanceSettings
        fields = [
            'shift_start',
            'shift_end',
            'working_hours_per_day',
            'late_threshold_minutes',
            'half_day_hours',
            'overtime_threshold_hours',
            'late_deduction_amount',
            'overtime_rate_normal',
            'overtime_rate_night',
            'overtime_rate_holiday',
            'overtime_rate_multiplier',
            'auto_mark_absent',
            'working_days_in_month',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'auto_mark_absent':
                field.widget.attrs['class'] = 'form-check-input'
            elif name in ('shift_start', 'shift_end'):
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs.setdefault('type', 'time')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ['name', 'date', 'location', 'is_recurring']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'location':
                field.widget.attrs['class'] = 'form-select'
            elif name == 'is_recurring':
                field.widget.attrs['class'] = 'form-check-input'
            elif name != 'date':
                field.widget.attrs.setdefault('class', 'form-control')


class AttendanceMarkForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = ['employee', 'date', 'check_in', 'check_out', 'status', 'overtime_type', 'notes', 'source', 'project']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'check_in': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'check_out': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].queryset = Employee.objects.filter(is_active=True).order_by('first_name', 'last_name')
        self.fields['project'].queryset = Project.objects.filter(is_active=True).order_by('project_code', 'name')
        self.fields['project'].required = False
        self.fields['project'].label = 'Project (labour / site)'
        for name, field in self.fields.items():
            if name not in self.Meta.widgets:
                field.widget.attrs.setdefault(
                    'class',
                    'form-select' if name in ('employee', 'status', 'source', 'overtime_type', 'project') else 'form-control',
                )

    def clean(self):
        cleaned = super().clean()
        employee = cleaned.get('employee')
        ad = cleaned.get('date')
        check_in = cleaned.get('check_in')
        check_out = cleaned.get('check_out')
        if employee and ad and check_in:
            exclude_pk = self.instance.pk if self.instance and self.instance.pk else None
            overlap = attendance_overlap_message(
                employee,
                ad,
                check_in,
                check_out,
                exclude_pk=exclude_pk,
            )
            if overlap:
                raise forms.ValidationError(overlap)
        return cleaned


class UAEComplianceForm(forms.ModelForm):
    class Meta:
        model = UAECompliance
        fields = [
            'emirates_id_expiry',
            'visa_type',
            'passport_number',
            'passport_expiry',
            'labour_card_number',
            'labour_card_expiry',
            'medical_insurance_provider',
            'medical_insurance_policy_number',
            'medical_insurance_expiry',
            'unified_number',
            'unified_number_expiry',
            'bank_iban',
            'bank_routing_code',
            'iloe_insurance_provider',
            'iloe_insurance_policy_number',
            'iloe_insurance_expiry',
            'iloe_applicable',
            'gratuity_applicable',
        ]
        widgets = {
            'emirates_id_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'passport_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'labour_card_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'medical_insurance_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'unified_number_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'iloe_insurance_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'visa_type': forms.Select(attrs={'class': 'form-select'}),
            'iloe_applicable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'gratuity_applicable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _date_formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
        for name, field in self.fields.items():
            if name in self.Meta.widgets:
                if isinstance(field.widget, forms.DateInput):
                    field.input_formats = _date_formats
                continue
            field.widget.attrs.setdefault('class', 'form-control')


class KSAComplianceForm(forms.ModelForm):
    class Meta:
        model = KSACompliance
        fields = [
            'iqama_number',
            'iqama_expiry',
            'iqama_profession',
            'work_permit_number',
            'work_permit_expiry',
            'work_permit_classification',
            'passport_number',
            'passport_expiry',
            'medical_insurance_provider',
            'medical_insurance_policy_number',
            'medical_insurance_expiry',
            'muqeem_number',
            'muqeem_expiry',
            'absher_id',
            'nationality',
            'gosi_number',
            'gosi_applicable',
            'nitaqat_category',
            'qiwa_contract_registered',
            'mudad_wps_enrolled',
        ]
        help_texts = {
            'nationality': 'Saudi vs non-Saudi drives GOSI rates on payroll (10%+12% vs 0%+2%).',
            'gosi_number': 'GOSI registration number for reporting.',
            'gosi_applicable': (
                'Uncheck only if this employee is excluded from GOSI. '
                'Saudi: 10% employee + 12% employer deducted on payroll processing. '
                'Non-Saudi: 0% employee + 2% employer (hazard) deducted.'
            ),
            'iqama_number': '9-digit Iqama / national ID for KSA.',
        }
        widgets = {
            'iqama_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'work_permit_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'passport_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'medical_insurance_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'muqeem_expiry': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'
            ),
            'nationality': forms.Select(attrs={'class': 'form-select'}),
            'work_permit_classification': forms.Select(attrs={'class': 'form-select'}),
            'nitaqat_category': forms.Select(attrs={'class': 'form-select'}),
            'gosi_applicable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'qiwa_contract_registered': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'mudad_wps_enrolled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _date_formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
        for name, field in self.fields.items():
            if name in self.Meta.widgets:
                if isinstance(field.widget, forms.DateInput):
                    field.input_formats = _date_formats
                continue
            field.widget.attrs.setdefault('class', 'form-control')


class EmployeeHRProfileForm(forms.ModelForm):
    class Meta:
        model = EmployeeHRProfile
        fields = ['employment_entity', 'gosi_employee_category', 'nationality_display']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-select')

