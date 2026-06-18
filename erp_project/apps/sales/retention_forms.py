"""Forms for project retention on estimates and invoices."""
from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.projects.models import Project
from apps.sales.models import Estimate
from apps.sales.project_retention import normalize_retention_percent


class EstimateProjectRetentionForm(forms.Form):
    """Save project + retention % on an estimate."""

    project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        empty_label='— No project —',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    retention_percent = forms.ChoiceField(
        choices=[
            ('', 'None'),
            ('5', '5%'),
            ('10', '10%'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
        label='Retention amount',
    )

    def __init__(self, *args, estimate=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.estimate = estimate
        if estimate and estimate.customer_id:
            self.fields['project'].queryset = (
                Project.objects.filter(customer_id=estimate.customer_id, is_active=True)
                .order_by('name', 'project_code')
            )
        else:
            self.fields['project'].queryset = Project.objects.filter(is_active=True).order_by('name')
        if estimate:
            if estimate.project_id:
                self.fields['project'].initial = estimate.project_id
            pct = normalize_retention_percent(estimate.retention_percent)
            if pct is not None:
                self.fields['retention_percent'].initial = str(int(pct))

    def save(self, estimate: Estimate) -> Estimate:
        project = self.cleaned_data.get('project')
        pct = normalize_retention_percent(self.cleaned_data.get('retention_percent'))
        estimate.project = project
        estimate.retention_percent = pct
        estimate.save(update_fields=['project', 'retention_percent', 'updated_at'])
        return estimate
