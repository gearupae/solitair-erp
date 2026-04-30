from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView

from apps.core.mixins import CreatePermissionMixin, PermissionRequiredMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker

from .forms import VehicleForm, VehicleOtherDocumentFormSet
from .models import Vehicle


class VehicleListView(PermissionRequiredMixin, ListView):
    model = Vehicle
    template_name = 'fleet/vehicle_list.html'
    context_object_name = 'vehicles'
    module_name = 'fleet'
    permission_type = 'view'

    def get_queryset(self):
        return Vehicle.objects.filter(is_active=True).select_related('driver').order_by('make', 'model')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Fleet — Vehicles'
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'fleet', 'create'
        )
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'fleet', 'edit'
        )
        return context


class VehicleCreateView(CreatePermissionMixin, CreateView):
    model = Vehicle
    form_class = VehicleForm
    template_name = 'fleet/vehicle_form.html'
    success_url = reverse_lazy('fleet:vehicle_list')
    module_name = 'fleet'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Add vehicle'
        if 'doc_formset' in kwargs:
            context['doc_formset'] = kwargs['doc_formset']
        elif self.request.method == 'POST':
            context['doc_formset'] = VehicleOtherDocumentFormSet(self.request.POST, instance=Vehicle())
        else:
            context['doc_formset'] = VehicleOtherDocumentFormSet(instance=Vehicle())
        return context

    def form_valid(self, form):
        self.object = form.save()
        formset = VehicleOtherDocumentFormSet(self.request.POST, instance=self.object)
        if formset.is_valid():
            formset.save()
            messages.success(self.request, 'Vehicle saved.')
            return HttpResponseRedirect(self.get_success_url())
        self.object.delete()
        self.object = None
        messages.error(self.request, 'Please correct the other documents below.')
        return self.render_to_response(self.get_context_data(form=form, doc_formset=formset))

    def form_invalid(self, form):
        formset = VehicleOtherDocumentFormSet(self.request.POST, instance=Vehicle())
        return self.render_to_response(self.get_context_data(form=form, doc_formset=formset))


class VehicleUpdateView(UpdatePermissionMixin, UpdateView):
    model = Vehicle
    form_class = VehicleForm
    template_name = 'fleet/vehicle_form.html'
    success_url = reverse_lazy('fleet:vehicle_list')
    module_name = 'fleet'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit vehicle: {self.object}'
        if 'doc_formset' in kwargs:
            context['doc_formset'] = kwargs['doc_formset']
        elif self.request.method == 'POST':
            context['doc_formset'] = VehicleOtherDocumentFormSet(self.request.POST, instance=self.object)
        else:
            context['doc_formset'] = VehicleOtherDocumentFormSet(instance=self.object)
        return context

    def form_valid(self, form):
        self.object = form.save()
        formset = VehicleOtherDocumentFormSet(self.request.POST, instance=self.object)
        if formset.is_valid():
            formset.save()
            messages.success(self.request, 'Vehicle updated.')
            return HttpResponseRedirect(self.get_success_url())
        messages.error(self.request, 'Please correct the other documents below.')
        return self.render_to_response(self.get_context_data(form=form, doc_formset=formset))

    def form_invalid(self, form):
        formset = VehicleOtherDocumentFormSet(self.request.POST, instance=self.object)
        return self.render_to_response(self.get_context_data(form=form, doc_formset=formset))
