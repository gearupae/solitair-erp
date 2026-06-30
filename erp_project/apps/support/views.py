"""
Support ticket views — list, kanban board, create, edit, detail.
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_http_methods
from django.views.generic import ListView, CreateView, UpdateView, DetailView

from apps.core.mixins import PermissionRequiredMixin, CreatePermissionMixin, UpdatePermissionMixin
from apps.core.utils import PermissionChecker
from apps.hr.models import Employee
from apps.settings_app.models import AuditLog
from apps.core.middleware import get_current_request

from .forms import PublicSupportTicketForm, SupportTicketForm
from .models import SupportTicket, SupportTicketKanbanStage
from .utils import (
    SUPPORT_KANBAN_CLOSED_THEME,
    SUPPORT_KANBAN_STAGE_THEMES,
    SUPPORT_KANBAN_UNASSIGNED_THEME,
    kanban_theme_style,
    search_public_link_suggestions,
)


def log_action(user, action, model, record_id, changes=None):
    request = get_current_request()
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0]
        else:
            ip_address = request.META.get('REMOTE_ADDR')
    AuditLog.objects.create(
        user=user,
        action=action,
        model=model,
        record_id=str(record_id),
        changes=changes or {},
        ip_address=ip_address,
    )


def apply_ticket_list_filters(queryset, params):
    search = (params.get('search') or '').strip()
    if search:
        queryset = queryset.filter(
            Q(ticket_number__icontains=search)
            | Q(subject__icontains=search)
            | Q(description__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(project__name__icontains=search)
            | Q(project__project_code__icontains=search)
            | Q(amc_contract__name__icontains=search)
            | Q(amc_contract__contract_number__icontains=search)
        )
    priority = (params.get('priority') or '').strip()
    if priority:
        queryset = queryset.filter(priority=priority)
    assignee = (params.get('assigned_to') or '').strip()
    if assignee:
        try:
            queryset = queryset.filter(assigned_to_id=int(assignee))
        except (TypeError, ValueError):
            pass
    stage = (params.get('stage') or '').strip()
    if stage:
        if stage == 'unassigned':
            queryset = queryset.filter(kanban_stage__isnull=True)
        else:
            try:
                queryset = queryset.filter(kanban_stage_id=int(stage))
            except (TypeError, ValueError):
                pass
    link_type = (params.get('link_type') or '').strip()
    if link_type:
        queryset = queryset.filter(link_type=link_type)
    date_from = (params.get('date_from') or '').strip()
    date_to = (params.get('date_to') or '').strip()
    if date_from:
        queryset = queryset.filter(opened_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(opened_date__lte=date_to)
    return queryset


class SupportTicketListView(PermissionRequiredMixin, ListView):
    model = SupportTicket
    template_name = 'support/ticket_list.html'
    context_object_name = 'tickets'
    module_name = 'support'
    permission_type = 'view'
    paginate_by = 25

    def get_queryset(self):
        qs = SupportTicket.objects.filter(is_active=True).select_related(
            'customer',
            'project',
            'amc_contract',
            'assigned_to',
            'kanban_stage',
        )
        return apply_ticket_list_filters(qs, self.request.GET).order_by('-opened_date', '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx['title'] = 'Support'
        ctx['priority_choices'] = SupportTicket.PRIORITY_CHOICES
        ctx['link_type_choices'] = SupportTicket.LINK_TYPE_CHOICES
        ctx['can_create'] = user.is_superuser or PermissionChecker.has_permission(
            user, 'support', 'create'
        )
        ctx['can_edit'] = user.is_superuser or PermissionChecker.has_permission(
            user, 'support', 'edit'
        )
        ctx['can_delete'] = user.is_superuser or PermissionChecker.has_permission(
            user, 'support', 'delete'
        )
        ctx['can_configure_kanban'] = user.is_superuser or PermissionChecker.has_permission(
            user, 'settings', 'edit'
        )
        ctx['assignee_choices'] = Employee.objects.filter(
            is_active=True,
            status='active',
        ).order_by('first_name', 'last_name')

        board_stages = list(
            SupportTicketKanbanStage.objects.filter(is_active=True, is_closed=False).order_by(
                'sort_order', 'id'
            )
        )
        ctx['kanban_stages'] = board_stages
        ctx['kanban_closed_stage'] = SupportTicketKanbanStage.objects.filter(
            is_active=True,
            is_closed=True,
        ).first()

        board_tickets = apply_ticket_list_filters(
            SupportTicket.objects.filter(is_active=True).select_related(
                'customer',
                'project',
                'amc_contract',
                'assigned_to',
                'kanban_stage',
            ),
            self.request.GET,
        ).order_by('-opened_date')
        tickets_by_stage = {s.id: [] for s in board_stages}
        unassigned = []
        for ticket in board_tickets:
            sid = ticket.kanban_stage_id
            if sid and sid in tickets_by_stage:
                tickets_by_stage[sid].append(ticket)
            else:
                unassigned.append(ticket)
        ctx['kanban_columns'] = [
            {
                'stage': s,
                'tickets': tickets_by_stage[s.id],
                'theme_style': kanban_theme_style(
                    SUPPORT_KANBAN_STAGE_THEMES[i % len(SUPPORT_KANBAN_STAGE_THEMES)]
                ),
            }
            for i, s in enumerate(board_stages)
        ]
        ctx['kanban_tickets_unassigned'] = unassigned
        ctx['kanban_unassigned_style'] = kanban_theme_style(SUPPORT_KANBAN_UNASSIGNED_THEME)
        ctx['kanban_closed_style'] = kanban_theme_style(SUPPORT_KANBAN_CLOSED_THEME)

        all_tickets = SupportTicket.objects.filter(is_active=True)
        ctx['total_tickets'] = all_tickets.count()
        ctx['open_tickets'] = all_tickets.filter(
            Q(kanban_stage__isnull=True) | Q(kanban_stage__is_closed=False)
        ).count()
        ctx['urgent_tickets'] = all_tickets.filter(priority='urgent').count()
        ctx['unassigned_tickets'] = all_tickets.filter(assigned_to__isnull=True).count()
        ctx['public_support_url'] = self.request.build_absolute_uri(reverse('support:public_create'))
        return ctx


class SupportTicketCreateView(CreatePermissionMixin, CreateView):
    model = SupportTicket
    form_class = SupportTicketForm
    template_name = 'support/ticket_form.html'
    success_url = reverse_lazy('support:ticket_list')
    module_name = 'support'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Create Support Ticket'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Support ticket {form.instance.ticket_number} created.')
        return super().form_valid(form)


class SupportTicketUpdateView(UpdatePermissionMixin, UpdateView):
    model = SupportTicket
    form_class = SupportTicketForm
    template_name = 'support/ticket_form.html'
    module_name = 'support'

    def get_queryset(self):
        return SupportTicket.objects.filter(is_active=True)

    def get_success_url(self):
        return reverse_lazy('support:ticket_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Edit {self.object.ticket_number}'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Support ticket updated.')
        return super().form_valid(form)


class SupportTicketDetailView(PermissionRequiredMixin, DetailView):
    model = SupportTicket
    template_name = 'support/ticket_detail.html'
    context_object_name = 'ticket'
    module_name = 'support'
    permission_type = 'view'

    def get_queryset(self):
        return SupportTicket.objects.filter(is_active=True).select_related(
            'customer',
            'project',
            'amc_contract',
            'assigned_to',
            'kanban_stage',
            'created_by',
            'updated_by',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx['title'] = self.object.ticket_number
        ctx['can_edit'] = user.is_superuser or PermissionChecker.has_permission(
            user, 'support', 'edit'
        )
        return ctx


@login_required
@require_POST
def support_kanban_move(request):
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'support', 'edit')
    ):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    try:
        body = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    pk = body.get('ticket_id')
    stage_raw = body.get('stage_id')
    if not pk:
        return JsonResponse({'error': 'ticket_id required.'}, status=400)
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid ticket_id.'}, status=400)

    ticket = SupportTicket.objects.filter(pk=pk, is_active=True).first()
    if not ticket:
        return JsonResponse({'error': 'Ticket not found.'}, status=404)

    if stage_raw in ('closed', '__closed__', True):
        closed = SupportTicketKanbanStage.objects.filter(is_active=True, is_closed=True).first()
        if not closed:
            return JsonResponse(
                {'error': 'No closed stage configured. Add one under Settings → Support pipeline.'},
                status=400,
            )
        ticket.kanban_stage = closed
        ticket.save(update_fields=['kanban_stage', 'updated_at'])
        log_action(request.user, 'update', 'SupportTicket', ticket.id, {'action': 'kanban_closed'})
        return JsonResponse({'ok': True, 'closed': True})

    if stage_raw in (None, '', 0, '0', 'null', 'unassigned'):
        SupportTicket.objects.filter(pk=pk).update(kanban_stage=None)
        log_action(request.user, 'update', 'SupportTicket', pk, {'action': 'kanban_unassigned'})
        return JsonResponse({'ok': True})

    try:
        stage_id = int(stage_raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid stage_id.'}, status=400)

    stage = SupportTicketKanbanStage.objects.filter(pk=stage_id, is_active=True).first()
    if not stage:
        return JsonResponse({'error': 'Stage not found.'}, status=404)

    SupportTicket.objects.filter(pk=pk).update(kanban_stage=stage)
    log_action(
        request.user,
        'update',
        'SupportTicket',
        pk,
        {'action': 'kanban_move', 'stage_id': stage_id, 'stage_name': stage.name},
    )
    return JsonResponse({'ok': True})


@login_required
@require_POST
def support_ticket_delete(request, pk):
    if not (
        request.user.is_superuser
        or PermissionChecker.has_permission(request.user, 'support', 'delete')
    ):
        messages.error(request, 'Permission denied.')
        return redirect('support:ticket_list')

    ticket = get_object_or_404(SupportTicket, pk=pk, is_active=True)
    ticket.is_active = False
    ticket.save(update_fields=['is_active', 'updated_at'])
    log_action(request.user, 'delete', 'SupportTicket', ticket.id)
    messages.success(request, f'Ticket {ticket.ticket_number} removed.')
    return redirect('support:ticket_list')


@never_cache
@require_http_methods(['GET', 'POST'])
def public_support_ticket_create(request):
    """Public (no login): submit a support ticket with name-based record matching."""
    if request.method == 'POST':
        form = PublicSupportTicketForm(request.POST)
        if form.is_valid():
            ticket = form.create_ticket()
            return render(
                request,
                'support/public_ticket_success.html',
                {'ticket': ticket},
            )
    else:
        form = PublicSupportTicketForm()

    return render(request, 'support/public_ticket_form.html', {'form': form})


@never_cache
def public_support_link_search(request):
    """JSON autocomplete for public support form (customers, projects, AMC)."""
    q = (request.GET.get('q') or '').strip()
    return JsonResponse({'results': search_public_link_suggestions(q)})
