"""
CRM Forms
"""
from django import forms
from .models import Customer


class CustomerForm(forms.ModelForm):
    """Form for creating/editing customers."""

    scope = forms.MultipleChoiceField(
        choices=Customer.SCOPE_CHOICES,
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                'class': 'form-select select2-crm-scope',
                'data-placeholder': 'Select scope…',
            }
        ),
    )

    class Meta:
        model = Customer
        fields = [
            'name', 'email', 'phone', 'company', 'address',
            'trn', 'website', 'scope', 'job_type', 'primary_project',
            'status', 'customer_type', 'notes',
        ]

    def __init__(self, *args, projects_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.projects.models import Project

        qs = (
            projects_queryset
            if projects_queryset is not None
            else Project.objects.filter(is_active=True).order_by('name')
        )
        self.fields['primary_project'].queryset = qs
        self.fields['primary_project'].required = False
        self.fields['primary_project'].widget.attrs['class'] = 'form-select'
        self.fields['primary_project'].label = 'Project'
        self.fields['scope'].label = 'Scope'

        if self.instance.pk:
            self.initial['scope'] = list(self.instance.scope or [])

        for field_name, field in self.fields.items():
            if field_name in ('scope', 'primary_project'):
                continue
            if field_name in ['address', 'notes']:
                field.widget.attrs['class'] = 'form-control'
                field.widget.attrs['rows'] = 3
            elif field_name in ['status', 'customer_type']:
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'

            if field_name == 'name':
                field.widget.attrs['placeholder'] = 'Contact Name'
            elif field_name == 'email':
                field.widget.attrs['placeholder'] = 'email@example.com'
            elif field_name == 'phone':
                field.widget.attrs['placeholder'] = '+971 XX XXX XXXX'
            elif field_name == 'company':
                field.widget.attrs['placeholder'] = 'Company Name'
            elif field_name == 'address':
                field.widget.attrs['placeholder'] = 'Full Address'
            elif field_name == 'trn':
                field.widget.attrs['placeholder'] = 'VAT / TRN number'
            elif field_name == 'website':
                field.widget.attrs['placeholder'] = 'https://example.com'
            elif field_name == 'job_type':
                field.widget.attrs['placeholder'] = 'Job type'
