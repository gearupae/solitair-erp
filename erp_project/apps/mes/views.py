"""MES views — manufacturing hub, lists, and CRUD (phase 2)."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from apps.core.mixins import PermissionRequiredMixin
from apps.core.utils import PermissionChecker

from .forms import (
    BOMItemForm,
    PartForm,
    ProductionOrderCreateForm,
    ProductionOrderUpdateForm,
    ProductionOrderTeamForm,
    RoutingOperationForm,
    RoutingOperationTeamForm,
    RoutingOperationUpdateForm,
    WorkCenterForm,
)
from .models import BOMItem, OracleSyncLog, Part, ProductionOrder, RoutingOperation, WorkCenter
from .services.costing import compute_wip_breakdown, recalculate_wip
from .services.oracle import OracleConnector
from .services.parts_generation import generate_parts_from_bom
from .services.po import POWorkflowError, release_production_order
from .services.pipeline import (
    PipelineError,
    advance_production_order,
    next_pipeline_status,
    previous_pipeline_status,
)
from .services.routing import ensure_routing_for_order, get_routing_operations, swap_routing_sequence
from .services.templates import copy_template_to_production_order
from .utils import get_default_mes_company
from .utils_bom import build_bom_tree


def _user_can_access_mes(user):
    return user.is_superuser or PermissionChecker.has_permission(user, 'settings', 'view')


def _company_or_none():
    return get_default_mes_company()


def _require_company(request):
    company = _company_or_none()
    if not company:
        messages.error(request, 'No active company configured for Manufacturing.')
    return company


class MesAccessMixin(PermissionRequiredMixin):
    """Manufacturing lives under Settings; reuse settings view permission."""

    module_name = 'settings'
    permission_type = 'view'


class MesCompanyMixin:
    """Resolve tenant company for queryset / form kwargs."""

    def get_company(self):
        return _company_or_none()

    def dispatch(self, request, *args, **kwargs):
        if not self.get_company():
            messages.error(request, 'No active company configured for Manufacturing.')
            return redirect('mes:index')
        return super().dispatch(request, *args, **kwargs)


class MesSoftDeleteView(MesAccessMixin, MesCompanyMixin, View):
    """POST-only soft delete (is_active=False)."""

    model = None
    success_url = None
    label_attr = 'name'

    def post(self, request, *args, **kwargs):
        company = self.get_company()
        obj = get_object_or_404(
            self.model,
            pk=kwargs['pk'],
            company=company,
            is_active=True,
        )
        label = str(getattr(obj, self.label_attr, obj))
        obj.is_active = False
        obj.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, f'"{label}" removed.')
        return redirect(self.success_url)


# ---------------------------------------------------------------------------
# Hub & lists
# ---------------------------------------------------------------------------


class MesIndexView(MesAccessMixin, ListView):
    """Manufacturing overview hub."""

    template_name = 'mes/index.html'
    context_object_name = 'production_orders'

    def get_queryset(self):
        company = _company_or_none()
        if not company:
            return ProductionOrder.objects.none()
        return (
            ProductionOrder.objects.filter(company=company, is_active=True)
            .order_by('-created_at')[:8]
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = _company_or_none()
        ctx['title'] = 'Manufacturing'
        ctx['company'] = company
        if company:
            ctx['work_center_count'] = WorkCenter.objects.filter(
                company=company, is_active=True,
            ).count()
            ctx['open_order_count'] = ProductionOrder.objects.filter(
                company=company,
                is_active=True,
                status__in=[
                    ProductionOrder.STATUS_RELEASED,
                    ProductionOrder.STATUS_IN_PRODUCTION,
                    ProductionOrder.STATUS_ON_HOLD,
                ],
            ).count()
        else:
            ctx['work_center_count'] = 0
            ctx['open_order_count'] = 0
        from apps.mes.services.gearup_agent import get_agent_ai_status

        agent_ai = get_agent_ai_status()
        ctx['agent_ai'] = agent_ai
        ctx['openai_configured'] = agent_ai['ai_available']
        return ctx


class WorkCenterListView(MesAccessMixin, ListView):
    model = WorkCenter
    template_name = 'mes/work_center_list.html'
    context_object_name = 'work_centers'

    def get_queryset(self):
        company = _company_or_none()
        if not company:
            return WorkCenter.objects.none()
        return WorkCenter.objects.filter(company=company, is_active=True).order_by(
            'sequence_order', 'name',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Work Centers'
        return ctx


class ProductionOrderListView(MesAccessMixin, ListView):
    model = ProductionOrder
    template_name = 'mes/production_order_list.html'
    context_object_name = 'orders'

    def get_queryset(self):
        company = _company_or_none()
        if not company:
            return ProductionOrder.objects.none()
        return (
            ProductionOrder.objects.filter(company=company, is_active=True)
            .annotate(parts_count=Count('parts', filter=Q(parts__is_active=True)))
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Production Orders'
        ctx['company'] = _company_or_none()
        return ctx


class ProductionOrderDetailView(MesAccessMixin, DetailView):
    model = ProductionOrder
    template_name = 'mes/production_order_detail.html'
    context_object_name = 'order'

    def get_queryset(self):
        company = _company_or_none()
        qs = ProductionOrder.objects.filter(is_active=True).prefetch_related(
            'bom_items__children',
            'parts__bom_item',
            'parts__current_work_center',
        )
        if company:
            qs = qs.filter(company=company)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object
        ctx['title'] = f'Production Order {order.po_number}'
        ctx['bom_tree'] = build_bom_tree(order)
        ctx['parts'] = order.parts.filter(is_active=True).select_related(
            'bom_item', 'current_work_center',
        )
        ctx['parts_count'] = ctx['parts'].count()
        ctx['can_edit_po'] = order.is_editable
        ctx['can_edit_bom'] = order.is_editable
        ctx['can_generate_parts'] = order.is_editable
        ctx['can_release'] = (
            order.is_editable and ctx['parts_count'] > 0
        )
        ctx['is_on_floor'] = order.is_on_floor
        ctx['can_assign_team'] = order.is_editable or order.is_on_floor
        ctx['can_edit_routing'] = order.is_editable
        ctx['routing_ops'] = get_routing_operations(order)
        ctx['cost_breakdown'] = compute_wip_breakdown(order)
        ctx['pipeline_stages'] = [
            (code, dict(ProductionOrder.STATUS_CHOICES).get(code, code))
            for code in ProductionOrder.PIPELINE_STAGES
        ]
        ctx['pipeline_stage_labels'] = dict(ProductionOrder.STATUS_CHOICES)
        ctx['next_status'] = next_pipeline_status(order)
        ctx['prev_status'] = previous_pipeline_status(order)
        if ctx['next_status']:
            ctx['next_status_label'] = dict(ProductionOrder.STATUS_CHOICES).get(ctx['next_status'], ctx['next_status'])
        if ctx['prev_status']:
            ctx['prev_status_label'] = dict(ProductionOrder.STATUS_CHOICES).get(ctx['prev_status'], ctx['prev_status'])
        ctx['team_form'] = ProductionOrderTeamForm(production_order=order)
        ctx['status_logs'] = order.status_logs.filter(is_active=True).select_related('changed_by')[:10]
        ctx['source_template'] = order.source_template_name or (
            order.product_template.name if order.product_template_id else ''
        )
        return ctx


@login_required
def tablet_home(request):
    if not _user_can_access_mes(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    company = _company_or_none()
    production_steps = []
    locations = []
    if company:
        all_centers = WorkCenter.objects.filter(
            company=company, is_active=True,
        ).order_by('sequence_order', 'name')
        production_steps = [wc for wc in all_centers if wc.is_production_step]
        locations = [wc for wc in all_centers if not wc.is_production_step]
    return render(
        request,
        'mes/tablet_home.html',
        {
            'title': 'Floor Tablet',
            'production_steps': production_steps,
            'location_centers': locations,
            'company': company,
        },
    )


@login_required
def part_label(request, pk):
    if not _user_can_access_mes(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('dashboard')
    company = _company_or_none()
    part = get_object_or_404(Part, pk=pk, is_active=True)
    if company and part.company_id != company.pk:
        messages.error(request, 'Part not found.')
        return redirect('mes:production_order_list')
    return render(
        request,
        'mes/part_label.html',
        {
            'title': f'Label — {part.barcode}',
            'part': part,
        },
    )


# ---------------------------------------------------------------------------
# Work center CRUD
# ---------------------------------------------------------------------------


class WorkCenterCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = WorkCenter
    form_class = WorkCenterForm
    template_name = 'mes/work_center_form.html'
    success_url = reverse_lazy('mes:work_center_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'New Work Center'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Work center "{form.instance.name}" created.')
        return super().form_valid(form)


class WorkCenterUpdateView(MesAccessMixin, MesCompanyMixin, UpdateView):
    model = WorkCenter
    form_class = WorkCenterForm
    template_name = 'mes/work_center_form.html'
    success_url = reverse_lazy('mes:work_center_list')

    def get_queryset(self):
        return WorkCenter.objects.filter(company=self.get_company(), is_active=True)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit {self.object.code}'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Work center "{form.instance.name}" updated.')
        return super().form_valid(form)


class WorkCenterDeleteView(MesSoftDeleteView):
    model = WorkCenter
    success_url = reverse_lazy('mes:work_center_list')
    label_attr = 'name'


# ---------------------------------------------------------------------------
# Production order CRUD
# ---------------------------------------------------------------------------


class ProductionOrderCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = ProductionOrder
    form_class = ProductionOrderCreateForm
    template_name = 'mes/production_order_form.html'

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'New Production Order'
        ctx['is_create'] = True
        return ctx

    def form_valid(self, form):
        form.instance.company = self.get_company()
        template = form.cleaned_data.get('product_template')
        response = super().form_valid(form)
        if template:
            bom_n, route_n = copy_template_to_production_order(template, self.object)
            messages.success(
                self.request,
                f'Production order {form.instance.po_number} created from template '
                f'({bom_n} BOM lines, {route_n} routing steps).',
            )
        else:
            ensure_routing_for_order(self.object)
            messages.success(
                self.request,
                f'Production order {form.instance.po_number} created — add BOM lines next.',
            )
        return response


class ProductionOrderUpdateView(MesAccessMixin, MesCompanyMixin, UpdateView):
    model = ProductionOrder
    form_class = ProductionOrderUpdateForm
    template_name = 'mes/production_order_form.html'

    def get_queryset(self):
        return ProductionOrder.objects.filter(company=self.get_company(), is_active=True)

    def dispatch(self, request, *args, **kwargs):
        company = self.get_company()
        order = get_object_or_404(
            ProductionOrder,
            pk=kwargs['pk'],
            company=company,
            is_active=True,
        )
        if not order.is_editable:
            messages.warning(request, 'Released orders cannot be edited.')
            return redirect('mes:production_order_detail', pk=order.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit {self.object.po_number}'
        ctx['is_create'] = False
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Production order "{form.instance.po_number}" updated.')
        return super().form_valid(form)


class GeneratePartsView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, pk):
        company = self.get_company()
        order = get_object_or_404(
            ProductionOrder,
            pk=pk,
            company=company,
            is_active=True,
        )
        try:
            created = generate_parts_from_bom(order)
            ensure_routing_for_order(order)
        except POWorkflowError as exc:
            messages.error(request, exc.message)
            return redirect('mes:production_order_detail', pk=pk)
        if created:
            messages.success(request, f'Generated {created} part(s).')
        else:
            messages.info(request, 'All required parts already exist — nothing new generated.')
        recalculate_wip(order)
        return redirect('mes:production_order_detail', pk=pk)


class ReleaseProductionOrderView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, pk):
        company = self.get_company()
        order = get_object_or_404(
            ProductionOrder,
            pk=pk,
            company=company,
            is_active=True,
        )
        try:
            release_production_order(order, user=request.user)
            recalculate_wip(order)
        except POWorkflowError as exc:
            messages.error(request, exc.message)
            return redirect('mes:production_order_detail', pk=pk)
        messages.success(
            request,
            f'{order.po_number} released to the floor — parts are now scannable on the tablet.',
        )
        return redirect('mes:production_order_detail', pk=pk)


class PipelineAdvanceView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(
            ProductionOrder,
            pk=pk,
            company=self.get_company(),
            is_active=True,
        )
        target = request.POST.get('target_status', '')
        try:
            advance_production_order(order, target, user=request.user)
            messages.success(request, f'Order moved to {order.get_status_display()}.')
        except PipelineError as exc:
            messages.error(request, exc.message)
        return redirect('mes:production_order_detail', pk=pk)


class ProductionOrderTeamAssignView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(
            ProductionOrder,
            pk=pk,
            company=self.get_company(),
            is_active=True,
        )
        if not (order.is_editable or order.is_on_floor):
            messages.error(request, 'Team cannot be changed for this order.')
            return redirect('mes:production_order_detail', pk=pk)
        form = ProductionOrderTeamForm(request.POST, production_order=order)
        if form.is_valid():
            order.assigned_employees.set(form.cleaned_data['assigned_employees'])
            recalculate_wip(order)
            messages.success(request, 'Team assignment updated.')
        else:
            messages.error(request, 'Could not update team assignment.')
        return redirect('mes:production_order_detail', pk=pk)


class RoutingOperationTeamAssignView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, po_pk, pk):
        order = get_object_or_404(
            ProductionOrder,
            pk=po_pk,
            company=self.get_company(),
            is_active=True,
        )
        if not (order.is_editable or order.is_on_floor):
            messages.error(request, 'Team cannot be changed for this order.')
            return redirect('mes:production_order_detail', pk=po_pk)
        op = get_object_or_404(
            RoutingOperation,
            pk=pk,
            production_order=order,
            company=self.get_company(),
            is_active=True,
        )
        form = RoutingOperationTeamForm(request.POST, routing_operation=op)
        if form.is_valid():
            op.assigned_employees.set(form.cleaned_data['assigned_employees'])
            recalculate_wip(order)
            messages.success(request, f'Team updated for {op.work_center.code}.')
        else:
            messages.error(request, 'Could not update operation team.')
        return redirect('mes:production_order_detail', pk=po_pk)


class RoutingOperationTeamPageView(MesAccessMixin, MesCompanyMixin, FormView):
    form_class = RoutingOperationTeamForm
    template_name = 'mes/routing_operation_team.html'

    def dispatch(self, request, *args, **kwargs):
        self.production_order = _get_production_order(request, kwargs['po_pk'])
        if not self.production_order:
            return redirect('mes:index')
        if not (self.production_order.is_editable or self.production_order.is_on_floor):
            messages.error(request, 'Team cannot be changed for this order.')
            return redirect('mes:production_order_detail', pk=self.production_order.pk)
        self.routing_operation = get_object_or_404(
            RoutingOperation,
            pk=kwargs['pk'],
            production_order=self.production_order,
            company=self.get_company(),
            is_active=True,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['routing_operation'] = self.routing_operation
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Team — {self.routing_operation.work_center.code}'
        ctx['production_order'] = self.production_order
        ctx['routing_operation'] = self.routing_operation
        return ctx

    def form_valid(self, form):
        self.routing_operation.assigned_employees.set(form.cleaned_data['assigned_employees'])
        recalculate_wip(self.production_order)
        messages.success(self.request, f'Team updated for {self.routing_operation.work_center.code}.')
        return redirect('mes:production_order_detail', pk=self.production_order.pk)


class ProductionOrderDeleteView(MesSoftDeleteView):
    model = ProductionOrder
    success_url = reverse_lazy('mes:production_order_list')
    label_attr = 'po_number'


class RoutingOperationCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = RoutingOperation
    form_class = RoutingOperationForm
    template_name = 'mes/routing_operation_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.production_order = _get_production_order(request, kwargs['po_pk'])
        if not self.production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, self.production_order)
        if locked:
            return locked
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['production_order'] = self.production_order
        return kwargs

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.production_order.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add routing operation'
        ctx['production_order'] = self.production_order
        ctx['is_create'] = True
        ctx['work_center_rates_json'] = json.dumps({
            str(wc.pk): str(wc.cost_per_hour)
            for wc in WorkCenter.objects.filter(
                company=self.get_company(), is_active=True,
            )
        })
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        recalculate_wip(self.production_order)
        messages.success(
            self.request,
            f'Operation {form.instance.work_center.code} added to routing.',
        )
        return response


class RoutingOperationUpdateView(MesAccessMixin, MesCompanyMixin, UpdateView):
    model = RoutingOperation
    form_class = RoutingOperationUpdateForm
    template_name = 'mes/routing_operation_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.production_order = _get_production_order(request, kwargs['po_pk'])
        if not self.production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, self.production_order)
        if locked:
            return locked
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return RoutingOperation.objects.filter(
            production_order=self.production_order,
            company=self.get_company(),
            is_active=True,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['production_order'] = self.production_order
        return kwargs

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.production_order.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit routing — {self.object.work_center.code}'
        ctx['production_order'] = self.production_order
        ctx['is_create'] = False
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        recalculate_wip(self.production_order)
        messages.success(self.request, f'Routing updated for {self.object.work_center.code}.')
        return response


class RoutingOperationDeleteView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, po_pk, pk):
        production_order = _get_production_order(request, po_pk)
        if not production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, production_order)
        if locked:
            return locked
        company = self.get_company()
        obj = get_object_or_404(
            RoutingOperation,
            pk=pk,
            production_order=production_order,
            company=company,
            is_active=True,
        )
        label = obj.work_center.code
        obj.is_active = False
        obj.save(update_fields=['is_active', 'updated_at'])
        recalculate_wip(production_order)
        messages.success(request, f'Routing operation "{label}" removed.')
        return redirect('mes:production_order_detail', pk=production_order.pk)


class RoutingOperationReorderView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, po_pk, pk, direction):
        production_order = _get_production_order(request, po_pk)
        if not production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, production_order)
        if locked:
            return locked
        company = self.get_company()
        operations = list(
            RoutingOperation.objects.filter(
                production_order=production_order,
                company=company,
                is_active=True,
            ).order_by('sequence', 'id'),
        )
        op = next((row for row in operations if row.pk == pk), None)
        if not op:
            messages.error(request, 'Routing operation not found.')
            return redirect('mes:production_order_detail', pk=production_order.pk)

        idx = operations.index(op)
        if direction == 'up' and idx > 0:
            swap_routing_sequence(op, operations[idx - 1])
        elif direction == 'down' and idx < len(operations) - 1:
            swap_routing_sequence(op, operations[idx + 1])
        return redirect('mes:production_order_detail', pk=production_order.pk)


# ---------------------------------------------------------------------------
# BOM item CRUD (scoped to production order)
# ---------------------------------------------------------------------------


def _get_production_order(request, po_pk):
    company = _require_company(request)
    if not company:
        return None
    return get_object_or_404(
        ProductionOrder,
        pk=po_pk,
        company=company,
        is_active=True,
    )


def _redirect_if_po_locked(request, production_order):
    if production_order and not production_order.is_editable:
        messages.warning(request, 'Order is locked after release — BOM, routing, and parts cannot be edited.')
        return redirect('mes:production_order_detail', pk=production_order.pk)
    return None


class BOMItemCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = BOMItem
    form_class = BOMItemForm
    template_name = 'mes/bom_item_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.production_order = _get_production_order(request, kwargs['po_pk'])
        if not self.production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, self.production_order)
        if locked:
            return locked
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['production_order'] = self.production_order
        return kwargs

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.production_order.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add BOM Line'
        ctx['production_order'] = self.production_order
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'BOM line "{form.instance.part_name}" added.')
        return super().form_valid(form)


class BOMItemUpdateView(MesAccessMixin, MesCompanyMixin, UpdateView):
    model = BOMItem
    form_class = BOMItemForm
    template_name = 'mes/bom_item_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.production_order = _get_production_order(request, kwargs['po_pk'])
        if not self.production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, self.production_order)
        if locked:
            return locked
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return BOMItem.objects.filter(
            production_order=self.production_order,
            company=self.get_company(),
            is_active=True,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['production_order'] = self.production_order
        return kwargs

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.production_order.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit BOM — {self.object.part_name}'
        ctx['production_order'] = self.production_order
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'BOM line "{form.instance.part_name}" updated.')
        return super().form_valid(form)


class BOMItemDeleteView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, po_pk, pk):
        production_order = _get_production_order(request, po_pk)
        if not production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, production_order)
        if locked:
            return locked
        company = _company_or_none()
        obj = get_object_or_404(
            BOMItem,
            pk=pk,
            production_order=production_order,
            company=company,
            is_active=True,
        )
        label = obj.part_name
        obj.is_active = False
        obj.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, f'BOM line "{label}" removed.')
        return redirect('mes:production_order_detail', pk=production_order.pk)


# ---------------------------------------------------------------------------
# Part CRUD (scoped to production order)
# ---------------------------------------------------------------------------


class PartCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = Part
    form_class = PartForm
    template_name = 'mes/part_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.production_order = _get_production_order(request, kwargs['po_pk'])
        if not self.production_order:
            return redirect('mes:index')
        locked = _redirect_if_po_locked(request, self.production_order)
        if locked:
            return locked
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['production_order'] = self.production_order
        return kwargs

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.production_order.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add Part'
        ctx['production_order'] = self.production_order
        return ctx

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Part "{form.instance.barcode}" created.',
        )
        return super().form_valid(form)


class PartUpdateView(MesAccessMixin, MesCompanyMixin, UpdateView):
    model = Part
    form_class = PartForm
    template_name = 'mes/part_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.production_order = _get_production_order(request, kwargs['po_pk'])
        if not self.production_order:
            return redirect('mes:index')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Part.objects.filter(
            production_order=self.production_order,
            company=self.get_company(),
            is_active=True,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['production_order'] = self.production_order
        return kwargs

    def get_success_url(self):
        return reverse('mes:production_order_detail', kwargs={'pk': self.production_order.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit Part {self.object.barcode}'
        ctx['production_order'] = self.production_order
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Part "{form.instance.barcode}" updated.')
        return super().form_valid(form)


class PartDeleteView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, po_pk, pk):
        production_order = _get_production_order(request, po_pk)
        if not production_order:
            return redirect('mes:index')
        if not production_order.is_editable:
            messages.warning(request, 'Parts cannot be removed after release.')
            return redirect('mes:production_order_detail', pk=production_order.pk)
        company = _company_or_none()
        obj = get_object_or_404(
            Part,
            pk=pk,
            production_order=production_order,
            company=company,
            is_active=True,
        )
        label = obj.barcode
        obj.is_active = False
        obj.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, f'Part "{label}" removed.')
        return redirect('mes:production_order_detail', pk=production_order.pk)


# ---------------------------------------------------------------------------
# Oracle sync
# ---------------------------------------------------------------------------


class OracleSyncLogListView(MesAccessMixin, ListView):
    model = OracleSyncLog
    template_name = 'mes/oracle_sync_log.html'
    context_object_name = 'logs'
    paginate_by = 50

    def get_queryset(self):
        company = _company_or_none()
        if not company:
            return OracleSyncLog.objects.none()
        return OracleSyncLog.objects.filter(company=company).order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Oracle Sync Log'
        return ctx


class OraclePullView(MesAccessMixin, TemplateView):
    """Mock/demo page — pull production orders from the local Oracle mock API."""

    template_name = 'mes/oracle_pull.html'

    def get_context_data(self, **kwargs):
        from apps.oracle_mock.data import SAMPLE_PRODUCTION_ORDERS

        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Pull from Oracle'
        company = _company_or_none()
        ctx['company'] = company
        ctx['mock_endpoint'] = self.request.build_absolute_uri('/oracle-mock/production-orders/')

        items = SAMPLE_PRODUCTION_ORDERS.get('items', [])
        existing = set()
        if company:
            numbers = [
                row.get('WorkOrderNumber') or row.get('ProductionOrderNumber')
                for row in items
            ]
            existing = set(
                ProductionOrder.objects.filter(
                    company=company,
                    po_number__in=[n for n in numbers if n],
                ).values_list('po_number', flat=True),
            )

        preview = []
        for row in items:
            po_number = row.get('WorkOrderNumber') or row.get('ProductionOrderNumber') or '—'
            preview.append(
                {
                    'po_number': po_number,
                    'description': row.get('WorkOrderDescription') or row.get('Description') or '',
                    'quantity': row.get('Quantity') or 1,
                    'status': row.get('StatusCode') or 'Released',
                    'planned_start': row.get('ScheduledStartDate'),
                    'planned_end': row.get('ScheduledCompletionDate'),
                    'already_imported': po_number in existing,
                },
            )
        ctx['preview_orders'] = preview
        return ctx


class OraclePullExecuteView(MesAccessMixin, MesCompanyMixin, View):
    """POST — import work orders via OracleConnector pointed at oracle-mock."""

    def post(self, request):
        company = self.get_company()
        connector = OracleConnector(company=company)
        connector.base_url = request.build_absolute_uri('/oracle-mock').rstrip('/')
        try:
            result = connector.pull_production_orders()
        except Exception as exc:
            messages.error(request, f'Oracle pull failed: {exc}')
            return redirect('mes:oracle_pull')

        created = result.get('created', 0)
        updated = result.get('updated', 0)
        if created or updated:
            messages.success(
                request,
                f'Pulled from Oracle — {created} created, {updated} updated.',
            )
        else:
            messages.warning(
                request,
                'No production orders returned from Oracle mock. Check the sync log for errors.',
            )
        return redirect('mes:oracle_pull')
