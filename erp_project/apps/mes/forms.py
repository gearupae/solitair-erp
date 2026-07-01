"""MES ModelForms — tenant-scoped via get_default_mes_company()."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .models import (
    BOMItem,
    Part,
    ProductTemplate,
    ProductionOrder,
    RoutingOperation,
    TemplateBOMItem,
    TemplateRoutingOp,
    WorkCenter,
)
from .services.po import allocate_po_number
from .services.routing import next_routing_sequence


class MesModelForm(forms.ModelForm):
    """Attach company on create; callers pass company= from the view."""

    def __init__(self, *args, company=None, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.company and (not instance.pk or not instance.company_id):
            instance.company = self.company
        if commit:
            instance.save()
        return instance


class WorkCenterForm(MesModelForm):
    class Meta:
        model = WorkCenter
        fields = [
            'code', 'name', 'sequence_order', 'center_type',
            'is_production_step', 'is_qc_gate',
            'cost_per_hour', 'capacity_units_per_hour',
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'sequence_order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'center_type': forms.Select(attrs={'class': 'form-select'}),
            'is_production_step': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_qc_gate': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'cost_per_hour': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'capacity_units_per_hour': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }


class ProductionOrderCreateForm(MesModelForm):
    product_template = forms.ModelChoiceField(
        queryset=ProductTemplate.objects.none(),
        required=False,
        empty_label='— Build from scratch —',
        label='Product template',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = ProductionOrder
        fields = ['reference', 'quantity', 'due_date', 'overhead_percent']
        widgets = {
            'reference': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'overhead_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['quantity'].initial = 1
        self.fields['overhead_percent'].initial = Decimal('10.00')
        self.fields['quantity'].required = False
        self.fields['overhead_percent'].required = False
        if self.company:
            self.fields['product_template'].queryset = ProductTemplate.objects.filter(
                company=self.company,
                is_active=True,
            ).order_by('name')

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty in (None, ''):
            return 1
        if qty < 1:
            raise ValidationError('Quantity must be at least 1.')
        return qty

    def clean_overhead_percent(self):
        overhead = self.cleaned_data.get('overhead_percent')
        if overhead in (None, ''):
            return Decimal('10.00')
        return overhead

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.company:
            instance.company = self.company
        if not instance.po_number and self.company:
            instance.po_number = allocate_po_number(self.company)
        instance.status = ProductionOrder.STATUS_DRAFT
        if commit:
            instance.save()
        return instance


class ProductionOrderUpdateForm(ProductionOrderCreateForm):
    """Same fields as create; only used while PO is draft."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('product_template', None)


class BOMItemForm(MesModelForm):
    class Meta:
        model = BOMItem
        fields = [
            'parent',
            'part_name',
            'material_type',
            'quantity',
            'unit',
            'item_code',
            'inventory_item',
            'unit_cost',
        ]
        widgets = {
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'part_name': forms.TextInput(attrs={'class': 'form-control'}),
            'material_type': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0.001'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'item_code': forms.TextInput(attrs={'class': 'form-control'}),
            'inventory_item': forms.Select(attrs={'class': 'form-select select2'}),
            'unit_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, production_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.production_order = production_order
        from apps.inventory.models import Item
        self.fields['inventory_item'].queryset = Item.objects.filter(is_active=True).order_by('name')
        self.fields['inventory_item'].required = False
        self.fields['inventory_item'].empty_label = '— Manual cost —'
        if production_order:
            qs = BOMItem.objects.filter(
                production_order=production_order,
                company=production_order.company,
                is_active=True,
            ).order_by('part_name')
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields['parent'].queryset = qs
            self.fields['parent'].required = False
            self.fields['parent'].empty_label = '— Top level —'
        else:
            self.fields['parent'].queryset = BOMItem.objects.none()

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is not None and qty <= 0:
            raise ValidationError('Quantity must be greater than zero.')
        return qty

    def clean_unit(self):
        unit = (self.cleaned_data.get('unit') or '').strip()
        if not unit:
            raise ValidationError('Unit is required.')
        return unit

    def clean(self):
        cleaned = super().clean()
        parent = cleaned.get('parent')
        if parent and self.instance.pk and parent.pk == self.instance.pk:
            raise ValidationError({'parent': 'A BOM line cannot be its own parent.'})
        if parent and self.instance.pk:
            seen = {self.instance.pk}
            node = parent
            while node is not None:
                if node.pk in seen:
                    raise ValidationError({'parent': 'Circular parent reference is not allowed.'})
                seen.add(node.pk)
                node = node.parent
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.production_order:
            instance.production_order = self.production_order
        if instance.inventory_item_id and not instance.unit_cost:
            instance.unit_cost = instance.inventory_item.purchase_price or Decimal('0')
        if commit:
            instance.full_clean()
            instance.save()
        return instance


class ProductTemplateForm(MesModelForm):
    class Meta:
        model = ProductTemplate
        fields = ['code', 'name', 'description']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class TemplateBOMItemForm(MesModelForm):
    class Meta:
        model = TemplateBOMItem
        fields = [
            'parent', 'part_name', 'material_type', 'quantity', 'unit', 'item_code', 'inventory_item',
        ]
        widgets = {
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'part_name': forms.TextInput(attrs={'class': 'form-control'}),
            'material_type': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0.001'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'item_code': forms.TextInput(attrs={'class': 'form-control'}),
            'inventory_item': forms.Select(attrs={'class': 'form-select select2'}),
        }

    def __init__(self, *args, template=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.template = template
        from apps.inventory.models import Item
        self.fields['inventory_item'].queryset = Item.objects.filter(is_active=True).order_by('name')
        self.fields['inventory_item'].required = False
        self.fields['inventory_item'].empty_label = '— None —'
        if template:
            qs = TemplateBOMItem.objects.filter(template=template, company=template.company, is_active=True)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields['parent'].queryset = qs
            self.fields['parent'].required = False
            self.fields['parent'].empty_label = '— Top level —'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.template:
            instance.template = self.template
        if commit:
            instance.save()
        return instance


class TemplateRoutingOpForm(MesModelForm):
    class Meta:
        model = TemplateRoutingOp
        fields = ['work_center', 'sequence', 'std_time_minutes']
        widgets = {
            'work_center': forms.Select(attrs={'class': 'form-select'}),
            'sequence': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'std_time_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }

    def __init__(self, *args, template=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.template = template
        if template:
            used = template.routing_ops.filter(is_active=True).values_list('work_center_id', flat=True)
            qs = WorkCenter.objects.filter(company=template.company, is_active=True)
            if not self.instance.pk:
                qs = qs.exclude(pk__in=used)
            self.fields['work_center'].queryset = qs.order_by('sequence_order', 'name')

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.template:
            instance.template = self.template
        if commit:
            instance.save()
        return instance


class ProductionOrderTeamForm(forms.Form):
    assigned_employees = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2', 'size': 8}),
        label='Assigned team members',
    )

    def __init__(self, *args, production_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.hr.models import Employee
        if production_order:
            self.fields['assigned_employees'].queryset = Employee.objects.filter(
                company=production_order.company,
                status='active',
                is_active=True,
            ).order_by('first_name', 'last_name')
            self.fields['assigned_employees'].initial = production_order.assigned_employees.all()


class RoutingOperationTeamForm(forms.Form):
    assigned_employees = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2', 'size': 6}),
        label='Assigned team members',
    )

    def __init__(self, *args, routing_operation=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.hr.models import Employee
        if routing_operation:
            po = routing_operation.production_order
            self.fields['assigned_employees'].queryset = Employee.objects.filter(
                company=po.company,
                status='active',
                is_active=True,
            ).order_by('first_name', 'last_name')
            self.fields['assigned_employees'].initial = routing_operation.assigned_employees.all()


class RoutingOperationForm(MesModelForm):
    class Meta:
        model = RoutingOperation
        fields = ['work_center', 'sequence', 'std_time_minutes', 'rate_per_hour']
        widgets = {
            'work_center': forms.Select(attrs={'class': 'form-select', 'id': 'id_work_center'}),
            'sequence': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'std_time_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'rate_per_hour': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'id': 'id_rate_per_hour'},
            ),
        }

    def __init__(self, *args, production_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.production_order = production_order
        if production_order:
            used_wc_ids = production_order.routing_operations.filter(
                is_active=True,
            ).values_list('work_center_id', flat=True)
            if self.instance.pk:
                qs = WorkCenter.objects.filter(
                    company=production_order.company,
                    is_active=True,
                )
            else:
                qs = WorkCenter.objects.filter(
                    company=production_order.company,
                    is_active=True,
                ).exclude(pk__in=used_wc_ids)
            self.fields['work_center'].queryset = qs.order_by('sequence_order', 'name')
            if not self.instance.pk:
                self.fields['sequence'].initial = next_routing_sequence(production_order)
                self.fields['sequence'].widget = forms.HiddenInput()
        self.fields['std_time_minutes'].initial = 15

    def clean_std_time_minutes(self):
        minutes = self.cleaned_data.get('std_time_minutes')
        if minutes is not None and minutes < 1:
            raise ValidationError('Standard time must be at least 1 minute.')
        return minutes

    def clean_rate_per_hour(self):
        rate = self.cleaned_data.get('rate_per_hour')
        if rate is not None and rate < 0:
            raise ValidationError('Rate cannot be negative.')
        return rate

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.production_order:
            instance.production_order = self.production_order
        if instance.work_center_id and (
            not instance.rate_per_hour or instance.rate_per_hour == Decimal('0.00')
        ):
            instance.rate_per_hour = instance.work_center.cost_per_hour
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class RoutingOperationUpdateForm(RoutingOperationForm):
    """Edit existing step — work center is fixed (unique per PO)."""

    class Meta(RoutingOperationForm.Meta):
        fields = ['sequence', 'std_time_minutes', 'rate_per_hour', 'assigned_employees']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('work_center', None)
        self.fields['sequence'].widget = forms.NumberInput(attrs={'class': 'form-control', 'min': 0})
        from apps.hr.models import Employee
        if self.production_order:
            self.fields['assigned_employees'].queryset = Employee.objects.filter(
                company=self.production_order.company,
                status='active',
                is_active=True,
            ).order_by('first_name', 'last_name')
        self.fields['assigned_employees'].required = False
        self.fields['assigned_employees'].widget = forms.SelectMultiple(
            attrs={'class': 'form-select select2', 'size': 6},
        )
        self.fields['assigned_employees'].label = 'Assigned team members'


class PartForm(MesModelForm):
    class Meta:
        model = Part
        fields = [
            'barcode',
            'bom_item',
            'current_work_center',
            'status',
            'parent_part',
        ]
        widgets = {
            'barcode': forms.TextInput(attrs={'class': 'form-control', 'readonly': True}),
            'bom_item': forms.Select(attrs={'class': 'form-select'}),
            'current_work_center': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'parent_part': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, production_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.production_order = production_order
        is_create = not (self.instance and self.instance.pk)

        if production_order:
            self.fields['bom_item'].queryset = BOMItem.objects.filter(
                production_order=production_order,
                company=production_order.company,
                is_active=True,
            ).order_by('part_name')
            self.fields['parent_part'].queryset = Part.objects.filter(
                production_order=production_order,
                company=production_order.company,
                is_active=True,
            ).order_by('barcode')
            if self.instance.pk:
                self.fields['parent_part'].queryset = self.fields['parent_part'].queryset.exclude(
                    pk=self.instance.pk,
                )
            self.fields['current_work_center'].queryset = WorkCenter.objects.filter(
                company=production_order.company,
                is_active=True,
            ).order_by('sequence_order', 'name')
        else:
            self.fields['bom_item'].queryset = BOMItem.objects.none()
            self.fields['parent_part'].queryset = Part.objects.none()
            self.fields['current_work_center'].queryset = WorkCenter.objects.none()

        self.fields['parent_part'].required = False
        self.fields['parent_part'].empty_label = '— None —'
        self.fields['current_work_center'].required = False
        self.fields['current_work_center'].empty_label = '— Not assigned —'

        if is_create:
            self.fields['barcode'].required = False
            self.fields['barcode'].widget = forms.HiddenInput()
            self.fields['barcode'].initial = ''
        else:
            self.fields['barcode'].widget.attrs['readonly'] = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.production_order:
            instance.production_order = self.production_order
        if not instance.pk and not instance.barcode:
            instance.barcode = generate_part_barcode(self.production_order)
        if commit:
            instance.save()
        return instance


def generate_part_barcode(production_order: ProductionOrder) -> str:
    """Unique floor barcode for a manually added part."""
    po_slug = production_order.po_number.replace(' ', '-').upper()[:24]
    for _ in range(5):
        suffix = uuid.uuid4().hex[:8].upper()
        candidate = f'{po_slug}-{suffix}'
        if not Part.objects.filter(
            company=production_order.company,
            barcode=candidate,
        ).exists():
            return candidate
    return f'{po_slug}-{uuid.uuid4().hex.upper()}'
