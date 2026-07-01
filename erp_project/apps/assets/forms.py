from django import forms
from django.utils import timezone

from apps.projects.models import Project

from .models import AssetCategory, FixedAsset


class AssetCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategory
        fields = [
            'name', 'code', 'description',
            'depreciation_method', 'useful_life_years', 'salvage_value_percent',
            'partial_month_policy', 'depreciation_start_policy',
            'asset_account', 'depreciation_expense_account', 'accumulated_depreciation_account',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'depreciation_method': forms.Select(attrs={'class': 'form-select'}),
            'useful_life_years': forms.NumberInput(attrs={'class': 'form-control'}),
            'salvage_value_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'partial_month_policy': forms.Select(attrs={'class': 'form-select'}),
            'depreciation_start_policy': forms.Select(attrs={'class': 'form-select'}),
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


class AssetOperationalForm(forms.ModelForm):
    """Operational fields editable on active assets (allocation rates & location)."""

    class Meta:
        model = FixedAsset
        fields = [
            'current_location', 'cost_per_hour', 'ownership_type', 'rental_rate_per_day',
        ]
        widgets = {
            'current_location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Warehouse / site'}),
            'cost_per_hour': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'ownership_type': forms.Select(attrs={'class': 'form-select'}),
            'rental_rate_per_day': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class EquipmentAllocationForm(forms.Form):
    project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    start_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    expected_end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.filter(
            is_active=True,
        ).exclude(status__in=('completed', 'cancelled')).order_by('project_code', 'name')


class EquipmentReturnForm(forms.Form):
    return_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    hours_used = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Auto from days × 8 if blank'}),
    )
    warehouse_location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Warehouse'}),
    )


class EquipmentTransferForm(forms.Form):
    target_project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Transfer to project',
    )
    transfer_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, exclude_project=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Project.objects.filter(is_active=True).exclude(
            status__in=('completed', 'cancelled'),
        ).order_by('project_code', 'name')
        if exclude_project:
            qs = qs.exclude(pk=exclude_project.pk)
        self.fields['target_project'].queryset = qs


class EquipmentMaintenanceForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Damage / service required…'}),
    )

