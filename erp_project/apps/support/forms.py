from django import forms
from django.utils import timezone

from apps.crm.models import Customer
from apps.hr.models import Employee
from apps.projects.models import Project

from .models import SupportTicket
from .utils import get_amc_contract_queryset, get_default_support_kanban_stage


class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = [
            'subject',
            'link_type',
            'customer',
            'project',
            'amc_contract',
            'opened_date',
            'priority',
            'assigned_to',
            'description',
            'kanban_stage',
        ]
        widgets = {
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief summary of the issue'}),
            'link_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'project': forms.Select(attrs={'class': 'form-select'}),
            'amc_contract': forms.Select(attrs={'class': 'form-select'}),
            'opened_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'kanban_stage': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(is_active=True).order_by('name')
        self.fields['customer'].required = False
        self.fields['project'].queryset = Project.objects.filter(is_active=True).select_related(
            'customer'
        ).order_by('-created_at')
        self.fields['project'].required = False
        self.fields['amc_contract'].queryset = get_amc_contract_queryset()
        self.fields['amc_contract'].required = False
        self.fields['assigned_to'].queryset = Employee.objects.filter(
            is_active=True,
            status='active',
        ).order_by('first_name', 'last_name')
        self.fields['assigned_to'].required = False
        self.fields['assigned_to'].label_from_instance = lambda e: e.full_name
        self.fields['kanban_stage'].required = False

        if not self.initial.get('opened_date') and not self.data:
            self.initial['opened_date'] = timezone.localdate()

        if not (self.instance and self.instance.pk and self.instance.link_type == 'unlinked'):
            self.fields['link_type'].choices = [
                c for c in SupportTicket.LINK_TYPE_CHOICES if c[0] != 'unlinked'
            ]

        for name in ('customer', 'project', 'amc_contract'):
            self.fields[name].empty_label = '— Select —'

        self.fields['assigned_to'].empty_label = '— Unassigned —'
        self.fields['kanban_stage'].empty_label = '— Unassigned —'

    def clean(self):
        cleaned = super().clean()
        link_type = cleaned.get('link_type')
        if link_type == 'customer' and not cleaned.get('customer'):
            self.add_error('customer', 'Select a customer.')
        elif link_type == 'project' and not cleaned.get('project'):
            self.add_error('project', 'Select a project.')
        elif link_type == 'amc' and not cleaned.get('amc_contract'):
            self.add_error('amc_contract', 'Select an AMC contract.')
        elif link_type == 'unlinked' and not (
            (self.instance and self.instance.submitted_via_public)
            or (self.instance and (self.instance.requester_name or '').strip())
        ):
            self.add_error('link_type', 'General tickets are only for public submissions.')
        return cleaned


class PublicSupportTicketForm(forms.Form):
    """Anonymous public support ticket submission."""

    requester_name = forms.CharField(
        max_length=255,
        label='Your name or company',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Type your name or company…',
            'autocomplete': 'off',
            'id': 'id_requester_name',
        }),
    )
    requester_email = forms.EmailField(
        required=False,
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'email@example.com',
        }),
    )
    requester_phone = forms.CharField(
        required=False,
        max_length=40,
        label='Phone',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+971 …',
        }),
    )
    subject = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Brief summary of the issue',
        }),
    )
    priority = forms.ChoiceField(
        choices=SupportTicket.PRIORITY_CHOICES,
        initial='medium',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 5,
            'placeholder': 'Describe the issue in detail…',
        }),
    )
    link_type = forms.CharField(required=False, widget=forms.HiddenInput())
    link_id = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean(self):
        cleaned = super().clean()
        link_type = (cleaned.get('link_type') or '').strip()
        link_id = (cleaned.get('link_id') or '').strip()
        if link_type and link_id:
            if link_type not in ('customer', 'project', 'amc'):
                self.add_error('requester_name', 'Invalid link selection.')
            else:
                try:
                    link_id = int(link_id)
                except (TypeError, ValueError):
                    self.add_error('requester_name', 'Invalid link selection.')
                else:
                    cleaned['link_id'] = link_id
                    if link_type == 'customer' and not Customer.objects.filter(
                        pk=link_id, is_active=True
                    ).exists():
                        self.add_error('requester_name', 'Selected customer is no longer available.')
                    elif link_type == 'project' and not Project.objects.filter(
                        pk=link_id, is_active=True
                    ).exists():
                        self.add_error('requester_name', 'Selected project is no longer available.')
                    elif link_type == 'amc' and not get_amc_contract_queryset().filter(pk=link_id).exists():
                        self.add_error('requester_name', 'Selected AMC contract is no longer available.')
        else:
            cleaned['link_type'] = 'unlinked'
            cleaned['link_id'] = None
        return cleaned

    def create_ticket(self):
        from .models import SupportTicket

        data = self.cleaned_data
        link_type = data['link_type']
        link_id = data.get('link_id')
        ticket = SupportTicket(
            subject=data['subject'],
            link_type=link_type,
            opened_date=timezone.localdate(),
            priority=data['priority'],
            description=data['description'],
            submitted_via_public=True,
            requester_name=data['requester_name'].strip(),
            requester_email=(data.get('requester_email') or '').strip(),
            requester_phone=(data.get('requester_phone') or '').strip(),
            kanban_stage=get_default_support_kanban_stage(),
        )
        if link_type == 'customer' and link_id:
            ticket.customer_id = link_id
        elif link_type == 'project' and link_id:
            ticket.project_id = link_id
        elif link_type == 'amc' and link_id:
            ticket.amc_contract_id = link_id
        ticket.full_clean()
        ticket.save()
        return ticket
