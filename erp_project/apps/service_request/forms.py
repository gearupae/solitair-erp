"""
Service Request forms.
"""
from django import forms
from .models import ServiceRequest, ServiceRequestItem, ServiceRequestAttachment


class ServiceRequestForm(forms.ModelForm):
    """Form for creating/editing service requests."""
    
    class Meta:
        model = ServiceRequest
        fields = ['date', 'required_by_date', 'department', 'priority', 'status', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'required_by_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.hr.models import Department
        self.fields['department'].queryset = Department.objects.filter(is_active=True)
        self.fields['required_by_date'].required = False
        self.fields['notes'].required = False


class ServiceRequestItemForm(forms.ModelForm):
    class Meta:
        model = ServiceRequestItem
        fields = ['service_description', 'vendor', 'quantity', 'unit', 'estimated_unit_cost']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.purchase.models import Vendor
        self.fields['vendor'].queryset = Vendor.objects.filter(is_active=True, status='active')
        self.fields['vendor'].widget.attrs['class'] = 'form-select'
        self.fields['vendor'].required = False
        for field_name, field in self.fields.items():
            if field_name != 'vendor':
                field.widget.attrs['class'] = 'form-control'


ServiceRequestItemFormSet = forms.inlineformset_factory(
    ServiceRequest,
    ServiceRequestItem,
    form=ServiceRequestItemForm,
    extra=1,
    can_delete=True
)


class ServiceRequestAttachmentForm(forms.ModelForm):
    class Meta:
        model = ServiceRequestAttachment
        fields = ['file']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }


class ServiceRequestRejectForm(forms.Form):
    """Form for reject/return with comments."""
    comment = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Enter comment/reason...'}),
        label='Comment'
    )
