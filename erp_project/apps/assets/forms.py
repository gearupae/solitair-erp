from django import forms
from .models import AssetCategory, FixedAsset


class AssetCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategory
        fields = [
            'name', 'code', 'description',
            'depreciation_method', 'useful_life_years', 'salvage_value_percent',
            'asset_account', 'depreciation_expense_account', 'accumulated_depreciation_account'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'depreciation_method': forms.Select(attrs={'class': 'form-select'}),
            'useful_life_years': forms.NumberInput(attrs={'class': 'form-control'}),
            'salvage_value_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'asset_account': forms.Select(attrs={'class': 'form-select'}),
            'depreciation_expense_account': forms.Select(attrs={'class': 'form-select'}),
            'accumulated_depreciation_account': forms.Select(attrs={'class': 'form-select'}),
        }


class FixedAssetForm(forms.ModelForm):
    class Meta:
        model = FixedAsset
        fields = [
            'name', 'description', 'category',
            'serial_number', 'location', 'custodian',
            'acquisition_date', 'acquisition_cost', 'vendor', 'purchase_invoice',
            'depreciation_method', 'useful_life_years', 'salvage_value', 'depreciation_start_date'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'serial_number': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'custodian': forms.Select(attrs={'class': 'form-select'}),
            'acquisition_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'acquisition_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'vendor': forms.Select(attrs={'class': 'form-select'}),
            'purchase_invoice': forms.TextInput(attrs={'class': 'form-control'}),
            'depreciation_method': forms.Select(attrs={'class': 'form-select'}),
            'useful_life_years': forms.NumberInput(attrs={'class': 'form-control'}),
            'salvage_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'depreciation_start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class DisposalForm(forms.Form):
    disposal_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    disposal_amount = forms.DecimalField(
        max_digits=15, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
    )




