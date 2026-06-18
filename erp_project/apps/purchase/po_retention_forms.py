"""Forms for purchase-order project retention."""
from __future__ import annotations

from django import forms

from apps.projects.models import Project
from apps.purchase.models import PurchaseOrder
from apps.purchase.po_retention import normalize_po_retention_percent


class PurchaseOrderRetentionForm(forms.Form):
    project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        empty_label='— No project —',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    retention_percent = forms.ChoiceField(
        choices=[('', 'None'), ('5', '5%'), ('10', '10%')],
        required=False,
        label='Retention amount',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )

    def __init__(self, *args, purchase_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.purchase_order = purchase_order
        self.fields['project'].queryset = Project.objects.filter(is_active=True).exclude(
            status='cancelled'
        ).order_by('name', 'project_code')
        if purchase_order:
            if purchase_order.project_id:
                self.fields['project'].initial = purchase_order.project_id
            pct = normalize_po_retention_percent(purchase_order.retention_percent)
            if pct is not None:
                self.fields['retention_percent'].initial = str(int(pct))

    def save(self, purchase_order: PurchaseOrder) -> PurchaseOrder:
        purchase_order.project = self.cleaned_data.get('project')
        purchase_order.retention_percent = normalize_po_retention_percent(
            self.cleaned_data.get('retention_percent')
        )
        purchase_order.save(update_fields=['project', 'retention_percent', 'updated_at'])
        return purchase_order
