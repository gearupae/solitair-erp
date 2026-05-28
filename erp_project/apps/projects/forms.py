from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import Project, Task, ProjectExpense, ProjectGatepass, ProjectItemLine
from apps.crm.models import Customer
from apps.inventory.models import Item
from apps.purchase.models import Vendor
from apps.finance.models import Account
from django.contrib.auth import get_user_model

User = get_user_model()


def project_staff_choice_label(user):
    """Display name + HR employee code in Members / Technicians dropdowns."""
    name = (user.get_full_name() or '').strip()
    emp = getattr(user, 'employee_profile', None)
    if emp:
        if not name:
            name = emp.full_name
        code = (emp.employee_code or '').strip()
        if name and code:
            return f'{name} — {code}'
        if code:
            return code
    if name:
        return name
    return user.username


def project_staff_select_queryset():
    """
    Every user account for Members / Technicians.

    Project membership is stored against Django users; HR may list more people than
    have (or have active) logins — we still expose **all** ``User`` rows so nothing
    is hidden by ``is_active`` or HR link state. Active accounts sort first.
    """
    return (
        User.objects.select_related('employee_profile')
        .all()
        .order_by('-is_active', 'first_name', 'last_name', 'username')
    )


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
                attrs={'class': 'form-select select2-members', 'data-placeholder': 'Search by name or employee code…'}
            ),
            'technicians': forms.SelectMultiple(
                attrs={'class': 'form-select select2-technicians', 'data-placeholder': 'Search by name or employee code…'}
            ),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        staff_qs = project_staff_select_queryset()
        manager_qs = User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
        self.fields['manager'].queryset = manager_qs
        self.fields['members'].queryset = staff_qs
        self.fields['members'].required = False
        self.fields['members'].label = 'Members'
        self.fields['members'].label_from_instance = project_staff_choice_label
        self.fields['technicians'].queryset = staff_qs
        self.fields['technicians'].required = False
        self.fields['technicians'].label = 'Technicians'
        self.fields['technicians'].label_from_instance = project_staff_choice_label
        for name, field in self.fields.items():
            if name in ['customer', 'manager', 'status']:
                field.widget.attrs['class'] = 'form-select'
            elif name in ('members', 'technicians'):
                pass  # class set on widget
            else:
                field.widget.attrs['class'] = 'form-control'
        self.fields['budget'].widget.attrs.setdefault('step', '0.01')
        self.fields['estimated_cost'].widget.attrs.setdefault('step', '0.01')

class CustomerTaskCreateForm(forms.Form):
    """Quick task create from CRM customer detail (one task per selected member)."""

    name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Task name'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Task description'}),
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    due_date = forms.DateField(
        required=False,
        label='End date',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        widget=forms.SelectMultiple(
            attrs={
                'class': 'form-select select2-task-members',
                'data-placeholder': 'Search by name or employee code…',
            }
        ),
        label='Members',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        staff_qs = project_staff_select_queryset()
        self.fields['members'].queryset = staff_qs
        self.fields['members'].label_from_instance = project_staff_choice_label

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('due_date')
        if start and end and start > end:
            raise ValidationError('Start date must be on or before end date.')
        return cleaned


class ProjectTaskCreateForm(CustomerTaskCreateForm):
    """Quick task create from project detail (one task per selected member)."""

    status = forms.ChoiceField(
        choices=Task.STATUS_CHOICES,
        initial='pending',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    priority = forms.ChoiceField(
        choices=Task.PRIORITY_CHOICES,
        initial='medium',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    estimated_hours = forms.DecimalField(
        required=False,
        initial=Decimal('0.00'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )


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
    
    def __init__(self, *args, project=None, customer=None, **kwargs):
        self.project = project
        self.customer = customer
        super().__init__(*args, **kwargs)
        # Filter assigned_to to active users only
        self.fields['assigned_to'].queryset = (
            User.objects.filter(is_active=True)
            .select_related('employee_profile')
            .order_by('first_name', 'last_name', 'username')
        )
        self.fields['assigned_to'].empty_label = '-- Unassigned --'
        self.fields['assigned_to'].label_from_instance = project_staff_choice_label
        self.fields['due_date'].label = 'End date'
        for name, field in self.fields.items():
            if name in ['assigned_to', 'status', 'priority']:
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'

    def _post_clean(self):
        if self.project is not None:
            self.instance.project = self.project
        if self.customer is not None:
            self.instance.customer = self.customer
        super()._post_clean()


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
        
        # Active projects that can still incur expenses (exclude cancelled only)
        self.fields['project'].queryset = (
            Project.objects.filter(is_active=True)
            .exclude(status='cancelled')
            .order_by('-created_at', '-pk')
        )
        self.fields['project'].widget.attrs['class'] = 'form-select select2-project'
        self.fields['project'].widget.attrs['data-placeholder'] = 'Search by code or name…'
        
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
            if name in ['category', 'vendor', 'expense_account']:
                field.widget.attrs['class'] = 'form-select'
            elif name == 'project':
                pass  # class set above
            else:
                field.widget.attrs['class'] = 'form-control'
        
        self.fields['amount'].widget.attrs['step'] = '0.01'
        self.fields['vat_amount'].widget.attrs['step'] = '0.01'


class ProjectItemDeliveryForm(forms.Form):
    """Deliver inventory items to a project (FIFO for serial-tracked items)."""

    item = forms.ModelChoiceField(
        queryset=Item.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='Select item…',
    )
    quantity = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=Decimal('1'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'min': '1'}),
    )
    delivered_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        qs = Item.objects.filter(is_active=True, item_type='product').order_by('name')
        if project:
            from .item_delivery import project_has_scoped_inventory_lines, project_item_remaining_qty

            if project_has_scoped_inventory_lines(project):
                item_ids = (
                    ProjectItemLine.objects.filter(
                        project=project,
                        inventory_item__isnull=False,
                    )
                    .values_list('inventory_item_id', flat=True)
                    .distinct()
                )
                deliverable_ids = [
                    pk for pk in item_ids
                    if (project_item_remaining_qty(project, Item.objects.get(pk=pk)) or Decimal('0')) > 0
                ]
                qs = qs.filter(pk__in=deliverable_ids) if deliverable_ids else Item.objects.none()
        self.fields['item'].queryset = qs

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get('item')
        qty = cleaned.get('quantity')
        if self.project and item and qty is not None:
            from .item_delivery import project_item_remaining_qty, project_item_required_qty, project_item_delivered_qty

            remaining = project_item_remaining_qty(self.project, item)
            if remaining is not None and qty > remaining:
                required = project_item_required_qty(self.project, item)
                delivered = project_item_delivered_qty(self.project, item)
                if remaining <= 0:
                    raise forms.ValidationError(
                        f'All {required} unit(s) of {item.name} are already delivered to this project.'
                    )
                self.add_error(
                    'quantity',
                    f'Project requires {required} × {item.name}; {delivered} delivered. Max {remaining} more.',
                )
        return cleaned


class ProjectItemReturnForm(forms.Form):
    """Return delivered inventory from a project back to stock."""

    item = forms.ModelChoiceField(
        queryset=Item.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='Select item…',
    )
    quantity = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=Decimal('1'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'min': '1'}),
    )
    returned_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project:
            from .item_delivery import project_returnable_item_ids
            ids = project_returnable_item_ids(project)
            self.fields['item'].queryset = Item.objects.filter(pk__in=ids).order_by('name')
        else:
            self.fields['item'].queryset = Item.objects.none()

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get('item')
        qty = cleaned.get('quantity')
        if self.project and item and qty is not None:
            from .item_delivery import project_item_returnable_qty

            returnable = project_item_returnable_qty(self.project, item)
            if qty > returnable:
                self.add_error(
                    'quantity',
                    f'Only {returnable} unit(s) of {item.name} can be returned from this project.',
                )
            if item.track_by_serial and qty != qty.to_integral_value():
                self.add_error('quantity', 'Serial-tracked items require a whole-number quantity.')
        return cleaned

