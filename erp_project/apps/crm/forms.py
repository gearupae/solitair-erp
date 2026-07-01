"""
CRM Forms
"""
from django import forms
from django.core.exceptions import ValidationError

from .models import Customer, CrmLeadKanbanStage, SiteVisitLog
from .utils import (
    get_crm_project_queryset,
    get_sales_employee_for_user,
    get_sales_employee_queryset,
    normalize_customer_website,
    project_choice_label,
    salesperson_display_name,
)


class JobTypeChoiceField(forms.MultipleChoiceField):
    """Stores job types as a list; accepts single-select or multi-select widgets."""

    def to_python(self, value):
        if not value:
            return []
        if isinstance(value, str):
            value = [value]
        return [v for v in value if v]


class CustomerForm(forms.ModelForm):
    """Form for creating/editing customers."""

    job_type = JobTypeChoiceField(
        choices=Customer.JOB_TYPE_CHOICES,
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                'class': 'form-select select2-crm-job-type',
                'data-placeholder': 'Select job type(s)…',
            }
        ),
        label='Job type',
    )

    class Meta:
        model = Customer
        fields = [
            'name', 'email', 'phone', 'company', 'address',
            'trn', 'website', 'scope', 'job_type', 'primary_project',
            'assigned_salesperson', 'source_of_lead',
            'status', 'customer_type', 'lead_kanban_stage', 'business_segment',
            'trn_document', 'trade_license_document',
            'notes',
        ]

    def __init__(self, *args, projects_queryset=None, user=None, for_lead=None, **kwargs):
        super().__init__(*args, **kwargs)

        is_lead = for_lead if for_lead is not None else (
            self.instance.pk and self.instance.customer_type == 'lead'
        )
        if not self.instance.pk and for_lead is None:
            ctype = (self.initial.get('customer_type') or '').strip()
            if not ctype and self.data:
                ctype = (self.data.get('customer_type') or '').strip()
            is_lead = ctype == 'lead'

        if is_lead:
            self.fields.pop('status', None)
            stage_qs = CrmLeadKanbanStage.objects.filter(
                is_active=True,
                converts_to_customer=False,
            ).order_by('sort_order', 'id')
            self.fields['lead_kanban_stage'].queryset = stage_qs
            self.fields['lead_kanban_stage'].required = False
            self.fields['lead_kanban_stage'].empty_label = '— Unassigned —'
            self.fields['lead_kanban_stage'].label = 'Pipeline stage'
            self.fields['lead_kanban_stage'].widget.attrs['class'] = 'form-select'
            self.fields['source_of_lead'].required = False
            self.fields['source_of_lead'].label = 'Source of lead'
            self.fields['source_of_lead'].widget.attrs['class'] = 'form-select'
        else:
            self.fields.pop('lead_kanban_stage', None)
            self.fields.pop('source_of_lead', None)

        qs = projects_queryset if projects_queryset is not None else get_crm_project_queryset()
        if self.instance.pk:
            self.fields.pop('primary_project', None)
        else:
            self.fields['primary_project'].queryset = qs
            self.fields['primary_project'].required = False
            self.fields['primary_project'].empty_label = '— Select project —'
            self.fields['primary_project'].label_from_instance = project_choice_label
            self.fields['primary_project'].widget.attrs['class'] = 'form-select'
            self.fields['primary_project'].label = 'Project'
        self.fields['scope'].label = 'Scope'
        self.fields['scope'].required = False
        self.fields['scope'].widget.attrs['class'] = 'form-select'
        self.fields['business_segment'].required = True
        self.fields['business_segment'].widget.attrs['class'] = 'form-select'
        self.fields['business_segment'].label = 'Business type'
        self.fields['trn_document'].required = False
        self.fields['trade_license_document'].required = False
        if not self.instance.pk:
            self.fields['phone'].required = True

        include_salesperson_id = None
        if self.instance.pk and self.instance.assigned_salesperson_id:
            include_salesperson_id = self.instance.assigned_salesperson_id
        self.fields['assigned_salesperson'].queryset = get_sales_employee_queryset(
            include_employee_id=include_salesperson_id,
        )
        self.fields['assigned_salesperson'].required = True
        self.fields['assigned_salesperson'].empty_label = '— Select salesman —'
        self.fields['assigned_salesperson'].label_from_instance = salesperson_display_name
        self.fields['assigned_salesperson'].widget.attrs['class'] = 'form-select select2'
        self.fields['assigned_salesperson'].label = 'Assigned salesman'
        self.fields['name'].required = False
        self.fields['company'].required = True

        if user and not self.instance.pk:
            emp = get_sales_employee_for_user(user)
            if emp and 'assigned_salesperson' not in self.initial:
                self.initial['assigned_salesperson'] = emp.pk

        if self.instance.pk:
            self.initial['job_type'] = list(self.instance.job_type or [])

        for field_name, field in self.fields.items():
            if field_name in ('job_type', 'primary_project', 'business_segment', 'assigned_salesperson', 'scope', 'source_of_lead'):
                continue
            if field_name in ('trn_document', 'trade_license_document'):
                field.widget = forms.FileInput(
                    attrs={
                        'class': 'form-control form-control-sm',
                        'accept': '.pdf,.jpg,.jpeg,.png,.webp,.heic',
                    }
                )
                field.widget.attrs['data-crm-doc-field'] = field_name
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
                field.widget = forms.TextInput(attrs=field.widget.attrs)
                field.widget.attrs['placeholder'] = 'gear-up.ae, www.gear-up.ae, or https://gear-up.ae'

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.job_type = self.cleaned_data.get('job_type') or []
        if instance.customer_type == 'lead' and 'status' not in self.fields:
            if not instance.status:
                instance.status = 'active'
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def clean_website(self):
        raw = self.cleaned_data.get('website') or ''
        try:
            return normalize_customer_website(raw)
        except ValidationError:
            raise forms.ValidationError(
                'Enter a valid website (e.g. gear-up.ae, www.gear-up.ae, or https://gear-up.ae).'
            )

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.instance.customer_type == 'customer':
            cleaned['customer_type'] = 'customer'
        ctype = cleaned.get('customer_type')
        seg = (cleaned.get('business_segment') or '').strip()

        if seg not in ('b2b', 'b2c'):
            self.add_error(
                'business_segment',
                'Select B2B or B2C.',
            )

        if not cleaned.get('assigned_salesperson'):
            self.add_error(
                'assigned_salesperson',
                'Select a salesman to assign this account.',
            )

        phone = (cleaned.get('phone') or '').strip()
        if not self.instance.pk and not phone:
            self.add_error('phone', 'Phone number is required.')
        else:
            cleaned['phone'] = phone

        company = (cleaned.get('company') or '').strip()
        if not company:
            self.add_error('company', 'Company name is required.')
        else:
            cleaned['company'] = company

        cleaned['name'] = (cleaned.get('name') or '').strip()

        if seg == 'b2c':
            cleaned['trn'] = ''
        elif seg == 'b2b' and ctype == 'customer':
            if self.data.get('trade_license_document-clear') in ('on', 'true', '1'):
                cleaned['trade_license_document'] = False
            lic_f = cleaned.get('trade_license_document')
            has_lic = bool(lic_f) or (
                self.instance.pk
                and bool(self.instance.trade_license_document)
                and self.data.get('trade_license_document-clear') not in ('on', 'true', '1')
            )
            if not has_lic:
                self.add_error(
                    'trade_license_document',
                    'Trade license upload is required for B2B customers.',
                )
            if self.data.get('trn_document-clear') in ('on', 'true', '1'):
                cleaned['trn_document'] = False

        return cleaned


class SiteVisitLogForm(forms.ModelForm):
    """Quick log visit form on lead detail."""

    class Meta:
        model = SiteVisitLog
        fields = ['visit_date', 'location', 'outcome', 'notes']
        widgets = {
            'visit_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Visit location'}),
            'outcome': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Visit notes…'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['visit_date'].label = 'Date'
        self.fields['outcome'].label = 'Outcome'
