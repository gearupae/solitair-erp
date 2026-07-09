from django import forms
from django.forms import inlineformset_factory

from apps.crm.models import Customer
from apps.crm.utils import get_sales_employee_for_user, get_sales_employee_queryset, salesperson_display_name
from apps.settings_app.models import CompanySettings

from .models import Contract, ContractDocumentExpiry, ContractType


class ContractForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            'customer',
            'salesperson',
            'amc_category',
            'service_site',
            'name',
            'contract_value',
            'start_date',
            'end_date',
            'planned_visits',
            'status',
            'remind_before_days',
            'description',
            'terms_and_conditions',
            'contract_types',
        ]
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'salesperson': forms.Select(attrs={'class': 'form-select select2-contract-salesperson'}),
            'amc_category': forms.Select(attrs={'class': 'form-select'}),
            'service_site': forms.Textarea(
                attrs={
                    'rows': 3,
                    'class': 'form-control',
                    'placeholder': 'Building, street address, emirate/area…',
                }
            ),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contract name'}),
            'contract_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'planned_visits': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
            'remind_before_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '365'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'terms_and_conditions': forms.Textarea(
                attrs={'rows': 6, 'class': 'form-control', 'placeholder': 'Terms & conditions (shown on PDF)'}
            ),
            'contract_types': forms.SelectMultiple(
                attrs={'class': 'form-select select2-contract-types', 'data-placeholder': 'Select types…'}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        include_salesperson_id = None
        if self.instance.pk and self.instance.salesperson_id:
            include_salesperson_id = self.instance.salesperson_id
        elif self.instance.pk and self.instance.customer_id and self.instance.customer.assigned_salesperson_id:
            include_salesperson_id = self.instance.customer.assigned_salesperson_id

        self.fields['customer'].queryset = Customer.objects.filter(is_active=True).order_by('name', 'company')
        self.fields['customer'].required = False
        self.fields['customer'].empty_label = '— No customer —'
        self.fields['salesperson'].queryset = get_sales_employee_queryset(
            include_employee_id=include_salesperson_id,
        )
        self.fields['salesperson'].required = True
        self.fields['salesperson'].empty_label = '— Select salesperson —'
        self.fields['salesperson'].label = 'Salesperson'
        self.fields['salesperson'].label_from_instance = salesperson_display_name
        self.fields['amc_category'].required = True
        self.fields['amc_category'].label = 'AMC category'
        self.fields['amc_category'].empty_label = '— Select category —'
        self.fields['service_site'].required = True
        self.fields['service_site'].label = 'Service site / place'
        self.fields['contract_types'].queryset = ContractType.objects.filter(is_active=True).order_by('name')
        self.fields['contract_types'].required = False
        self.fields['contract_types'].label = 'Contract types'
        self.fields['contract_value'].label = 'Contract amount (AED)'
        self.fields['planned_visits'].label = 'Number of planned visits'
        self.fields['planned_visits'].required = True
        self.fields['remind_before_days'].label = 'Renewal reminder (days before end)'
        self.fields['status'].label = 'Status'
        self.fields['terms_and_conditions'].label = 'Terms & conditions'
        if not self.instance.pk and not self.data:
            self.fields['terms_and_conditions'].initial = (
                CompanySettings.get_settings().contract_default_terms or ''
            )
            self.fields['remind_before_days'].initial = 30
            if user:
                emp = get_sales_employee_for_user(user)
                if emp:
                    self.fields['salesperson'].initial = emp.pk

        if not self.instance.pk and not self.data and self.initial.get('customer'):
            customer = Customer.objects.filter(pk=self.initial['customer']).first()
            if customer and customer.assigned_salesperson_id and 'salesperson' not in self.initial:
                self.initial['salesperson'] = customer.assigned_salesperson_id

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            raise forms.ValidationError('End date must be on or after start date.')
        planned = cleaned.get('planned_visits')
        if planned is not None and planned < 1:
            self.add_error('planned_visits', 'Enter at least one planned visit for PPM scheduling.')
        return cleaned


class ContractDocumentExpiryForm(forms.ModelForm):
    class Meta:
        model = ContractDocumentExpiry
        fields = ['document_name', 'expiry_date', 'remind_before_days']
        widgets = {
            'document_name': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Document name'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'remind_before_days': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'min': '0', 'max': '365'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['document_name'].required = False
        self.fields['expiry_date'].required = False
        self.fields['remind_before_days'].label = 'Remind before (days)'

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get('document_name') or '').strip()
        expiry = cleaned.get('expiry_date')
        if not name and not expiry:
            return cleaned
        if not name:
            raise forms.ValidationError('Document name is required.')
        if not expiry:
            raise forms.ValidationError('Expiry date is required.')
        cleaned['document_name'] = name
        return cleaned


ContractDocumentExpiryFormSet = inlineformset_factory(
    Contract,
    ContractDocumentExpiry,
    form=ContractDocumentExpiryForm,
    extra=3,
    can_delete=True,
    min_num=0,
    validate_min=False,
)
