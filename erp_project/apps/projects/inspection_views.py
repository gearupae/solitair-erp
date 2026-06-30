"""Inspection checklists — list, detail, public link (project or AMC)."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import DetailView, ListView

from apps.core.mixins import PermissionRequiredMixin
from apps.core.utils import PermissionChecker

from .forms import InspectionForm
from .models import Inspection, InspectionChecklistItem, InspectionChecklistUpload


def _parse_checklist_date(raw: str) -> date | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _checklist_row_html(item, *, show_delete=False, toggle_class='checklist-toggle'):
    return render_to_string(
        'projects/partials/checklist_item_row.html',
        {
            'item': item,
            'show_delete': show_delete,
            'toggle_class': toggle_class,
        },
    ).strip()


def _inspection_qs():
    return (
        Inspection.objects.filter(is_active=True)
        .select_related('project', 'amc_contract')
        .annotate(
            item_count=Count('checklist_items', filter=Q(checklist_items__is_active=True)),
            done_count=Count(
                'checklist_items',
                filter=Q(checklist_items__is_active=True, checklist_items__is_flagged_red=True),
            ),
        )
    )


def _inspection_by_token(token):
    return Inspection.objects.filter(is_active=True, public_token=token).first()


def _resolve_public_inspection(request, inspection_qs=None):
    inspection_qs = inspection_qs or _inspection_qs()
    raw_id = (request.GET.get('inspection') or request.POST.get('inspection') or '').strip()
    if raw_id.isdigit():
        return inspection_qs.filter(pk=int(raw_id)).first()
    return None


def _public_inspection_redirect(inspection_id: int):
    return redirect(reverse('projects:public_inspection') + f'?inspection={inspection_id}')


class InspectionListView(PermissionRequiredMixin, ListView):
    model = Inspection
    template_name = 'projects/inspection_list.html'
    context_object_name = 'inspections'
    module_name = 'projects'
    permission_type = 'view'
    paginate_by = 25

    def get_queryset(self):
        qs = _inspection_qs()
        search = (self.request.GET.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(inspection_number__icontains=search)
                | Q(project__name__icontains=search)
                | Q(project__project_code__icontains=search)
                | Q(amc_contract__name__icontains=search)
                | Q(amc_contract__contract_number__icontains=search)
            )
        link_type = (self.request.GET.get('link_type') or '').strip()
        if link_type in ('project', 'amc'):
            qs = qs.filter(link_type=link_type)
        return qs.order_by('-inspection_date', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Inspections'
        ctx['form'] = InspectionForm(initial={'inspection_date': timezone.now().date()})
        ctx['can_create'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'projects', 'create'
        )
        ctx['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'projects', 'edit'
        )
        ctx['search'] = (self.request.GET.get('search') or '').strip()
        ctx['link_type_filter'] = (self.request.GET.get('link_type') or '').strip()
        return ctx

    def post(self, request, *args, **kwargs):
        if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'create')):
            messages.error(request, 'You do not have permission to create inspections.')
            return redirect('projects:inspection_list')

        form = InspectionForm(request.POST)
        if not form.is_valid():
            self.object_list = self.get_queryset()
            context = self.get_context_data()
            context['form'] = form
            return self.render_to_response(context)

        inspection = form.save(commit=False)
        inspection.created_by = request.user
        inspection.updated_by = request.user
        inspection.full_clean()
        inspection.save()
        messages.success(request, f'Inspection {inspection.inspection_number} created.')
        return redirect('projects:inspection_detail', pk=inspection.pk)


class InspectionDetailView(PermissionRequiredMixin, DetailView):
    model = Inspection
    template_name = 'projects/inspection_detail.html'
    context_object_name = 'inspection'
    module_name = 'projects'
    permission_type = 'view'

    def get_queryset(self):
        return (
            Inspection.objects.filter(is_active=True)
            .select_related('project', 'amc_contract', 'created_by', 'updated_by')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        self.object.ensure_public_token()
        ctx['today'] = timezone.now().date()
        ctx['can_edit'] = self.request.user.is_superuser or PermissionChecker.has_permission(
            self.request.user, 'projects', 'edit'
        )
        ctx['checklist_public_url'] = self.request.build_absolute_uri(
            reverse('projects:public_inspection') + f'?inspection={self.object.pk}'
        )
        ctx['checklist_items'] = list(
            self.object.checklist_items.filter(is_active=True).order_by(
                '-item_date', '-sort_order', '-created_at'
            )
        )
        ctx['checklist_uploads'] = list(
            self.object.checklist_uploads.filter(is_active=True)
            .select_related('checklist_item')
            .order_by('-created_at')
        )
        return ctx


@never_cache
def public_inspection_token_redirect(request, token):
    inspection = _inspection_by_token(token)
    if not inspection:
        messages.error(request, 'Inspection link is invalid or no longer available.')
        return redirect('projects:public_inspection')
    return _public_inspection_redirect(inspection.pk)


@never_cache
@require_http_methods(['GET', 'POST'])
def public_inspection(request):
    """Public inspection hub: pick an inspection, toggle items, upload files."""
    inspection_qs = _inspection_qs().order_by('-inspection_date', '-created_at')
    inspection = _resolve_public_inspection(request, inspection_qs)
    selected_id = inspection.pk if inspection else None
    if not inspection:
        raw_id = (request.GET.get('inspection') or request.POST.get('inspection') or '').strip()
        if raw_id.isdigit():
            selected_id = int(raw_id)

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if not inspection:
            messages.error(request, 'Please select an inspection from the list.')
            return render(
                request,
                'projects/public_inspection.html',
                {
                    'inspections': inspection_qs,
                    'inspection': None,
                    'selected_inspection_id': selected_id,
                    'checklist_items': [],
                    'checklist_uploads': [],
                },
                status=400,
            )

        if action == 'toggle':
            item_id = request.POST.get('item_id')
            if item_id and str(item_id).isdigit():
                item = inspection.checklist_items.filter(pk=int(item_id), is_active=True).first()
                if item:
                    item.is_flagged_red = not item.is_flagged_red
                    item.save(update_fields=['is_flagged_red', 'updated_at'])
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'ok': True, 'is_flagged_red': item.is_flagged_red})
            return _public_inspection_redirect(inspection.pk)

        if action == 'upload':
            note = (request.POST.get('note') or '').strip()[:500]
            item_id = request.POST.get('checklist_item_id')
            checklist_item = None
            if item_id and str(item_id).isdigit():
                checklist_item = inspection.checklist_items.filter(pk=int(item_id), is_active=True).first()

            files = request.FILES.getlist('files')
            if not files:
                messages.error(request, 'Please add at least one file or photo.')
            else:
                for f in files:
                    InspectionChecklistUpload.objects.create(
                        inspection=inspection,
                        checklist_item=checklist_item,
                        file=f,
                        original_filename=getattr(f, 'name', '')[:255],
                        note=note,
                    )
                messages.success(request, f'{len(files)} file(s) uploaded.')
            return _public_inspection_redirect(inspection.pk)

    items = []
    uploads = []
    if inspection:
        items = list(
            inspection.checklist_items.filter(is_active=True).order_by(
                '-item_date', '-sort_order', '-created_at'
            )
        )
        uploads = list(
            inspection.checklist_uploads.filter(is_active=True)
            .select_related('checklist_item')
            .order_by('-created_at')
        )

    return render(
        request,
        'projects/public_inspection.html',
        {
            'inspections': inspection_qs,
            'inspection': inspection,
            'selected_inspection_id': selected_id,
            'checklist_items': items,
            'checklist_uploads': uploads,
        },
    )


@login_required
@require_POST
def inspection_checklist_toggle(request, pk):
    inspection = get_object_or_404(Inspection, pk=pk, is_active=True)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    item_id = request.POST.get('item_id')
    if not item_id or not str(item_id).isdigit():
        return JsonResponse({'ok': False, 'error': 'Invalid item.'}, status=400)

    item = inspection.checklist_items.filter(pk=int(item_id), is_active=True).first()
    if not item:
        return JsonResponse({'ok': False, 'error': 'Not found.'}, status=404)

    item.is_flagged_red = not item.is_flagged_red
    item.updated_by = request.user
    item.save(update_fields=['is_flagged_red', 'updated_by', 'updated_at'])
    return JsonResponse({'ok': True, 'is_flagged_red': item.is_flagged_red})


@login_required
@require_POST
def inspection_checklist_add(request, pk):
    inspection = get_object_or_404(Inspection, pk=pk, is_active=True)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    text = (request.POST.get('checklist_text') or '').strip()
    item_date = _parse_checklist_date(request.POST.get('checklist_date')) or date.today()
    if not text:
        return JsonResponse({'ok': False, 'error': 'Enter checklist text.'}, status=400)

    max_sort = (
        inspection.checklist_items.filter(is_active=True).aggregate(m=Max('sort_order')).get('m') or 0
    )
    item = InspectionChecklistItem.objects.create(
        inspection=inspection,
        text=text[:500],
        item_date=item_date,
        sort_order=max_sort + 1,
        created_by=request.user,
        updated_by=request.user,
    )
    return JsonResponse({
        'ok': True,
        'item': {'id': item.pk, 'is_flagged_red': item.is_flagged_red},
        'html': _checklist_row_html(item, show_delete=True),
    })


@login_required
@require_POST
def inspection_checklist_delete(request, pk):
    inspection = get_object_or_404(Inspection, pk=pk, is_active=True)
    if not (request.user.is_superuser or PermissionChecker.has_permission(request.user, 'projects', 'edit')):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    item_id = request.POST.get('item_id')
    if not item_id or not str(item_id).isdigit():
        return JsonResponse({'ok': False, 'error': 'Invalid item.'}, status=400)

    item = inspection.checklist_items.filter(pk=int(item_id), is_active=True).first()
    if not item:
        return JsonResponse({'ok': False, 'error': 'Not found.'}, status=404)

    item.is_active = False
    item.updated_by = request.user
    item.save(update_fields=['is_active', 'updated_by', 'updated_at'])
    return JsonResponse({'ok': True, 'item_id': item.pk})
