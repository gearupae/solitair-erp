"""
Settings app forms.
"""
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Role, CompanySettings, Company


class UserForm(UserCreationForm):
    """Form for creating/editing users."""
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2', 'is_active']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make password fields optional for editing
        if self.instance and self.instance.pk:
            self.fields['password1'].required = False
            self.fields['password2'].required = False
            self.fields['password1'].help_text = 'Leave blank to keep current password'
        
        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'
            if field_name == 'is_active':
                field.widget.attrs['class'] = 'form-check-input'
    
    def clean_username(self):
        """Override to exclude current instance from uniqueness check."""
        username = self.cleaned_data.get('username')
        if username:
            qs = User.objects.filter(username=username)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A user with that username already exists.")
        return username
    
    def clean_password1(self):
        """Override to allow empty password when editing."""
        password1 = self.cleaned_data.get('password1')
        
        # If editing and password is empty, skip validation
        if self.instance and self.instance.pk and not password1:
            return password1
        
        # Otherwise, run password validators
        if password1:
            from django.contrib.auth.password_validation import validate_password
            validate_password(password1, self.instance)
        
        return password1
    
    def clean_password2(self):
        """Override to allow empty passwords when editing."""
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        
        # If editing and both passwords are empty, skip validation
        if self.instance and self.instance.pk and not password1 and not password2:
            return password2
        
        # Otherwise, validate passwords match
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("The two password fields didn't match.")
        
        return password2
    
    def validate_passwords(self, password1_field_name="password1", password2_field_name="password2"):
        """Override to skip required validation when editing without password change."""
        password1 = self.cleaned_data.get(password1_field_name)
        password2 = self.cleaned_data.get(password2_field_name)
        
        # If editing and both passwords are empty, skip validation entirely
        if self.instance and self.instance.pk and not password1 and not password2:
            return
        
        # Otherwise, use parent validation
        if not password1 and password1_field_name not in self.errors:
            error = forms.ValidationError(
                self.fields[password1_field_name].error_messages["required"],
                code="required",
            )
            self.add_error(password1_field_name, error)

        if not password2 and password2_field_name not in self.errors:
            error = forms.ValidationError(
                self.fields[password2_field_name].error_messages["required"],
                code="required",
            )
            self.add_error(password2_field_name, error)

        if password1 and password2 and password1 != password2:
            error = forms.ValidationError("The two password fields didn't match.", code="password_mismatch")
            self.add_error(password2_field_name, error)
    
    def _post_clean(self):
        """Override to skip password validation when editing without password change."""
        super(forms.ModelForm, self)._post_clean()
        # Skip the UserCreationForm's _post_clean which validates password
    
    def save(self, commit=True):
        user = super().save(commit=False)
        if self.instance.pk and not self.cleaned_data.get('password1'):
            # Don't update password if not provided
            user.password = User.objects.get(pk=self.instance.pk).password
        if commit:
            user.save()
        return user


class RoleForm(forms.ModelForm):
    """Form for creating/editing roles."""
    
    class Meta:
        model = Role
        fields = ['name', 'code', 'description', 'is_system_role', 'is_active']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ['is_system_role', 'is_active']:
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'


class CompanyForm(forms.ModelForm):
    """Legal entity / employing company (HR)."""

    class Meta:
        model = Company
        fields = [
            'name',
            'trade_license_number',
            'country',
            'mol_number',
            'bank_iban',
            'bank_routing_code',
            'address',
            'logo',
            'is_active',
        ]
        widgets = {'address': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ('country',):
                field.widget.attrs['class'] = 'form-select'
            elif name == 'is_active':
                field.widget.attrs['class'] = 'form-check-input'
            elif name == 'logo':
                field.widget.attrs['class'] = 'form-control'
            elif name != 'address':
                field.widget.attrs['class'] = 'form-control'


class CompanySettingsForm(forms.ModelForm):
    """Form for company settings."""
    
    class Meta:
        model = CompanySettings
        fields = [
            'company_name', 'logo', 'address', 'phone', 'email',
            'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
            'smtp_use_tls', 'smtp_from_email',
            'website',
            'tax_id', 'fiscal_year_start', 'currency', 'date_format', 'timezone',
            'inventory_valuation_method',
            'contract_default_terms',
            'estimate_to_project_prompt_include_lines',
            'estimate_default_authorized_signature', 'estimate_default_customer_signature',
            'estimate_pdf_stamp_image', 'estimate_pdf_footer_image',
        ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['smtp_password'].required = False
        self.fields['smtp_password'].widget = forms.PasswordInput(
            render_value=False,
            attrs={'class': 'form-control', 'placeholder': 'Leave blank to keep unchanged'},
        )
        self.fields['smtp_use_tls'].widget.attrs['class'] = 'form-check-input'
        for field_name, field in self.fields.items():
            if field_name == 'logo':
                field.widget.attrs['class'] = 'form-control'
            elif field_name in (
                'estimate_default_authorized_signature',
                'estimate_default_customer_signature',
                'estimate_pdf_stamp_image',
                'estimate_pdf_footer_image',
            ):
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs['accept'] = 'image/*'
            elif field_name == 'address':
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs['rows'] = 3
            elif field_name in ('contract_default_terms',):
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs['rows'] = 5
            elif field_name == 'estimate_to_project_prompt_include_lines':
                field.widget.attrs['class'] = 'form-check-input'
            elif field_name == 'inventory_valuation_method':
                field.widget.attrs['class'] = 'form-select'
            elif field_name in ('smtp_password', 'smtp_use_tls'):
                continue
            elif field_name.startswith('smtp_'):
                field.widget.attrs['class'] = 'form-control'
            else:
                field.widget.attrs['class'] = 'form-control'

    def clean_smtp_password(self):
        val = self.cleaned_data.get('smtp_password')
        if val:
            return val
        if self.instance.pk:
            return self.instance.smtp_password
        return ''


