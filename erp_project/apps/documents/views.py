"""Documents Views"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.db.models import Q
from datetime import date, timedelta
from .models import DocumentType, Document
from .forms import DocumentTypeForm, DocumentForm
from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker


class DocumentListView(PermissionRequiredMixin, ListView):
    model = Document
    template_name = 'documents/document_list.html'
    context_object_name = 'documents'
    module_name = 'documents'
    permission_type = 'view'
    
    def get_queryset(self):
        queryset = Document.objects.filter(is_active=True).select_related('document_type')
        
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(Q(entity_name__icontains=search) | Q(document_number__icontains=search))
        
        status = self.request.GET.get('status')
        today = date.today()
        if status == 'expired':
            queryset = queryset.filter(expiry_date__lt=today)
        elif status == 'expiring':
            queryset = queryset.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
        elif status == 'active':
            queryset = queryset.filter(expiry_date__gt=today + timedelta(days=30))
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Documents'
        today = date.today()
        all_docs = Document.objects.filter(is_active=True)
        context['expired_count'] = all_docs.filter(expiry_date__lt=today).count()
        context['expiring_count'] = all_docs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30)).count()
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'documents', 'create')
        context['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'documents', 'edit')
        return context


class DocumentCreateView(CreatePermissionMixin, CreateView):
    model = Document
    form_class = DocumentForm
    template_name = 'documents/document_form.html'
    success_url = reverse_lazy('documents:document_list')
    module_name = 'documents'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Add Document'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, 'Document added.')
        return super().form_valid(form)


class DocumentUpdateView(UpdatePermissionMixin, UpdateView):
    model = Document
    form_class = DocumentForm
    template_name = 'documents/document_form.html'
    success_url = reverse_lazy('documents:document_list')
    module_name = 'documents'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Document'
        return context


class DocumentTypeListView(PermissionRequiredMixin, ListView):
    model = DocumentType
    template_name = 'documents/type_list.html'
    context_object_name = 'document_types'
    module_name = 'documents'
    permission_type = 'view'
    
    def get_queryset(self):
        return DocumentType.objects.filter(is_active=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Document Types'
        context['form'] = DocumentTypeForm()
        context['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(self.request.user, 'documents', 'create')
        return context
    
    def post(self, request, *args, **kwargs):
        form = DocumentTypeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Document type created.')
        return redirect('documents:type_list')


@login_required
def document_delete(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.user.is_superuser or PermissionChecker.has_permission(request.user, 'documents', 'delete'):
        doc.is_active = False
        doc.save()
        messages.success(request, 'Document deleted.')
    return redirect('documents:document_list')





