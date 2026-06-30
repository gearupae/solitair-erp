from django import forms
from django.forms import inlineformset_factory

from apps.crm.models import Customer
from apps.settings_app.models import CompanySettings

from .models import Contract, ContractDocumentExpiry, ContractType


class ContractForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            'customer',
            'name',
            'contract_value',
            'start_date',
            'end_date',
            'status',
            'remind_before_days',
            'description',
            'terms_and_conditions',
            'contract_types',
        ]
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contract name'}),
            'contract_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'remind_before_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '365'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'terms_and_conditions': forms.Textarea(
                attrs={'rows': 6, 'class': 'form-control', 'placeholder': 'Terms & conditions (shown on PDF)'}
            ),
            'contract_types': forms.SelectMultiple(
                attrs={'class': 'form-select select2-contract-types', 'data-placeholder': 'Select types…'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(is_active=True).order_by('name', 'company')
        self.fields['customer'].required = False
        self.fields['customer'].empty_label = '— No customer —'
        self.fields['contract_types'].queryset = ContractType.objects.filter(is_active=True).order_by('name')
        self.fields['contract_types'].required = False
        self.fields['contract_types'].label = 'Contract types'
        self.fields['contract_value'].label = 'Contract value'
        self.fields['remind_before_days'].label = 'Remind before (days)'
        self.fields['status'].label = 'Status'
        self.fields['terms_and_conditions'].label = 'Terms & conditions'
        if not self.instance.pk and not self.data:
            self.fields['terms_and_conditions'].initial = (
                CompanySettings.get_settings().contract_default_terms or ''
            )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            raise forms.ValidationError('End date must be on or after start date.')
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
