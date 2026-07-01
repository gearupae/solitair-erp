"""Product template CRUD views."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import ProductTemplateForm, TemplateBOMItemForm, TemplateRoutingOpForm
from .models import ProductTemplate, TemplateBOMItem, TemplateRoutingOp
from .utils_template_bom import build_template_bom_tree
from .views import MesAccessMixin, MesCompanyMixin, MesSoftDeleteView, _company_or_none


class ProductTemplateListView(MesAccessMixin, ListView):
    model = ProductTemplate
    template_name = 'mes/product_template_list.html'
    context_object_name = 'templates'

    def get_queryset(self):
        company = _company_or_none()
        if not company:
            return ProductTemplate.objects.none()
        return ProductTemplate.objects.filter(company=company, is_active=True).order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Product Templates'
        return ctx


class ProductTemplateCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = ProductTemplate
    form_class = ProductTemplateForm
    template_name = 'mes/product_template_form.html'

    def get_success_url(self):
        return reverse('mes:product_template_detail', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'New Product Template'
        ctx['is_create'] = True
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Template "{form.instance.name}" created.')
        return super().form_valid(form)


class ProductTemplateDetailView(MesAccessMixin, DetailView):
    model = ProductTemplate
    template_name = 'mes/product_template_detail.html'
    context_object_name = 'template'

    def get_queryset(self):
        company = _company_or_none()
        qs = ProductTemplate.objects.filter(is_active=True)
        if company:
            qs = qs.filter(company=company)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        t = self.object
        ctx['title'] = t.name
        ctx['bom_tree'] = build_template_bom_tree(t)
        ctx['routing_ops'] = t.routing_ops.filter(is_active=True).select_related('work_center')
        return ctx


class ProductTemplateUpdateView(MesAccessMixin, MesCompanyMixin, UpdateView):
    model = ProductTemplate
    form_class = ProductTemplateForm
    template_name = 'mes/product_template_form.html'

    def get_queryset(self):
        return ProductTemplate.objects.filter(company=self.get_company(), is_active=True)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        return kwargs

    def get_success_url(self):
        return reverse('mes:product_template_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit {self.object.code}'
        ctx['is_create'] = False
        return ctx


class ProductTemplateDeleteView(MesSoftDeleteView):
    model = ProductTemplate
    success_url = reverse_lazy('mes:product_template_list')
    label_attr = 'name'


def _get_template(request, pk):
    company = _company_or_none()
    if not company:
        return None
    return get_object_or_404(ProductTemplate, pk=pk, company=company, is_active=True)


class TemplateBOMItemCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = TemplateBOMItem
    form_class = TemplateBOMItemForm
    template_name = 'mes/template_bom_item_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.template_obj = _get_template(request, kwargs['template_pk'])
        if not self.template_obj:
            return redirect('mes:product_template_list')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['template'] = self.template_obj
        return kwargs

    def get_success_url(self):
        return reverse('mes:product_template_detail', kwargs={'pk': self.template_obj.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add template BOM line'
        ctx['template_obj'] = self.template_obj
        return ctx


class TemplateBOMItemUpdateView(MesAccessMixin, MesCompanyMixin, UpdateView):
    model = TemplateBOMItem
    form_class = TemplateBOMItemForm
    template_name = 'mes/template_bom_item_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.template_obj = _get_template(request, kwargs['template_pk'])
        if not self.template_obj:
            return redirect('mes:product_template_list')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return TemplateBOMItem.objects.filter(template=self.template_obj, company=self.get_company(), is_active=True)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['template'] = self.template_obj
        return kwargs

    def get_success_url(self):
        return reverse('mes:product_template_detail', kwargs={'pk': self.template_obj.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit BOM — {self.object.part_name}'
        ctx['template_obj'] = self.template_obj
        return ctx


class TemplateBOMItemDeleteView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, template_pk, pk):
        template_obj = _get_template(request, template_pk)
        if not template_obj:
            return redirect('mes:product_template_list')
        obj = get_object_or_404(
            TemplateBOMItem,
            pk=pk,
            template=template_obj,
            company=self.get_company(),
            is_active=True,
        )
        obj.is_active = False
        obj.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, f'BOM line "{obj.part_name}" removed.')
        return redirect('mes:product_template_detail', pk=template_obj.pk)


class TemplateRoutingOpCreateView(MesAccessMixin, MesCompanyMixin, CreateView):
    model = TemplateRoutingOp
    form_class = TemplateRoutingOpForm
    template_name = 'mes/template_routing_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.template_obj = _get_template(request, kwargs['template_pk'])
        if not self.template_obj:
            return redirect('mes:product_template_list')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.get_company()
        kwargs['template'] = self.template_obj
        return kwargs

    def get_success_url(self):
        return reverse('mes:product_template_detail', kwargs={'pk': self.template_obj.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Add template routing step'
        ctx['template_obj'] = self.template_obj
        return ctx


class TemplateRoutingOpDeleteView(MesAccessMixin, MesCompanyMixin, View):
    def post(self, request, template_pk, pk):
        template_obj = _get_template(request, template_pk)
        if not template_obj:
            return redirect('mes:product_template_list')
        obj = get_object_or_404(
            TemplateRoutingOp,
            pk=pk,
            template=template_obj,
            company=self.get_company(),
            is_active=True,
        )
        obj.is_active = False
        obj.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, f'Routing step "{obj.work_center.code}" removed.')
        return redirect('mes:product_template_detail', pk=template_obj.pk)
