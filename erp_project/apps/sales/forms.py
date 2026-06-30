"""
Sales Forms - Tax Code Driven VAT (SAP/Oracle Standard)

VAT is ALWAYS derived from a TaxCode:
- No Tax Code = No VAT (Out of Scope)
- VAT rate is read-only, computed from Tax Code
"""
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.forms.models import BaseInlineFormSet
from decimal import Decimal
from .models import Estimate, EstimateItem, Invoice, InvoiceItem
from apps.crm.models import Customer
from apps.finance.models import TaxCode
from apps.inventory.models import ItemBaseGroup
from .estimate_csv import get_default_estimate_csv_tax_code

User = get_user_model()


class EstimateForm(forms.ModelForm):
    """Form for creating/editing estimates."""

    scope_of_work = forms.ChoiceField(
        required=False,
        label='Scope of work',
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Estimate
        fields = [
            'customer', 'assigned_to', 'prepared_by',
            'estimation_reference_number', 'sales_engineer',
            'type_of_occupancy', 'type_of_work', 'scope_of_work',
            'date', 'valid_until',
            'discount_type', 'discount_value', 'show_rates_on_pdf', 'show_group_totals_on_pdf',
            'show_brand_name_on_pdf', 'show_installation_cost_on_pdf',
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
            'estimation_reference_number': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'External / client reference'},
            ),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'authorized_signature': forms.FileInput(attrs={'class': 'form-control'}),
            'customer_signature': forms.FileInput(attrs={'class': 'form-control'}),
            'show_rates_on_pdf': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'role': 'switch'},
            ),
            'show_group_totals_on_pdf': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'role': 'switch'},
            ),
            'show_brand_name_on_pdf': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'role': 'switch'},
            ),
            'show_installation_cost_on_pdf': forms.CheckboxInput(
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
        self.fields['valid_until'].required = False
        self.fields['date'].input_formats = ['%Y-%m-%d']
        self.fields['valid_until'].input_formats = ['%Y-%m-%d']
        self.fields['discount_type'].widget.attrs['class'] = 'form-select'
        self.fields['notes'].required = False
        self.fields['client_note'].required = False
        self.fields['client_note'].label = 'Payment terms'
        self.fields['terms_and_conditions'].required = False
        self.fields['prepared_by'].required = False
        self.fields['estimation_reference_number'].required = False
        self.fields['estimation_reference_number'].label = 'Estimation reference number'
        from apps.hr.models import Employee

        include_engineer_id = None
        if self.instance.pk and self.instance.sales_engineer_id:
            include_engineer_id = self.instance.sales_engineer_id
        engineer_qs = Employee.objects.filter(is_active=True, status='active').order_by(
            'first_name', 'last_name', 'employee_code',
        )
        if include_engineer_id:
            engineer_qs = Employee.objects.filter(
                Q(is_active=True, status='active') | Q(pk=include_engineer_id),
            ).order_by('first_name', 'last_name', 'employee_code')
        self.fields['sales_engineer'].queryset = engineer_qs
        self.fields['sales_engineer'].required = False
        self.fields['sales_engineer'].empty_label = '— Select sales engineer —'
        self.fields['sales_engineer'].label_from_instance = (
            lambda emp: f'{emp.full_name} ({emp.employee_code})'
        )
        self.fields['sales_engineer'].widget.attrs['class'] = 'form-select'
        for field_name in ('type_of_occupancy', 'type_of_work'):
            field = self.fields[field_name]
            field.required = False
            field.widget.attrs['class'] = 'form-select'
        self.fields['type_of_occupancy'].label = 'Type of occupancy'
        self.fields['type_of_work'].label = 'Type of work'
        scope_choices = [('', '---------')] + [
            (bg.name, bg.name) for bg in ItemBaseGroup.objects.order_by('name')
        ]
        if self.instance and self.instance.pk and self.instance.scope_of_work:
            current_scope = self.instance.scope_of_work
            if current_scope not in {value for value, _ in scope_choices if value}:
                scope_choices.append((current_scope, self.instance.scope_of_work_label))
        self.fields['scope_of_work'].choices = scope_choices
        self.fields['show_rates_on_pdf'].label = 'Show rates & line totals on PDF'
        self.fields['show_rates_on_pdf'].required = False
        self.fields['show_group_totals_on_pdf'].label = 'Show group totals on PDF'
        self.fields['show_group_totals_on_pdf'].required = False
        self.fields['show_brand_name_on_pdf'].label = 'Show brand name'
        self.fields['show_brand_name_on_pdf'].required = False
        self.fields['show_installation_cost_on_pdf'].label = 'Show installation cost'
        self.fields['show_installation_cost_on_pdf'].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.pk:
            instance.status = Estimate.objects.values_list('status', flat=True).get(pk=instance.pk)
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
            'group_name', 'group_qty_multiplier', 'sort_order', 'inventory_item', 'brand',
            'description', 'quantity', 'unit_price', 'installation_cost', 'selling_cost',
            'profit_type', 'profit_value', 'tax_code', 'is_vat_inclusive',
        ]
        widgets = {
            'group_name': forms.TextInput(attrs={
                'class': 'form-control form-control-sm item-group-name',
                'placeholder': 'PDF section',
                'list': 'estimate-group-names',
                'title': 'Estimate / PDF section title for this line. Editing this does not change inventory masters—only how this estimate is grouped on the PDF.',
            }),
            'group_qty_multiplier': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm item-group-qty-mult',
                'step': '1',
                'min': '1',
                'title': 'Multiplied with qty for every line in this group (effective qty = qty × group ×).',
            }),
            'sort_order': forms.HiddenInput(),
            'description': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-qty', 'step': '1', 'min': '1'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-base-price', 'step': '0.01', 'min': '0'}),
            'installation_cost': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm item-installation-cost',
                'step': '0.01',
                'min': '0',
            }),
            'selling_cost': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm item-selling-cost',
                'step': '0.01',
                'min': '0',
            }),
            'profit_type': forms.Select(attrs={'class': 'form-select form-select-sm item-profit-type'}),
            'profit_value': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm item-profit-value',
                'step': '0.01',
                'readonly': 'readonly',
            }),
            'inventory_item': forms.Select(attrs={'class': 'form-select form-select-sm item-inventory'}),
            'is_vat_inclusive': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.inventory.models import Item

        self.fields['inventory_item'].queryset = Item.objects.filter(is_active=True, status='active').order_by('name')
        self.fields['inventory_item'].required = False
        self.fields['inventory_item'].empty_label = '-- Select from inventory --'
        brand_choices = [
            (b, b)
            for b in Item.objects.filter(is_active=True, status='active')
            .exclude(brand='')
            .values_list('brand', flat=True)
            .distinct()
            .order_by('brand')
        ]
        if self.instance and self.instance.brand and self.instance.brand not in dict(brand_choices):
            brand_choices = [(self.instance.brand, self.instance.brand)] + brand_choices
        self.fields['brand'] = forms.ChoiceField(
            choices=[('', '')] + brand_choices,
            required=False,
            widget=forms.Select(attrs={'class': 'form-select form-select-sm item-brand'}),
        )
        self.fields['description'].required = False
        self.fields['unit_price'].required = False
        self.fields['unit_price'].label = 'Unit cost'
        self.fields['installation_cost'].required = False
        self.fields['installation_cost'].label = 'Unit installation cost'
        self.fields['selling_cost'].required = False
        self.fields['selling_cost'].label = 'Selling cost'
        self.fields['profit_value'].required = False

        for field_name, field in self.fields.items():
            if field_name in ['tax_code']:
                field.widget.attrs['class'] = 'form-select form-select-sm item-tax-code'
            elif field_name not in (
                'inventory_item', 'brand', 'profit_type', 'profit_value', 'selling_cost', 'group_name',
                'group_qty_multiplier', 'sort_order', 'description', 'quantity', 'unit_price',
                'installation_cost', 'is_vat_inclusive',
            ):
                pass

        self.fields['tax_code'].queryset = TaxCode.objects.filter(is_active=True)
        self.fields['tax_code'].required = False
        self.fields['tax_code'].empty_label = "-- No Tax (Out of Scope) --"

        self.fields['profit_type'].choices = [
            ('none', 'None'),
            ('percent', 'Percent (%)'),
            ('amount', 'AED per unit'),
        ]
        self.fields['profit_value'].label = 'Profit value'
        self.fields['profit_value'].help_text = 'Calculated from selling cost vs unit cost.'

        self.fields['group_name'].required = False
        self.fields['group_name'].help_text = 'Shown when this estimate is printed / on the PDF; does not update inventory.'
        self.fields['group_qty_multiplier'].required = False
        self.fields['group_qty_multiplier'].label = 'Group ×'

        if not self.instance.pk:
            default_tax_code = get_default_estimate_csv_tax_code()
            if default_tax_code:
                self.fields['tax_code'].initial = default_tax_code.pk

    def clean(self):
        cleaned = super().clean()
        inv = cleaned.get('inventory_item')
        unit_price = cleaned.get('unit_price')
        if inv and unit_price is not None:
            item = EstimateItem(
                unit_price=unit_price,
                quantity=cleaned.get('quantity') or Decimal('1'),
                installation_cost=cleaned.get('installation_cost') or Decimal('0'),
                selling_cost=cleaned.get('selling_cost') or unit_price or Decimal('0'),
                profit_type=cleaned.get('profit_type') or 'none',
            )
            item.apply_profit_from_selling_cost()
            selling = item.effective_selling_unit
            err = inv.quote_rate_bounds_error(unit_price, selling)
            if err:
                highlight = 'selling_cost' if (
                    (cleaned.get('profit_type') or 'none') != 'none'
                ) else 'unit_price'
                self.add_error(highlight, err)
        mult = cleaned.get('group_qty_multiplier')
        if mult is not None and mult < Decimal('1'):
            self.add_error('group_qty_multiplier', 'Group multiplier must be at least 1.')
        return cleaned


def estimate_line_is_empty(cleaned_data, instance=None):
    """True when a line has no inventory, description, or base price."""
    if not cleaned_data or cleaned_data.get('DELETE'):
        return False
    inv = cleaned_data.get('inventory_item')
    desc = (cleaned_data.get('description') or '').strip()
    unit_price = cleaned_data.get('unit_price')
    if unit_price is None and instance is not None:
        unit_price = instance.unit_price
    try:
        price = Decimal(str(unit_price or '0'))
    except Exception:
        price = Decimal('0')
    return not inv and not desc and price <= 0


class EstimateItemInlineFormSet(BaseInlineFormSet):
    """Hide the default DELETE checkbox; removal is done via the row ✕ (still posts DELETE)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        default_tax_code = get_default_estimate_csv_tax_code()
        if not default_tax_code:
            return
        for form in self.forms:
            if form.instance.pk:
                continue
            if form.initial.get('tax_code'):
                continue
            form.initial['tax_code'] = default_tax_code.pk
            form.fields['tax_code'].initial = default_tax_code.pk

    def clean(self):
        super().clean()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            if estimate_line_is_empty(form.cleaned_data, form.instance):
                if form.instance.pk:
                    form.cleaned_data['DELETE'] = True

    def save_new_objects(self, commit=True):
        self.new_objects = []
        for form in self.extra_forms:
            if not form.has_changed():
                continue
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            if estimate_line_is_empty(form.cleaned_data):
                continue
            self.new_objects.append(self.save_new(form, commit=commit))
            if not commit:
                self.saved_forms.append(form)
        return self.new_objects

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
    extra=0,
    can_delete=True,
    validate_min=False,
    min_num=0,
)


class InvoiceForm(forms.ModelForm):
    """Form for creating/editing invoices."""
    
    class Meta:
        model = Invoice
        fields = [
            'customer', 'estimate', 'project', 'invoice_date', 'due_date',
            'status', 'notes', 'retention_percent', 'retention_amount',
        ]
        widgets = {
            'invoice_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'retention_percent': forms.HiddenInput(),
            'retention_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'id': 'id_retention_amount',
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.projects.models import Project

        self.fields['customer'].queryset = Customer.objects.filter(is_active=True)
        self.fields['customer'].widget.attrs['class'] = 'form-select'
        self.fields['estimate'].queryset = Estimate.objects.filter(
            is_active=True, status='quotation_won',
        )
        self.fields['estimate'].widget.attrs['class'] = 'form-select'
        self.fields['estimate'].required = False
        self.fields['project'].queryset = Project.objects.filter(is_active=True).order_by('name', 'project_code')
        self.fields['project'].widget.attrs['class'] = 'form-select'
        self.fields['project'].required = False
        self.fields['project'].empty_label = '— No project —'
        self.fields['status'].widget.attrs['class'] = 'form-select'
        self.fields['notes'].required = False
        self.fields['retention_amount'].required = False
        self.fields['retention_amount'].label = 'Retention amount (AED)'

    def clean_retention_amount(self):
        value = self.cleaned_data.get('retention_amount')
        if value is None:
            return Decimal('0.00')
        return Decimal(str(value)).quantize(Decimal('0.01'))


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
            default_tax_code = get_default_estimate_csv_tax_code()
            if default_tax_code:
                self.fields['tax_code'].initial = default_tax_code.pk

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
