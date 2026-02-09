"""
Property Management Forms - PDC & Bank Reconciliation
"""
from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import (
    Property, Unit, Tenant, Lease, PDCCheque, 
    PDCAllocation, PDCAllocationLine, PDCBankMatch
)


class PropertyForm(forms.ModelForm):
    """Form for Property management."""
    class Meta:
        model = Property
        fields = [
            'name', 'address', 'city', 'emirate', 'country',
            'property_type', 'total_units', 'description', 'ar_account'
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class UnitForm(forms.ModelForm):
    """Form for Unit management."""
    class Meta:
        model = Unit
        fields = [
            'property', 'unit_number', 'unit_type', 'floor',
            'area_sqft', 'bedrooms', 'bathrooms', 'status', 'monthly_rent'
        ]


class TenantForm(forms.ModelForm):
    """Form for Tenant management."""
    class Meta:
        model = Tenant
        fields = [
            'name', 'email', 'phone', 'mobile', 'company',
            'emirates_id', 'trade_license', 'trn',
            'address', 'city', 'country', 'status', 'ar_account', 'notes'
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class LeaseForm(forms.ModelForm):
    """Form for Lease management."""
    class Meta:
        model = Lease
        fields = [
            'unit', 'tenant', 'start_date', 'end_date',
            'annual_rent', 'payment_frequency', 'number_of_cheques',
            'security_deposit', 'ejari_number', 'notes'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class PDCChequeForm(forms.ModelForm):
    """Form for PDC Cheque entry."""
    class Meta:
        model = PDCCheque
        fields = [
            'tenant', 'lease', 'cheque_number', 'bank_name', 'cheque_date',
            'amount', 'drawer_name', 'drawer_account', 'purpose',
            'payment_period_start', 'payment_period_end', 'notes'
        ]
        widgets = {
            'cheque_date': forms.DateInput(attrs={'type': 'date'}),
            'payment_period_start': forms.DateInput(attrs={'type': 'date'}),
            'payment_period_end': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        cheque_number = cleaned_data.get('cheque_number')
        bank_name = cleaned_data.get('bank_name')
        cheque_date = cleaned_data.get('cheque_date')
        amount = cleaned_data.get('amount')
        tenant = cleaned_data.get('tenant')
        
        # Check for duplicate PDC (composite uniqueness)
        if cheque_number and bank_name and cheque_date and amount and tenant:
            existing = PDCCheque.objects.filter(
                cheque_number=cheque_number,
                bank_name=bank_name,
                cheque_date=cheque_date,
                amount=amount,
                tenant=tenant,
                is_active=True
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise ValidationError(
                    'A PDC with the same cheque number, bank, date, amount, and tenant already exists.'
                )
        
        return cleaned_data


class PDCDepositForm(forms.Form):
    """Form for depositing PDC to bank."""
    bank_account = forms.ModelChoiceField(
        queryset=None,
        label='Deposit to Bank',
        help_text='Select the bank account to deposit this cheque'
    )
    deposit_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Date of deposit'
    )
    
    def __init__(self, *args, **kwargs):
        from apps.finance.models import BankAccount
        super().__init__(*args, **kwargs)
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)


class PDCClearForm(forms.Form):
    """Form for clearing a PDC."""
    clearing_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Date cheque was cleared by bank'
    )
    clearing_reference = forms.CharField(
        max_length=100,
        required=False,
        help_text='Bank reference number for clearing'
    )


class PDCBounceForm(forms.Form):
    """Form for recording a bounced PDC."""
    bounce_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Date cheque bounced'
    )
    bounce_reason = forms.CharField(
        max_length=200,
        required=True,
        help_text='Reason for bounce (e.g., Insufficient Funds, Signature Mismatch)'
    )
    bounce_charges = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        initial=Decimal('0.00'),
        required=False,
        help_text='Bounce charges to be recovered from tenant'
    )


class PDCAllocationForm(forms.ModelForm):
    """Form for manual PDC allocation."""
    class Meta:
        model = PDCAllocation
        fields = ['allocation_date', 'reason', 'notes']
        widgets = {
            'allocation_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class PDCAllocationLineForm(forms.ModelForm):
    """Form for individual allocation line."""
    class Meta:
        model = PDCAllocationLine
        fields = ['pdc', 'amount', 'notes']
    
    def __init__(self, *args, bank_statement_line=None, **kwargs):
        super().__init__(*args, **kwargs)
        if bank_statement_line:
            # Only show deposited PDCs that match the bank statement criteria
            self.fields['pdc'].queryset = PDCCheque.objects.filter(
                status='deposited',
                deposit_status='in_clearing',
                deposited_to_bank=bank_statement_line.statement.bank_account,
                is_active=True
            )


class PDCAllocationLineFormSet(forms.BaseInlineFormSet):
    """Formset for PDC allocation lines with validation."""
    
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        
        total_allocated = Decimal('0.00')
        pdcs_used = set()
        
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                pdc = form.cleaned_data.get('pdc')
                amount = form.cleaned_data.get('amount', Decimal('0.00'))
                
                if pdc:
                    if pdc.pk in pdcs_used:
                        raise ValidationError(f'PDC {pdc.pdc_number} is allocated multiple times.')
                    pdcs_used.add(pdc.pk)
                    
                    if amount > pdc.amount:
                        raise ValidationError(
                            f'Allocated amount ({amount}) exceeds PDC amount ({pdc.amount}) for {pdc.pdc_number}'
                        )
                    
                    total_allocated += amount
        
        return total_allocated


class BankStatementMatchForm(forms.Form):
    """Form for matching bank statement lines with PDCs."""
    match_by_amount = forms.BooleanField(required=False, initial=True)
    match_by_date = forms.BooleanField(required=False, initial=True)
    match_by_cheque_number = forms.BooleanField(required=False, initial=False)
    date_tolerance_days = forms.IntegerField(
        initial=3,
        min_value=0,
        max_value=30,
        help_text='Number of days tolerance for date matching'
    )


class BulkPDCForm(forms.Form):
    """Form for bulk PDC entry from lease."""
    lease = forms.ModelChoiceField(
        queryset=Lease.objects.filter(is_active=True, status='active'),
        label='Select Lease'
    )
    bank_name = forms.CharField(max_length=200)
    first_cheque_number = forms.CharField(max_length=50)
    drawer_name = forms.CharField(max_length=200, required=False)
    drawer_account = forms.CharField(max_length=50, required=False)
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )
    
    def clean_first_cheque_number(self):
        """Ensure cheque number is numeric for auto-increment."""
        value = self.cleaned_data['first_cheque_number']
        try:
            int(value)
        except ValueError:
            raise ValidationError('First cheque number must be numeric for auto-increment.')
        return value




