"""Forms for the Advances module."""
from datetime import date
from decimal import Decimal

from django import forms

from .models import (
    CustomerAdvance,
    CustomerAdvanceApplication,
    VendorAdvance,
    VendorAdvanceApplication,
    SecurityChequeOutward,
)


class _BootstrapMixin:
    """Apply Bootstrap classes to all form fields."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', 'form-control')
                widget.attrs.setdefault('rows', 2)
            else:
                widget.attrs.setdefault('class', 'form-control')


class CustomerAdvanceForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CustomerAdvance
        fields = ['date', 'reference', 'bank_account', 'amount', 'vat_amount', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.finance.models import BankAccount
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)
        self.fields['vat_amount'].help_text = 'Auto-calculated at 5% — you may override.'
        self.fields['amount'].widget.attrs['id'] = 'id_ca_amount'
        self.fields['vat_amount'].widget.attrs['id'] = 'id_ca_vat_amount'

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get('amount') or Decimal('0.00')
        vat = cleaned.get('vat_amount') or Decimal('0.00')
        if amount <= 0:
            self.add_error('amount', 'Amount must be greater than zero.')
        if vat < 0:
            self.add_error('vat_amount', 'VAT amount cannot be negative.')
        return cleaned


class CustomerAdvanceApplicationForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CustomerAdvanceApplication
        fields = ['invoice', 'date', 'amount_applied', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, advance=None, **kwargs):
        super().__init__(*args, **kwargs)
        if advance:
            from apps.sales.models import Invoice
            self.fields['invoice'].queryset = Invoice.objects.filter(
                customer=advance.customer,
                status__in=['posted', 'sent', 'partial', 'overdue'],
            ).order_by('-invoice_date')
            self.fields['invoice'].label_from_instance = lambda obj: (
                f'{obj.invoice_number} — AED {obj.total_amount:,.2f} '
                f'(due: AED {obj.total_amount - obj.paid_amount:,.2f})'
            )
        self.advance = advance

    def clean_amount_applied(self):
        amount = self.cleaned_data.get('amount_applied')
        if not amount or amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        if self.advance and amount > self.advance.balance:
            raise forms.ValidationError(
                f'Exceeds advance balance (AED {self.advance.balance:,.2f}).'
            )
        return amount

    def clean(self):
        cleaned = super().clean()
        invoice = cleaned.get('invoice')
        amount = cleaned.get('amount_applied') or Decimal('0.00')
        if invoice and amount:
            balance_due = invoice.total_amount - invoice.paid_amount
            if amount > balance_due:
                self.add_error(
                    'amount_applied',
                    f'Exceeds invoice balance due (AED {balance_due:,.2f}).',
                )
        return cleaned


class VendorAdvanceForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = VendorAdvance
        fields = ['date', 'reference', 'bank_account', 'amount', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.finance.models import BankAccount
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if not amount or amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount


class VendorAdvanceApplicationForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = VendorAdvanceApplication
        fields = ['bill', 'date', 'amount_applied', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, advance=None, **kwargs):
        super().__init__(*args, **kwargs)
        if advance:
            from apps.purchase.models import VendorBill
            self.fields['bill'].queryset = VendorBill.objects.filter(
                vendor=advance.vendor,
                status__in=['posted', 'pending', 'partial', 'overdue'],
            ).order_by('-bill_date')
            self.fields['bill'].label_from_instance = lambda obj: (
                f'{obj.bill_number} — AED {obj.total_amount:,.2f} '
                f'(due: AED {obj.total_amount - obj.paid_amount:,.2f})'
            )
        self.advance = advance

    def clean_amount_applied(self):
        amount = self.cleaned_data.get('amount_applied')
        if not amount or amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        if self.advance and amount > self.advance.balance:
            raise forms.ValidationError(
                f'Exceeds advance balance (AED {self.advance.balance:,.2f}).'
            )
        return amount

    def clean(self):
        cleaned = super().clean()
        bill = cleaned.get('bill')
        amount = cleaned.get('amount_applied') or Decimal('0.00')
        if bill and amount:
            balance_due = bill.total_amount - bill.paid_amount
            if amount > balance_due:
                self.add_error(
                    'amount_applied',
                    f'Exceeds bill balance due (AED {balance_due:,.2f}).',
                )
        return cleaned


class SecurityChequeOutwardForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SecurityChequeOutward
        fields = [
            'party_name', 'cheque_number', 'cheque_date', 'bank_name',
            'amount', 'issued_date', 'purpose', 'notes',
        ]
        widgets = {
            'cheque_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'issued_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if not amount or amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount


class SecurityChequeEncashForm(_BootstrapMixin, forms.Form):
    encash_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        initial=date.today,
    )
    bank_account = forms.ModelChoiceField(
        queryset=None,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Bank Account',
    )
    confirm = forms.BooleanField(
        required=True,
        label='I confirm this cheque has been encashed and the amount should be credited from the bank.',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.finance.models import BankAccount
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)


class SecurityChequeReturnForm(_BootstrapMixin, forms.Form):
    return_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        initial=date.today,
        label='Return Date',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        label='Notes',
    )
