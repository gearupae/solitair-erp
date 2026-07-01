from django import forms

from apps.hr.forms import DepartmentForm
from apps.hr.models import Department

from .models import Candidate, Position, RecruitmentRequest


def _style_fields(form):
    for field in form.fields.values():
        if isinstance(field.widget, forms.Select):
            field.widget.attrs.setdefault('class', 'form-select')
        elif isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs.setdefault('class', 'form-check-input')
        else:
            field.widget.attrs.setdefault('class', 'form-control')


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ['title', 'department']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('name')
        self.fields['department'].empty_label = '-- Select Department --'
        _style_fields(self)


class RecruitmentRequestForm(forms.ModelForm):
    class Meta:
        model = RecruitmentRequest
        fields = ['position', 'openings']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['position'].queryset = Position.objects.filter(is_active=True).select_related('department')
        _style_fields(self)


class RecruitmentRequestEditForm(forms.ModelForm):
    """Edit form — close open requests; pending/rejected can update details."""

    class Meta:
        model = RecruitmentRequest
        fields = ['position', 'openings', 'status']
        widgets = {
            'status': forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['position'].queryset = Position.objects.filter(is_active=True).select_related('department')
        _style_fields(self)
        status = self.instance.status if self.instance and self.instance.pk else RecruitmentRequest.STATUS_PENDING
        if status == RecruitmentRequest.STATUS_OPEN:
            self.fields['position'].disabled = True
            self.fields['openings'].disabled = True
            self.fields['status'].choices = [
                (RecruitmentRequest.STATUS_OPEN, 'Open'),
                (RecruitmentRequest.STATUS_CLOSED, 'Closed'),
            ]
        elif status == RecruitmentRequest.STATUS_PENDING:
            self.fields.pop('status', None)
        elif status == RecruitmentRequest.STATUS_REJECTED:
            self.fields.pop('status', None)
        else:
            for field in self.fields.values():
                field.disabled = True


class CandidateForm(forms.ModelForm):
    class Meta:
        model = Candidate
        fields = [
            'name',
            'phone',
            'email',
            'position_applied',
            'resume',
            'source',
            'status',
            'applied_date',
        ]
        widgets = {
            'applied_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'status': forms.Select(),
            'source': forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        locked = kwargs.pop('locked', False)
        super().__init__(*args, **kwargs)
        self.fields['position_applied'].queryset = Position.objects.filter(is_active=True).select_related('department')
        _style_fields(self)
        if locked:
            for field in self.fields.values():
                field.disabled = True
            if self.instance and self.instance.resume:
                self.fields['resume'].disabled = True
