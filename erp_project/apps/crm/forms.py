"""
CRM Forms
"""
from django import forms
from .models import Customer
from .utils import (
    crm_leads_restricted_to_assignee,
    get_crm_project_queryset,
    get_sales_employee_for_user,
    get_sales_employee_queryset,
    project_choice_label,
    salesperson_display_name,
)


class CustomerForm(forms.ModelForm):
    """Form for creating/editing customers."""

    scope = forms.MultipleChoiceField(
        choices=Customer.SCOPE_CHOICES,
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                'class': 'form-select select2-crm-scope',
                'data-placeholder': 'Select scope…',
            }
        ),
    )

    class Meta:
        model = Customer
        fields = [
            'name', 'email', 'phone', 'company', 'address',
            'trn', 'website', 'scope', 'job_type', 'primary_project',
            'assigned_salesperson',
            'status', 'customer_type', 'business_segment', 'trn_document', 'trade_license_document',
            'notes',
        ]

    def __init__(self, *args, projects_queryset=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._request_user = user
        self._sales_rep_only = crm_leads_restricted_to_assignee(user)

        qs = projects_queryset if projects_queryset is not None else get_crm_project_queryset()
        self.fields['primary_project'].queryset = qs
        self.fields['primary_project'].required = False
        self.fields['primary_project'].empty_label = '— Select project —'
        self.fields['primary_project'].label_from_instance = project_choice_label
        self.fields['primary_project'].widget.attrs['class'] = 'form-select'
        self.fields['primary_project'].label = 'Project'
        self.fields['scope'].label = 'Scope'
        self.fields['business_segment'].required = False
        self.fields['business_segment'].widget.attrs['class'] = 'form-select'
        self.fields['business_segment'].label = 'Business type'
        self.fields['trn_document'].required = False
        self.fields['trade_license_document'].required = False

        self.fields['assigned_salesperson'].queryset = get_sales_employee_queryset()
        self.fields['assigned_salesperson'].required = False
        self.fields['assigned_salesperson'].empty_label = '— Select salesman —'
        self.fields['assigned_salesperson'].label_from_instance = salesperson_display_name
        self.fields['assigned_salesperson'].widget.attrs['class'] = 'form-select'
        self.fields['assigned_salesperson'].label = 'Assigned salesman'

        if self._sales_rep_only:
            self.fields['assigned_salesperson'].widget = forms.HiddenInput()
            if user:
                emp = get_sales_employee_for_user(user)
                if emp:
                    self.fields['assigned_salesperson'].initial = emp.pk

        if self.instance.pk:
            self.initial['scope'] = list(self.instance.scope or [])

        for field_name, field in self.fields.items():
            if field_name in ('scope', 'primary_project', 'business_segment', 'assigned_salesperson'):
                continue
            if field_name in ('trn_document', 'trade_license_document'):
                field.widget.attrs.setdefault('class', 'form-control')
                field.widget.attrs.setdefault('accept', '.pdf,.jpg,.jpeg,.png,.webp,.heic')
                continue
            if field_name in ['address', 'notes']:
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs['rows'] = 3
            elif field_name in ['status', 'customer_type', 'job_type']:
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'

            if field_name == 'name':
                field.widget.attrs['placeholder'] = 'Contact Name'
            elif field_name == 'email':
                field.widget.attrs['placeholder'] = 'email@example.com'
            elif field_name == 'phone':
                field.widget.attrs['placeholder'] = '+971 XX XXX XXXX'
            elif field_name == 'company':
                field.widget.attrs['placeholder'] = 'Company Name'
            elif field_name == 'address':
                field.widget.attrs['placeholder'] = 'Full Address'
            elif field_name == 'trn':
                field.widget.attrs['placeholder'] = 'VAT / TRN number'
            elif field_name == 'website':
                field.widget.attrs['placeholder'] = 'https://example.com'

    def clean(self):
        cleaned = super().clean()
        ctype = cleaned.get('customer_type')
        seg = (cleaned.get('business_segment') or '').strip()

        if ctype == 'lead':
            cleaned['business_segment'] = ''
            if self._sales_rep_only and self._request_user:
                cleaned['assigned_salesperson'] = get_sales_employee_for_user(self._request_user)
            elif not cleaned.get('assigned_salesperson'):
                self.add_error(
                    'assigned_salesperson',
                    'Select a salesman to assign this lead.',
                )
        else:
            cleaned['assigned_salesperson'] = None

        if ctype == 'customer':
            if seg not in ('b2b', 'b2c'):
                self.add_error(
                    'business_segment',
                    'Select B2B or B2C when type is Customer.',
                )
            if seg == 'b2b':
                if not (cleaned.get('trn') or '').strip():
                    self.add_error('trn', 'VAT (TRN) number is required for B2B customers.')
                lic_f = cleaned.get('trade_license_document')
                has_lic = bool(lic_f) or (
                    self.instance.pk and bool(self.instance.trade_license_document)
                )
                if not has_lic:
                    self.add_error(
                        'trade_license_document',
                        'Trade license upload is required for B2B customers.',
                    )

        return cleaned
