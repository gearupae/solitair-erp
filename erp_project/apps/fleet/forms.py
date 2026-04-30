from django import forms
from django.forms import inlineformset_factory

from .models import Vehicle, VehicleOtherDocument


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['plate_number', 'make', 'model', 'driver', 'mulkiya_expiry', 'insurance_expiry']
        widgets = {
            'mulkiya_expiry': forms.DateInput(attrs={'type': 'date'}),
            'insurance_expiry': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.fields['driver'].queryset = User.objects.filter(is_active=True).order_by(
            'first_name', 'last_name', 'username'
        )
        self.fields['driver'].required = False
        self.fields['driver'].empty_label = '— No driver —'
        for name, field in self.fields.items():
            if name == 'driver':
                field.widget.attrs.setdefault('class', 'form-select')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class VehicleOtherDocumentForm(forms.ModelForm):
    class Meta:
        model = VehicleOtherDocument
        fields = ['document_name', 'expiry_date']
        widgets = {
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['document_name'].required = False
        self.fields['expiry_date'].required = False

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get('document_name') or '').strip()
        exp = cleaned.get('expiry_date')
        if not name and not exp:
            return cleaned
        if not name or not exp:
            raise forms.ValidationError('Document name and expiry are both required for each filled row.')
        return cleaned


VehicleOtherDocumentFormSet = inlineformset_factory(
    Vehicle,
    VehicleOtherDocument,
    form=VehicleOtherDocumentForm,
    extra=4,
    can_delete=True,
    min_num=0,
    validate_min=False,
)
