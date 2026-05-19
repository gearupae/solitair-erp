"""
Sales Forms - Tax Code Driven VAT (SAP/Oracle Standard)

VAT is ALWAYS derived from a TaxCode:
- No Tax Code = No VAT (Out of Scope)
- VAT rate is read-only, computed from Tax Code
"""
from django import forms
from django.contrib.auth import get_user_model
from django.forms.models import BaseInlineFormSet
from .models import Estimate, EstimateItem, Invoice, InvoiceItem
from apps.crm.models import Customer
from apps.finance.models import TaxCode
from apps.projects.models import Project

User = get_user_model()


class EstimateForm(forms.ModelForm):
    """Form for creating/editing estimates."""

    scope = forms.ChoiceField(
        choices=[('', '— Select scope —')] + list(Estimate.SCOPE_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Estimate
        fields = [
            'customer', 'assigned_to', 'prepared_by', 'project', 'date', 'valid_until', 'status',
            'discount_type', 'discount_value', 'show_rates_on_pdf',
            'notes', 'client_note', 'terms_and_conditions',
            'authorized_signature', 'customer_signature',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'valid_until': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(
                attrs={
                    'rows': 4,
                    'class': 'form-control estimate-internal-notes',
                    'placeholder': 'For your team only — not shown on the estimate PDF or to the client.',
                }
            ),
            'client_note': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'terms_and_conditions': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
            'prepared_by': forms.TextInput(attrs={'class': 'form-control'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'authorized_signature': forms.FileInput(attrs={'class': 'form-control'}),
            'customer_signature': forms.FileInput(attrs={'class': 'form-control'}),
            'show_rates_on_pdf': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'role': 'switch'},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(is_active=True)
        self.fields['customer'].widget.attrs['class'] = 'form-select'
        self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
        self.fields['assigned_to'].widget.attrs['class'] = 'form-select'
        self.fields['assigned_to'].required = False
        self.fields['assigned_to'].label = 'Assigned to'
        self.fields['project'].queryset = Project.objects.filter(is_active=True).order_by('name')
        self.fields['project'].widget.attrs['class'] = 'form-select'
        self.fields['project'].required = False
        self.fields['status'].widget.attrs['class'] = 'form-select'
        self.fields['valid_until'].required = False
        self.fields['discount_type'].widget.attrs['class'] = 'form-select'
        self.fields['notes'].required = False
        self.fields['client_note'].required = False
        self.fields['terms_and_conditions'].required = False
        self.fields['prepared_by'].required = False
        self.fields['scope'].label = 'Scope'
        self.fields['show_rates_on_pdf'].label = 'Show rates & line totals on PDF'
        self.fields['show_rates_on_pdf'].required = False

        if self.instance.pk and self.instance.scope:
            scopes = list(self.instance.scope or [])
            if len(scopes) == 1:
                self.initial['scope'] = scopes[0]
            elif len(scopes) > 1:
                self.initial['scope'] = scopes[0]

    def save(self, commit=True):
        instance = super().save(commit=False)
        val = self.cleaned_data.get('scope')
        instance.scope = [val] if val else []
        if commit:
            instance.save()
        return instance


class EstimateItemForm(forms.ModelForm):
    """
    Form for estimate line items.
    Tax Code determines VAT rate - No Tax Code = 0% VAT (Out of Scope)
    """

    class Meta:
        model = EstimateItem
        fields = [
            'group_name', 'sort_order', 'inventory_item', 'description', 'quantity', 'unit_price',
            'profit_type', 'profit_value', 'rate', 'tax_code', 'is_vat_inclusive',
        ]
        widgets = {
            'group_name': forms.TextInput(attrs={
                'class': 'form-control form-control-sm item-group-name',
                'placeholder': 'PDF section',
                'list': 'estimate-group-names',
                'title': 'Estimate / PDF section title for this line. Editing this does not change inventory masters—only how this estimate is grouped on the PDF.',
            }),
            'sort_order': forms.HiddenInput(),
            'description': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-qty', 'step': '0.01', 'min': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-base-price', 'step': '0.01', 'min': '0'}),
            'profit_type': forms.Select(attrs={'class': 'form-select form-select-sm item-profit-type'}),
            'profit_value': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-profit-value', 'step': '0.01', 'min': '0'}),
            'rate': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-rate', 'step': '0.01', 'readonly': 'readonly'}),
            'inventory_item': forms.Select(attrs={'class': 'form-select form-select-sm item-inventory'}),
            'is_vat_inclusive': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.inventory.models import Item

        self.fields['inventory_item'].queryset = Item.objects.filter(is_active=True, status='active').order_by('name')
        self.fields['inventory_item'].required = False
        self.fields['inventory_item'].empty_label = '-- Select from inventory --'
        self.fields['description'].required = False
        self.fields['unit_price'].required = False
        self.fields['profit_value'].required = False
        self.fields['rate'].required = False

        for field_name, field in self.fields.items():
            if field_name in ['tax_code']:
                field.widget.attrs['class'] = 'form-select form-select-sm item-tax-code'
            elif field_name not in ('inventory_item', 'profit_type', 'profit_value', 'rate', 'group_name', 'sort_order', 'description', 'quantity', 'unit_price', 'is_vat_inclusive'):
                pass

        self.fields['tax_code'].queryset = TaxCode.objects.filter(is_active=True)
        self.fields['tax_code'].required = False
        self.fields['tax_code'].empty_label = "-- No Tax (Out of Scope) --"

        self.fields['profit_type'].choices = [
            ('none', 'None'),
            ('percent', 'Percent (%)'),
            ('amount', 'AED per unit'),
        ]
        self.fields['profit_value'].label = 'Profit'
        self.fields['profit_value'].help_text = 'Percent markup on base, or AED added to base per unit (not one lump for the whole line).'

        self.fields['group_name'].required = False
        self.fields['group_name'].help_text = 'Shown when this estimate is printed / on the PDF; does not update inventory.'

        if not self.instance.pk:
            default_tax_code = TaxCode.objects.filter(is_active=True, is_default=True).first()
            if default_tax_code:
                self.fields['tax_code'].initial = default_tax_code


class EstimateItemInlineFormSet(BaseInlineFormSet):
    """Hide the default DELETE checkbox; removal is done via the row ✕ (still posts DELETE)."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if self.can_delete and 'DELETE' in form.fields:
            form.fields['DELETE'].label = ''
            form.fields['DELETE'].widget.attrs.update(
                {'class': 'd-none', 'aria-hidden': 'true', 'tabindex': '-1'}
            )


EstimateItemFormSet = forms.inlineformset_factory(
    Estimate,
    EstimateItem,
    form=EstimateItemForm,
    formset=EstimateItemInlineFormSet,
    extra=1,
    can_delete=True,
    validate_min=False,
    min_num=0,
)


class InvoiceForm(forms.ModelForm):
    """Form for creating/editing invoices."""
    
    class Meta:
        model = Invoice
        fields = ['customer', 'estimate', 'invoice_date', 'due_date', 'status', 'notes']
        widgets = {
            'invoice_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(is_active=True)
        self.fields['customer'].widget.attrs['class'] = 'form-select'
        self.fields['estimate'].queryset = Estimate.objects.filter(
            is_active=True, status__in=['approved', 'quotation_won'],
        )
        self.fields['estimate'].widget.attrs['class'] = 'form-select'
        self.fields['estimate'].required = False
        self.fields['status'].widget.attrs['class'] = 'form-select'
        self.fields['notes'].required = False


class InvoiceItemForm(forms.ModelForm):
    """
    Form for invoice line items.
    Tax Code determines VAT rate - No Tax Code = 0% VAT (Out of Scope)
    """
    
    class Meta:
        model = InvoiceItem
        fields = ['description', 'quantity', 'unit_price', 'tax_code', 'is_vat_inclusive']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['unit_price'].required = False
        for field_name, field in self.fields.items():
            if field_name in ['tax_code']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name == 'is_vat_inclusive':
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'
        
        self.fields['tax_code'].queryset = TaxCode.objects.filter(is_active=True)
        self.fields['tax_code'].required = False
        self.fields['tax_code'].empty_label = "-- No Tax (Out of Scope) --"
        
        if not self.instance.pk:
            default_tax_code = TaxCode.objects.filter(is_active=True, is_default=True).first()
            if default_tax_code:
                self.fields['tax_code'].initial = default_tax_code

    def clean(self):
        cleaned_data = super().clean()
        description = (cleaned_data.get('description') or '').strip()
        unit_price = cleaned_data.get('unit_price')
        if not description and not unit_price:
            return cleaned_data
        if not description:
            self.add_error('description', 'Description is required.')
        if not unit_price and unit_price != 0:
            self.add_error('unit_price', 'Unit price is required.')
        return cleaned_data


InvoiceItemFormSet = forms.inlineformset_factory(
    Invoice,
    InvoiceItem,
    form=InvoiceItemForm,
    extra=1,
    can_delete=True,
    validate_min=False,
    min_num=0
)
