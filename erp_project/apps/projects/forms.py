from django import forms
from django.core.exceptions import ValidationError
from .models import Project, Task, ProjectExpense, ProjectGatepass
from apps.crm.models import Customer
from apps.purchase.models import Vendor
from apps.finance.models import Account
from django.contrib.auth import get_user_model

User = get_user_model()


def project_staff_select_queryset():
    """
    Every user account for Members / Technicians.

    Project membership is stored against Django users; HR may list more people than
    have (or have active) logins — we still expose **all** ``User`` rows so nothing
    is hidden by ``is_active`` or HR link state. Active accounts sort first.
    """
    return User.objects.all().order_by('-is_active', 'first_name', 'last_name', 'username')


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            'name', 'description', 'customer', 'manager', 'status',
            'start_date', 'end_date', 'budget', 'estimated_cost', 'members', 'technicians',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 2}),
            'members': forms.SelectMultiple(
                attrs={'class': 'form-select select2-members', 'data-placeholder': 'Search users…'}
            ),
            'technicians': forms.SelectMultiple(
                attrs={'class': 'form-select select2-technicians', 'data-placeholder': 'Search technicians…'}
            ),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        manager_qs = User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
        self.fields['manager'].queryset = manager_qs

        staff_qs = project_staff_select_queryset()
        self.fields['members'].queryset = staff_qs
        self.fields['members'].required = False
        self.fields['members'].label = 'Members'
        self.fields['technicians'].queryset = staff_qs
        self.fields['technicians'].required = False
        self.fields['technicians'].label = 'Technicians'
        for name, field in self.fields.items():
            if name in ['customer', 'manager', 'status']:
                field.widget.attrs['class'] = 'form-select'
            elif name in ('members', 'technicians'):
                pass  # class set on widget
            else:
                field.widget.attrs['class'] = 'form-control'
        self.fields['budget'].widget.attrs.setdefault('step', '0.01')
        self.fields['estimated_cost'].widget.attrs.setdefault('step', '0.01')

class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            'name', 'description', 'assigned_to', 'status', 'priority',
            'start_date', 'due_date', 'estimated_hours',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter assigned_to to active users only
        self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
        self.fields['assigned_to'].empty_label = '-- Unassigned --'
        self.fields['due_date'].label = 'End date'
        for name, field in self.fields.items():
            if name in ['assigned_to', 'status', 'priority']:
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class ProjectGatepassForm(forms.ModelForm):
    class Meta:
        model = ProjectGatepass
        fields = ['member', 'start_date', 'expiry_date', 'reference_number', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields['member'].queryset = project.members.all().order_by(
                'first_name', 'last_name', 'username'
            )
        self.fields['member'].label = 'Team member'
        self.fields['expiry_date'].label = 'Expiry date'
        for name, field in self.fields.items():
            if name == 'member':
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned = super().clean()
        if self.project and cleaned.get('member'):
            if not self.project.members.filter(pk=cleaned['member'].pk).exists():
                raise ValidationError('Selected member must belong to this project.')
        start = cleaned.get('start_date')
        end = cleaned.get('expiry_date')
        if start and end and start > end:
            raise ValidationError('Start date must be on or before expiry date.')
        return cleaned


class ProjectExpenseForm(forms.ModelForm):
    """Form for creating/editing project expenses."""
    class Meta:
        model = ProjectExpense
        fields = [
            'project', 'category', 'description', 'expense_date',
            'amount', 'vat_amount', 'vendor', 'invoice_reference',
            'expense_account'
        ]
        widgets = {
            'expense_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter active projects
        self.fields['project'].queryset = Project.objects.filter(is_active=True, status__in=['planned', 'in_progress'])
        
        # Filter active vendors
        self.fields['vendor'].queryset = Vendor.objects.filter(is_active=True)
        self.fields['vendor'].required = False
        
        # Filter expense accounts
        self.fields['expense_account'].queryset = Account.objects.filter(
            is_active=True,
            account_type__in=['expense', 'cogs']
        )
        self.fields['expense_account'].required = False
        self.fields['expense_account'].empty_label = '-- Use Default --'
        
        for name, field in self.fields.items():
            if name in ['project', 'category', 'vendor', 'expense_account']:
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'
        
        self.fields['amount'].widget.attrs['step'] = '0.01'
        self.fields['vat_amount'].widget.attrs['step'] = '0.01'

