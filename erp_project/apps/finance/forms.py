"""
Finance Forms - UAE VAT & Corporate Tax Compliant
"""
from django import forms
from django.core.exceptions import ValidationError
from .models import (
    Account, FiscalYear, AccountingPeriod, JournalEntry, JournalEntryLine, 
    TaxCode, Payment, BankAccount, ExpenseClaim, ExpenseItem, VATReturn,
    CorporateTaxComputation, Budget, BudgetLine, BankTransfer, BankReconciliation,
    BankStatement, BankStatementLine, OpeningBalanceEntry, OpeningBalanceLine,
    WriteOff, ExchangeRate
)


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['code', 'name', 'account_type', 'account_category', 'parent', 'description', 
                  'opening_balance', 'is_cash_account', 'overdraft_allowed', 'is_contra_account']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['account_type', 'parent', 'account_category']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name in ['is_cash_account', 'overdraft_allowed', 'is_contra_account']:
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'
        self.fields['parent'].queryset = Account.objects.filter(is_active=True)
        self.fields['account_category'].required = False
        
        # Add help text for boolean fields
        self.fields['is_cash_account'].help_text = 'Check for Bank and Cash accounts (affects Cash Flow Statement)'
        self.fields['overdraft_allowed'].help_text = 'Allow negative balance (for bank overdraft accounts)'
        self.fields['is_contra_account'].help_text = 'Contra accounts have opposite normal balance (e.g., Accumulated Depreciation)'
    
    def clean_code(self):
        code = self.cleaned_data['code']
        # Check for duplicate (excluding current instance)
        qs = Account.objects.filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Account code already exists.")
        return code
    
    def clean_opening_balance(self):
        opening_balance = self.cleaned_data['opening_balance']
        if self.instance.pk and self.instance.opening_balance_locked:
            if opening_balance != self.instance.opening_balance:
                raise ValidationError("Opening balance cannot be changed after posting.")
        return opening_balance


class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ['name', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['class'] = 'form-control'


class AccountingPeriodForm(forms.ModelForm):
    class Meta:
        model = AccountingPeriod
        fields = ['fiscal_year', 'name', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class JournalEntryForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ['date', 'reference', 'description', 'fiscal_year', 'period']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reference'].widget.attrs['class'] = 'form-control'
        self.fields['fiscal_year'].widget.attrs['class'] = 'form-select'
        self.fields['fiscal_year'].queryset = FiscalYear.objects.filter(is_closed=False, is_active=True)
        self.fields['period'].widget.attrs['class'] = 'form-select'
        self.fields['period'].queryset = AccountingPeriod.objects.filter(is_locked=False, is_active=True)
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Check if entry is being edited and is already posted
        if self.instance.pk and self.instance.status in ['posted', 'reversed']:
            raise ValidationError("Posted or reversed entries cannot be edited. Use reversal instead.")
        
        # Check period is not locked
        period = cleaned_data.get('period')
        if period and period.is_locked:
            raise ValidationError(f"Accounting period {period.name} is locked. No posting allowed.")
        
        # Check fiscal year is not closed
        fiscal_year = cleaned_data.get('fiscal_year')
        if fiscal_year and fiscal_year.is_closed:
            raise ValidationError(f"Fiscal year {fiscal_year.name} is closed. No posting allowed.")
        
        # FISCAL YEAR BOUNDARY: Entry date must fall within fiscal year
        date_val = cleaned_data.get('date')
        if fiscal_year and date_val:
            fy_start = fiscal_year.start_date
            fy_end = fiscal_year.end_date
            if date_val < fy_start or date_val > fy_end:
                raise ValidationError(
                    f"Entry date {date_val} is outside fiscal year {fiscal_year.name} "
                    f"({fy_start} to {fy_end}). Choose a date within the fiscal period."
                )
        
        return cleaned_data


class JournalEntryLineForm(forms.ModelForm):
    class Meta:
        model = JournalEntryLine
        fields = ['account', 'description', 'debit', 'credit']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show leaf accounts (accounts without children)
        self.fields['account'].queryset = Account.objects.filter(is_active=True)
        self.fields['account'].widget.attrs['class'] = 'form-select'
        for field_name in ['description', 'debit', 'credit']:
            self.fields[field_name].widget.attrs['class'] = 'form-control'
    
    def clean_account(self):
        account = self.cleaned_data['account']
        if account and not account.is_leaf:
            raise ValidationError(f"Cannot post to parent account '{account.code}'. Only leaf accounts allowed.")
        return account
    
    def clean(self):
        cleaned_data = super().clean()
        debit = cleaned_data.get('debit', 0) or 0
        credit = cleaned_data.get('credit', 0) or 0
        
        if debit > 0 and credit > 0:
            raise ValidationError("A line cannot have both debit and credit amounts.")
        
        if debit == 0 and credit == 0:
            raise ValidationError("Either debit or credit must be greater than zero.")
        
        return cleaned_data


JournalEntryLineFormSet = forms.inlineformset_factory(
    JournalEntry,
    JournalEntryLine,
    form=JournalEntryLineForm,
    extra=2,
    can_delete=True,
    min_num=2,
    validate_min=True
)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['payment_type', 'payment_method', 'payment_date', 'party_name', 'amount', 
                  'reference', 'notes', 'bank_account']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['payment_type', 'payment_method', 'bank_account']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name not in ['notes', 'payment_date']:
                field.widget.attrs['class'] = 'form-control'
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Check if payment is being edited and is already confirmed
        if self.instance.pk and self.instance.status in ['confirmed', 'cancelled']:
            raise ValidationError("Confirmed or cancelled payments cannot be edited.")
        
        return cleaned_data


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['name', 'account_number', 'bank_name', 'branch', 'swift_code', 'iban', 
                  'currency', 'gl_account']
        widgets = {
            'iban': forms.TextInput(attrs={'placeholder': 'AE07 0331 234567 890123456'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == 'gl_account':
                field.widget.attrs['class'] = 'form-select'
                # Only show bank-type accounts
                field.queryset = Account.objects.filter(
                    is_active=True, 
                    account_type='asset'
                )
            else:
                field.widget.attrs['class'] = 'form-control'


class TaxCodeForm(forms.ModelForm):
    class Meta:
        model = TaxCode
        fields = ['code', 'name', 'tax_type', 'rate', 'description', 'is_default', 
                  'sales_account', 'purchase_account']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['sales_account', 'purchase_account', 'tax_type']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name == 'is_default':
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'
        
        # Sales account should be liability (VAT Payable)
        self.fields['sales_account'].queryset = Account.objects.filter(
            is_active=True, account_type='liability'
        )
        # Purchase account should be asset (VAT Recoverable)
        self.fields['purchase_account'].queryset = Account.objects.filter(
            is_active=True, account_type='asset'
        )


class ExpenseClaimForm(forms.ModelForm):
    class Meta:
        model = ExpenseClaim
        fields = ['claim_date', 'description']
        widgets = {
            'claim_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }


class ExpenseItemForm(forms.ModelForm):
    class Meta:
        model = ExpenseItem
        fields = ['date', 'category', 'description', 'amount', 'vat_amount', 'has_receipt', 
                  'receipt', 'is_non_deductible', 'expense_account']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['category', 'expense_account']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name in ['has_receipt', 'is_non_deductible']:
                field.widget.attrs['class'] = 'form-check-input'
            elif field_name != 'date':
                field.widget.attrs['class'] = 'form-control'
        
        self.fields['expense_account'].queryset = Account.objects.filter(
            is_active=True, account_type='expense'
        )
    
    def clean(self):
        cleaned_data = super().clean()
        has_receipt = cleaned_data.get('has_receipt')
        vat_amount = cleaned_data.get('vat_amount', 0) or 0
        
        # VAT can only be claimed with valid receipt
        if vat_amount > 0 and not has_receipt:
            raise ValidationError("VAT can only be claimed with a valid receipt.")
        
        return cleaned_data


ExpenseItemFormSet = forms.inlineformset_factory(
    ExpenseClaim,
    ExpenseItem,
    form=ExpenseItemForm,
    extra=1,
    can_delete=True
)


class VATReturnForm(forms.ModelForm):
    class Meta:
        model = VATReturn
        fields = ['period_type', 'period_start', 'period_end', 'due_date', 
                  'standard_rated_supplies', 'standard_rated_vat',
                  'zero_rated_supplies', 'exempt_supplies',
                  'standard_rated_expenses', 'input_vat',
                  'adjustments', 'adjustment_reason', 'notes']
        widgets = {
            'period_start': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'period_end': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'adjustment_reason': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == 'period_type':
                field.widget.attrs['class'] = 'form-select'
            elif 'date' not in field_name and field_name not in ['notes', 'adjustment_reason']:
                field.widget.attrs['class'] = 'form-control'
    
    def clean(self):
        cleaned_data = super().clean()
        adjustments = cleaned_data.get('adjustments', 0) or 0
        adjustment_reason = cleaned_data.get('adjustment_reason', '')
        
        # VAT adjustments require reason (FTA requirement)
        if adjustments != 0 and not adjustment_reason:
            raise ValidationError("Adjustment reason is mandatory for VAT adjustments.")
        
        return cleaned_data


class CorporateTaxForm(forms.ModelForm):
    class Meta:
        model = CorporateTaxComputation
        fields = ['fiscal_year', 'revenue', 'expenses', 'non_deductible_expenses', 
                  'exempt_income', 'other_adjustments', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name == 'fiscal_year':
                field.widget.attrs['class'] = 'form-select'
                field.queryset = FiscalYear.objects.filter(is_active=True)
            elif field_name != 'notes':
                field.widget.attrs['class'] = 'form-control'


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['name', 'fiscal_year', 'period_type', 'department', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['fiscal_year', 'period_type']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name != 'notes':
                field.widget.attrs['class'] = 'form-control'
        self.fields['fiscal_year'].queryset = FiscalYear.objects.filter(is_active=True, is_closed=False)


class BudgetLineForm(forms.ModelForm):
    class Meta:
        model = BudgetLine
        fields = ['account', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 
                  'jul', 'aug', 'sep', 'oct', 'nov', 'dec', 'notes']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].widget.attrs['class'] = 'form-select'
        self.fields['account'].queryset = Account.objects.filter(
            is_active=True, 
            account_type__in=['income', 'expense']
        )
        for field_name in ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 
                          'jul', 'aug', 'sep', 'oct', 'nov', 'dec', 'notes']:
            self.fields[field_name].widget.attrs['class'] = 'form-control'


BudgetLineFormSet = forms.inlineformset_factory(
    Budget,
    BudgetLine,
    form=BudgetLineForm,
    extra=5,
    can_delete=True
)


class BankTransferForm(forms.ModelForm):
    class Meta:
        model = BankTransfer
        fields = ['transfer_date', 'from_bank', 'to_bank', 'amount', 'reference', 'notes']
        widgets = {
            'transfer_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['from_bank', 'to_bank']:
                field.widget.attrs['class'] = 'form-select'
                field.queryset = BankAccount.objects.filter(is_active=True)
            elif field_name not in ['transfer_date', 'notes']:
                field.widget.attrs['class'] = 'form-control'
    
    def clean(self):
        cleaned_data = super().clean()
        from_bank = cleaned_data.get('from_bank')
        to_bank = cleaned_data.get('to_bank')
        
        if from_bank and to_bank and from_bank == to_bank:
            raise ValidationError("Source and destination bank cannot be the same.")
        
        return cleaned_data


class BankReconciliationForm(forms.ModelForm):
    class Meta:
        model = BankReconciliation
        fields = ['bank_account', 'bank_statement', 'reconciliation_date', 'period_start', 'period_end',
                  'statement_opening_balance', 'statement_closing_balance', 'notes']
        widgets = {
            'reconciliation_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'period_start': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'period_end': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['bank_account', 'bank_statement']:
                field.widget.attrs['class'] = 'form-select'
                if field_name == 'bank_account':
                    field.queryset = BankAccount.objects.filter(is_active=True)
                else:
                    field.queryset = BankStatement.objects.filter(is_active=True, status__in=['draft', 'in_progress'])
            elif 'date' not in field_name and field_name != 'notes':
                field.widget.attrs['class'] = 'form-control'


class BankStatementForm(forms.ModelForm):
    """Form for creating/editing bank statements."""
    class Meta:
        model = BankStatement
        fields = ['bank_account', 'statement_start_date', 'statement_end_date', 
                  'opening_balance', 'closing_balance', 'notes']
        widgets = {
            'statement_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'statement_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bank_account'].widget.attrs['class'] = 'form-select'
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)
        self.fields['opening_balance'].widget.attrs['class'] = 'form-control'
        self.fields['closing_balance'].widget.attrs['class'] = 'form-control'
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('statement_start_date')
        end_date = cleaned_data.get('statement_end_date')
        
        if start_date and end_date and start_date > end_date:
            raise ValidationError("Start date cannot be after end date.")
        
        return cleaned_data


class BankStatementLineForm(forms.ModelForm):
    """Form for bank statement lines."""
    class Meta:
        model = BankStatementLine
        fields = ['transaction_date', 'value_date', 'description', 'reference', 
                  'debit', 'credit', 'balance']
        widgets = {
            'transaction_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'value_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if 'date' not in field_name:
                field.widget.attrs['class'] = 'form-control'
    
    def clean(self):
        cleaned_data = super().clean()
        debit = cleaned_data.get('debit', 0) or 0
        credit = cleaned_data.get('credit', 0) or 0
        
        if debit > 0 and credit > 0:
            raise ValidationError("A line cannot have both debit and credit amounts.")
        
        if debit == 0 and credit == 0:
            raise ValidationError("Either debit or credit must be greater than zero.")
        
        return cleaned_data


BankStatementLineFormSet = forms.inlineformset_factory(
    BankStatement,
    BankStatementLine,
    form=BankStatementLineForm,
    extra=5,
    can_delete=True
)


class StatementLineMatchForm(forms.Form):
    """Form for manually matching statement lines."""
    statement_line = forms.ModelChoiceField(
        queryset=BankStatementLine.objects.filter(reconciliation_status='unmatched'),
        widget=forms.HiddenInput()
    )
    match_type = forms.ChoiceField(
        choices=[('payment', 'Payment'), ('journal', 'Journal Entry')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    payment = forms.ModelChoiceField(
        queryset=Payment.objects.filter(status='confirmed'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    journal_line = forms.ModelChoiceField(
        queryset=JournalEntryLine.objects.filter(journal_entry__status='posted'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        match_type = cleaned_data.get('match_type')
        payment = cleaned_data.get('payment')
        journal_line = cleaned_data.get('journal_line')
        
        if match_type == 'payment' and not payment:
            raise ValidationError("Please select a payment to match.")
        if match_type == 'journal' and not journal_line:
            raise ValidationError("Please select a journal entry line to match.")
        
        return cleaned_data


class AdjustmentForm(forms.Form):
    """Form for creating adjustment entries for unmatched statement lines."""
    ADJUSTMENT_TYPE_CHOICES = [
        ('bank_charge', 'Bank Charge'),
        ('bank_interest', 'Bank Interest'),
        ('fx_difference', 'FX Difference'),
        ('other', 'Other'),
    ]
    
    statement_line = forms.ModelChoiceField(
        queryset=BankStatementLine.objects.filter(reconciliation_status='unmatched'),
        widget=forms.HiddenInput()
    )
    adjustment_type = forms.ChoiceField(
        choices=ADJUSTMENT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    expense_account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True, account_type__in=['expense', 'income']),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Select expense account for charges, income account for interest"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # For bank charges: expense accounts
        # For bank interest: income accounts
        self.fields['expense_account'].queryset = Account.objects.filter(
            is_active=True, 
            account_type__in=['expense', 'income']
        ).order_by('account_type', 'code')


class OpeningBalanceEntryForm(forms.ModelForm):
    """Form for creating Opening Balance Entries."""
    class Meta:
        model = OpeningBalanceEntry
        fields = ['entry_type', 'fiscal_year', 'entry_date', 'description', 'notes']
        widgets = {
            'entry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['entry_type'].widget.attrs['class'] = 'form-select'
        self.fields['fiscal_year'].widget.attrs['class'] = 'form-select'
        self.fields['fiscal_year'].queryset = FiscalYear.objects.filter(is_active=True, is_closed=False)


class OpeningBalanceLineForm(forms.ModelForm):
    """Form for Opening Balance Entry lines."""
    class Meta:
        model = OpeningBalanceLine
        fields = ['account', 'description', 'customer', 'vendor', 'bank_account',
                  'debit', 'credit', 'reference_number', 'reference_date', 'due_date']
        widgets = {
            'reference_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['account', 'customer', 'vendor', 'bank_account']:
                field.widget.attrs['class'] = 'form-select'
            elif 'date' not in field_name:
                field.widget.attrs['class'] = 'form-control'
        
        self.fields['account'].queryset = Account.objects.filter(is_active=True)
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)
        self.fields['customer'].required = False
        self.fields['vendor'].required = False
        self.fields['bank_account'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        debit = cleaned_data.get('debit', 0) or 0
        credit = cleaned_data.get('credit', 0) or 0
        
        if debit > 0 and credit > 0:
            raise ValidationError("A line cannot have both debit and credit amounts.")
        
        if debit == 0 and credit == 0:
            raise ValidationError("Either debit or credit must be greater than zero.")
        
        return cleaned_data


OpeningBalanceLineFormSet = forms.inlineformset_factory(
    OpeningBalanceEntry,
    OpeningBalanceLine,
    form=OpeningBalanceLineForm,
    extra=5,
    can_delete=True
)


class WriteOffForm(forms.ModelForm):
    """Form for creating Write-Off entries."""
    class Meta:
        model = WriteOff
        fields = ['writeoff_type', 'writeoff_date', 'description', 'amount',
                  'source_account', 'expense_account', 'customer', 'vendor',
                  'reference_type', 'reference_number', 'notes']
        widgets = {
            'writeoff_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['writeoff_type', 'source_account', 'expense_account', 'customer', 'vendor']:
                field.widget.attrs['class'] = 'form-select'
            elif field_name not in ['writeoff_date', 'description', 'notes']:
                field.widget.attrs['class'] = 'form-control'
        
        # Source account - typically AR or AP
        self.fields['source_account'].queryset = Account.objects.filter(
            is_active=True, 
            account_type__in=['asset', 'liability']
        )
        # Expense account for write-off
        self.fields['expense_account'].queryset = Account.objects.filter(
            is_active=True, 
            account_type='expense'
        )
        self.fields['customer'].required = False
        self.fields['vendor'].required = False
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount and amount <= 0:
            raise ValidationError("Amount must be greater than zero.")
        return amount


class ExchangeRateForm(forms.ModelForm):
    """Form for exchange rates."""
    class Meta:
        model = ExchangeRate
        fields = ['currency_code', 'rate_date', 'rate', 'source']
        widgets = {
            'rate_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if 'date' not in field_name:
                field.widget.attrs['class'] = 'form-control'
        self.fields['currency_code'].widget.attrs['placeholder'] = 'USD, EUR, GBP, etc.'
        self.fields['source'].widget.attrs['placeholder'] = 'e.g., UAE Central Bank'
    
    def clean_currency_code(self):
        code = self.cleaned_data.get('currency_code', '').upper()
        if len(code) != 3:
            raise ValidationError("Currency code must be 3 characters (ISO 4217).")
        return code
