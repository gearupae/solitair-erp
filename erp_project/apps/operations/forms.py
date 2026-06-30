from django import forms
from django.utils import timezone

from apps.hr.models import Employee
from apps.projects.models import Project

from .models import StaffDutySchedule
from .utils import (
    employee_choice_label,
    find_employee_schedule_conflicts,
    format_conflict_message,
    get_amc_contract_queryset,
    get_hr_employee_queryset,
)


class StaffDutyScheduleForm(forms.ModelForm):
    """Edit a single duty assignment."""

    class Meta:
        model = StaffDutySchedule
        fields = [
            'employee',
            'duty_date',
            'start_time',
            'end_time',
            'link_type',
            'project',
            'amc_contract',
            'location',
            'contact_person_name',
            'contact_person_phone',
            'status',
            'notes',
        ]
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'duty_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'link_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'project': forms.Select(attrs={'class': 'form-select'}),
            'amc_contract': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Site or work location'}),
            'contact_person_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Name on site'}),
            'contact_person_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].queryset = get_hr_employee_queryset()
        self.fields['employee'].label_from_instance = employee_choice_label
        self.fields['project'].queryset = Project.objects.filter(is_active=True).select_related(
            'customer'
        ).order_by('-created_at')
        self.fields['project'].required = False
        self.fields['amc_contract'].queryset = get_amc_contract_queryset()
        self.fields['amc_contract'].required = False

    def clean(self):
        cleaned = super().clean()
        link_type = cleaned.get('link_type')
        if link_type == 'project' and not cleaned.get('project'):
            self.add_error('project', 'Select a project.')
        elif link_type == 'amc' and not cleaned.get('amc_contract'):
            self.add_error('amc_contract', 'Select an AMC contract.')

        employee = cleaned.get('employee')
        duty_date = cleaned.get('duty_date')
        status = cleaned.get('status') or 'scheduled'
        if employee and duty_date and status == 'scheduled':
            exclude_pk = self.instance.pk if self.instance and self.instance.pk else None
            conflicts = find_employee_schedule_conflicts([employee.pk], duty_date, exclude_pk=exclude_pk)
            if employee.pk in conflicts:
                self.add_error('employee', format_conflict_message(conflicts[employee.pk]))
        return cleaned


class StaffDutyBulkScheduleForm(forms.Form):
    """Create duty assignments for multiple staff at once."""

    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.SelectMultiple(
            attrs={
                'class': 'form-select select2-staff-multi',
                'data-placeholder': 'Select staff…',
            }
        ),
        help_text='',
    )
    duty_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
    )
    end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
    )
    link_type = forms.ChoiceField(
        choices=StaffDutySchedule.LINK_TYPE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='project',
    )
    project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    amc_contract = forms.ModelChoiceField(
        queryset=get_amc_contract_queryset(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='AMC contract',
    )
    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Site or work location'}),
    )
    contact_person_name = forms.CharField(
        required=False,
        label='Contact person',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Name on site'}),
    )
    contact_person_phone = forms.CharField(
        required=False,
        label='Contact phone',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employees'].queryset = get_hr_employee_queryset()
        self.fields['employees'].label_from_instance = employee_choice_label
        self.fields['project'].queryset = Project.objects.filter(is_active=True).select_related(
            'customer'
        ).order_by('-created_at')
        if not self.initial.get('duty_date') and not self.data.get('duty_date'):
            self.initial['duty_date'] = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        link_type = cleaned.get('link_type')
        if link_type == 'project' and not cleaned.get('project'):
            self.add_error('project', 'Select a project.')
        elif link_type == 'amc' and not cleaned.get('amc_contract'):
            self.add_error('amc_contract', 'Select an AMC contract.')

        start_time = cleaned.get('start_time')
        end_time = cleaned.get('end_time')
        if start_time and end_time and end_time <= start_time:
            self.add_error('end_time', 'End time must be after start time.')

        employees = cleaned.get('employees')
        duty_date = cleaned.get('duty_date')
        if employees and duty_date:
            conflicts = find_employee_schedule_conflicts(
                [emp.pk for emp in employees],
                duty_date,
            )
            if conflicts:
                messages = [format_conflict_message(conflicts[emp.pk]) for emp in employees if emp.pk in conflicts]
                self.add_error('employees', ' '.join(messages))
        return cleaned

    def create_schedules(self):
        employees = self.cleaned_data['employees']
        created = []
        for employee in employees:
            schedule = StaffDutySchedule(
                employee=employee,
                duty_date=self.cleaned_data['duty_date'],
                start_time=self.cleaned_data['start_time'],
                end_time=self.cleaned_data.get('end_time'),
                link_type=self.cleaned_data['link_type'],
                project=self.cleaned_data.get('project') if self.cleaned_data['link_type'] == 'project' else None,
                amc_contract=self.cleaned_data.get('amc_contract') if self.cleaned_data['link_type'] == 'amc' else None,
                location=self.cleaned_data.get('location') or '',
                contact_person_name=self.cleaned_data.get('contact_person_name') or '',
                contact_person_phone=self.cleaned_data.get('contact_person_phone') or '',
                notes=self.cleaned_data.get('notes') or '',
                status='scheduled',
            )
            schedule.full_clean()
            schedule.save()
            created.append(schedule)
        return created
