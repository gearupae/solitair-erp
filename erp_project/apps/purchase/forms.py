"""
Purchase Forms - Including Expense Claims and Recurring Expenses

VAT LOGIC (Tax Code Driven - SAP/Oracle Standard):
- VAT is ALWAYS derived from a TaxCode
- No Tax Code = No VAT (Out of Scope)
- VAT rate is read-only, computed from Tax Code
"""
from django import forms
from django.db.models import Q
from django.core.exceptions import ValidationError
from .models import (
    Vendor, PurchaseRequest, PurchaseRequestItem,
    PurchaseOrder, PurchaseOrderItem, VendorBill, VendorBillItem,
    ExpenseClaim, ExpenseClaimItem, RecurringExpense
)
from apps.finance.models import TaxCode


class VendorForm(forms.ModelForm):
    """Form for creating/editing vendors."""
    
    class Meta:
        model = Vendor
        fields = ['name', 'contact_person', 'email', 'phone', 'address', 'status', 'notes']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['address', 'notes']:
                field.widget.attrs['class'] = 'form-control'
            elif field_name == 'status':
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class PurchaseRequestForm(forms.ModelForm):
    """Form for creating/editing purchase requests."""
    
    class Meta:
        model = PurchaseRequest
        fields = ['date', 'required_by_date', 'department', 'priority', 'status', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'required_by_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.hr.models import Department
        self.fields['department'].queryset = Department.objects.filter(is_active=True)
        self.fields['department'].required = False
        self.fields['status'].widget.attrs['class'] = 'form-select'
        self.fields['required_by_date'].required = False
        self.fields['notes'].required = False


class PurchaseRequestItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseRequestItem
        fields = ['description', 'quantity', 'unit', 'estimated_price']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unit'].widget.attrs['class'] = 'form-select'
        for field in self.fields.values():
            if field.widget.attrs.get('class') != 'form-select':
                field.widget.attrs['class'] = 'form-control'


PurchaseRequestItemFormSet = forms.inlineformset_factory(
    PurchaseRequest,
    PurchaseRequestItem,
    form=PurchaseRequestItemForm,
    extra=1,
    can_delete=True
)


class PurchaseOrderForm(forms.ModelForm):
    """Form for creating/editing purchase orders."""
    
    class Meta:
        model = PurchaseOrder
        fields = ['vendor', 'purchase_request', 'service_request', 'order_date', 'expected_delivery_date', 'status', 'notes']
        widgets = {
            'order_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'expected_delivery_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'rows': 1, 'class': 'form-control'}),
        }
    
    # Fields to exclude when editing (source is set at creation only)
    edit_exclude = ['purchase_request', 'service_request']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_edit = self.instance and self.instance.pk
        
        # When editing, exclude PR/SR - source is set at creation only, avoids validation issues
        if is_edit:
            for f in self.edit_exclude:
                if f in self.fields:
                    del self.fields[f]
        
        self.fields['vendor'].queryset = Vendor.objects.filter(is_active=True, status='active')
        self.fields['vendor'].widget.attrs['class'] = 'form-select'
        
        if not is_edit:
            # Show approved PRs (create form only)
            approved_prs = PurchaseRequest.objects.filter(is_active=True, status='approved')
            self.fields['purchase_request'].queryset = approved_prs
            self.fields['purchase_request'].widget.attrs['class'] = 'form-select'
            self.fields['purchase_request'].required = False
            self.fields['purchase_request'].empty_label = "— Optional —"
            
            # Show approved SRs (create form only)
            from apps.service_request.models import ServiceRequest
            approved_srs = ServiceRequest.objects.filter(is_active=True, status='approved')
            self.fields['service_request'].queryset = approved_srs
            self.fields['service_request'].widget.attrs['class'] = 'form-select'
            self.fields['service_request'].required = False
            self.fields['service_request'].empty_label = "— Optional —"

        self.fields['status'].widget.attrs['class'] = 'form-select'
        self.fields['status'].choices = PurchaseOrder.STATUS_CHOICES
        self.fields['expected_delivery_date'].required = False
        self.fields['notes'].required = False
    
    def clean_service_request(self):
        """Ensure empty value is None - From SR is optional."""
        val = self.cleaned_data.get('service_request')
        return val if val else None
    
    def clean_purchase_request(self):
        """Ensure empty value is None - From PR is optional."""
        val = self.cleaned_data.get('purchase_request')
        return val if val else None


class PurchaseOrderItemForm(forms.ModelForm):
    """
    Form for purchase order line items.
    Tax Code determines VAT rate - No Tax Code = 0% VAT (Out of Scope)
    """
    
    class Meta:
        model = PurchaseOrderItem
        fields = ['description', 'quantity', 'unit_price', 'tax_code', 'is_vat_inclusive']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['tax_code']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name == 'is_vat_inclusive':
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'
        
        # Set Tax Code queryset and default
        self.fields['tax_code'].queryset = TaxCode.objects.filter(is_active=True)
        self.fields['tax_code'].required = False
        self.fields['tax_code'].empty_label = "-- No Tax (Out of Scope) --"
        
        # Pre-select default tax code if creating new item
        if not self.instance.pk:
            default_tax_code = TaxCode.objects.filter(is_active=True, is_default=True).first()
            if default_tax_code:
                self.fields['tax_code'].initial = default_tax_code


PurchaseOrderItemFormSet = forms.inlineformset_factory(
    PurchaseOrder,
    PurchaseOrderItem,
    form=PurchaseOrderItemForm,
    extra=1,
    can_delete=True
)


class VendorBillForm(forms.ModelForm):
    """Form for creating/editing vendor bills."""

    class Meta:
        model = VendorBill
        fields = [
            'vendor', 'purchase_order', 'goods_received',
            'vendor_invoice_number', 'bill_date', 'due_date', 'status', 'notes',
        ]
        widgets = {
            'bill_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'goods_received': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vendor'].queryset = Vendor.objects.filter(is_active=True)
        self.fields['vendor'].widget.attrs['class'] = 'form-select'
        self.fields['purchase_order'].queryset = PurchaseOrder.objects.filter(is_active=True)
        self.fields['purchase_order'].widget.attrs['class'] = 'form-select'
        self.fields['purchase_order'].required = False
        self.fields['status'].widget.attrs['class'] = 'form-select'
        self.fields['vendor_invoice_number'].widget.attrs['class'] = 'form-control'
        self.fields['vendor_invoice_number'].required = False
        self.fields['notes'].required = False
        self.fields['goods_received'].help_text = (
            "Check if this bill is for goods already received into inventory. "
            "This will debit GRN Clearing instead of Expense."
        )

    def clean(self):
        cleaned = super().clean()
        goods_received = cleaned.get('goods_received', False)
        po = cleaned.get('purchase_order')

        if goods_received and not po:
            self.add_error('purchase_order',
                           'A goods-received bill must be linked to a Purchase Order.')

        if goods_received and po and po.status != 'received':
            self.add_error('purchase_order',
                           f'PO {po.po_number} has status "{po.get_status_display()}". '
                           f'Goods must be received before posting a GRN bill.')

        return cleaned


class VendorBillItemForm(forms.ModelForm):
    """
    Form for vendor bill line items.
    Tax Code determines VAT rate - No Tax Code = 0% VAT (Out of Scope)
    """
    
    class Meta:
        model = VendorBillItem
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


VendorBillItemFormSet = forms.inlineformset_factory(
    VendorBill,
    VendorBillItem,
    form=VendorBillItemForm,
    extra=1,
    can_delete=True
)


# ============ EXPENSE CLAIM FORMS ============

class ExpenseClaimForm(forms.ModelForm):
    """Form for creating/editing expense claims."""
    
    class Meta:
        model = ExpenseClaim
        fields = ['claim_date', 'description']
        widgets = {
            'claim_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }


class ExpenseClaimItemForm(forms.ModelForm):
    """
    Form for expense claim line items.
    Tax Code determines VAT - No Tax Code or no receipt = 0% VAT
    """
    
    class Meta:
        model = ExpenseClaimItem
        fields = ['date', 'category', 'description', 'amount', 'tax_code', 'has_receipt', 
                  'receipt', 'is_non_deductible', 'expense_account']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        from apps.finance.models import Account
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['category', 'expense_account', 'tax_code']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name in ['has_receipt', 'is_non_deductible']:
                field.widget.attrs['class'] = 'form-check-input'
            elif field_name != 'date':
                field.widget.attrs['class'] = 'form-control'
        
        self.fields['expense_account'].queryset = Account.objects.filter(
            is_active=True, account_type='expense'
        )
        self.fields['expense_account'].required = False
        
        # Set Tax Code queryset
        self.fields['tax_code'].queryset = TaxCode.objects.filter(is_active=True)
        self.fields['tax_code'].required = False
        self.fields['tax_code'].empty_label = "-- No Tax (Out of Scope) --"
    
    def clean(self):
        cleaned_data = super().clean()
        has_receipt = cleaned_data.get('has_receipt')
        tax_code = cleaned_data.get('tax_code')
        
        # Warn if VAT tax code selected but no receipt
        if tax_code and tax_code.rate > 0 and not has_receipt:
            # Don't raise error - just VAT won't be claimed
            pass
        
        return cleaned_data


ExpenseClaimItemFormSet = forms.inlineformset_factory(
    ExpenseClaim,
    ExpenseClaimItem,
    form=ExpenseClaimItemForm,
    extra=1,
    can_delete=True
)


class ExpenseClaimPaymentForm(forms.Form):
    """Form for paying expense claims."""
    from apps.finance.models import BankAccount
    
    bank_account = forms.ModelChoiceField(
        queryset=None,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    payment_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    payment_reference = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Check #, Transfer Ref'})
    )
    
    def __init__(self, *args, **kwargs):
        from apps.finance.models import BankAccount
        super().__init__(*args, **kwargs)
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)


# ============ RECURRING EXPENSE FORMS ============

class RecurringExpenseForm(forms.ModelForm):
    """Form for creating/editing recurring expenses."""
    
    class Meta:
        model = RecurringExpense
        fields = [
            'name', 'vendor', 'expense_account', 'tax_code',
            'amount', 'frequency', 'start_date', 'end_date',
            'payment_mode', 'bank_account', 'auto_post', 'description', 'status'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        from apps.finance.models import Account, TaxCode, BankAccount
        super().__init__(*args, **kwargs)
        
        # Set widget classes
        for field_name, field in self.fields.items():
            if field_name in ['vendor', 'expense_account', 'tax_code', 'frequency', 
                            'payment_mode', 'bank_account', 'status']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name in ['auto_post']:
                field.widget.attrs['class'] = 'form-check-input'
            elif 'date' not in field_name and field_name != 'description':
                field.widget.attrs['class'] = 'form-control'
        
        # Set querysets
        self.fields['vendor'].queryset = Vendor.objects.filter(is_active=True)
        self.fields['expense_account'].queryset = Account.objects.filter(
            is_active=True, account_type='expense'
        )
        self.fields['tax_code'].queryset = TaxCode.objects.filter(is_active=True)
        self.fields['tax_code'].required = False
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)
        self.fields['bank_account'].required = False
        self.fields['end_date'].required = False
        self.fields['description'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        payment_mode = cleaned_data.get('payment_mode')
        bank_account = cleaned_data.get('bank_account')
        
        # Bank account required if payment mode is 'bank'
        if payment_mode == 'bank' and not bank_account:
            raise ValidationError({
                'bank_account': "Bank account is required for direct bank payment mode."
            })
        
        # End date must be after start date
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and end_date < start_date:
            raise ValidationError({
                'end_date': "End date must be after start date."
            })
        
        return cleaned_data

