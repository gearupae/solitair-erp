"""
Core views for the ERP system.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from apps.settings_app.models import Notification
from apps.core.utils import PermissionChecker
from apps.projects.gatepass_alerts import get_gatepass_dashboard_alerts
from apps.fleet.fleet_alerts import get_fleet_dashboard_alerts
from apps.core.compliance_service import get_compliance_dashboard_alerts, sync_compliance_notifications
from apps.crm.dashboard_notifications import get_dashboard_notifications, sync_dashboard_notifications
from apps.core.dashboard_pending_cards import get_dashboard_pending_cards


@login_required
def notification_open(request, pk):
    """Mark notification read and redirect to its link (same-origin path only)."""
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=['is_read'])
    link = (n.link or '').strip() or '/'
    if not link.startswith('/') or link.startswith('//'):
        link = '/'
    return redirect(link)


@login_required
@require_POST
def notifications_mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    next_url = request.POST.get('next', '').strip()
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('dashboard')


@login_required
def dashboard(request):
    """Main dashboard view."""
    from calendar import monthrange
    from decimal import Decimal
    from django.db.models import Count, Sum
    from django.utils import timezone

    today = timezone.localdate()
    month_end = today.replace(day=monthrange(today.year, today.month)[1])

    context = {
        'title': 'Dashboard',
        'dashboard_month_label': today.strftime('%B %Y'),
    }

    try:
        from apps.projects.models import Project

        pq = Project.objects.filter(is_active=True)
        context['project_total'] = pq.count()
        status_counts = {r['status']: r['c'] for r in pq.values('status').annotate(c=Count('pk'))}
        context['project_status_breakdown'] = [
            {'code': code, 'label': label, 'count': status_counts.get(code, 0)}
            for code, label in Project.STATUS_CHOICES
        ]
        context['project_in_progress'] = status_counts.get('ongoing', 0)
        context['project_completed'] = status_counts.get('completed', 0)
        context['project_open'] = pq.exclude(status__in=['completed', 'cancelled']).count()
    except Exception:
        context['project_total'] = 0
        context['project_status_breakdown'] = []
        context['project_in_progress'] = 0
        context['project_completed'] = 0
        context['project_open'] = 0

    try:
        from apps.hr.models import Employee

        eq = Employee.objects.filter(is_active=True)
        context['employee_total'] = eq.count()
        emp_status_counts = {r['status']: r['c'] for r in eq.values('status').annotate(c=Count('pk'))}
        context['employee_status_breakdown'] = [
            {'code': code, 'label': label, 'count': emp_status_counts.get(code, 0)}
            for code, label in Employee.STATUS_CHOICES
        ]
    except Exception:
        context['employee_total'] = 0
        context['employee_status_breakdown'] = []

    try:
        from apps.sales.models import Estimate, Invoice

        context['estimates_approved'] = Estimate.objects.filter(
            is_active=True, status__in=['approved', 'quotation_won'],
        ).count()
        inv = Invoice.objects.filter(
            is_active=True,
            invoice_date__gte=today.replace(day=1),
            invoice_date__lte=month_end,
        ).exclude(status__in=['draft', 'cancelled'])
        agg = inv.aggregate(s=Sum('total_amount'))
        context['invoiced_month_total'] = agg['s'] if agg['s'] is not None else Decimal('0.00')
        context['invoiced_month_count'] = inv.count()
    except Exception:
        context['estimates_approved'] = 0
        context['invoiced_month_total'] = Decimal('0.00')
        context['invoiced_month_count'] = 0

    try:
        from apps.contracts.models import Contract

        context['contracts_active'] = Contract.objects.filter(
            is_active=True,
            status='active',
            start_date__lte=today,
            end_date__gte=today,
        ).count()
    except Exception:
        context['contracts_active'] = 0

    try:
        from apps.crm.models import Customer

        context['total_customers'] = Customer.objects.filter(is_active=True).count()
    except Exception:
        context['total_customers'] = 0

    context['gatepass_expiry_alerts'] = get_gatepass_dashboard_alerts(request.user)
    context['fleet_expiry_alerts'] = get_fleet_dashboard_alerts(request.user)
    context['dashboard_notifications'] = get_dashboard_notifications(request.user)
    sync_dashboard_notifications(request.user, context['dashboard_notifications'])
    context['dashboard_pending_cards'] = get_dashboard_pending_cards(request.user)
    context['compliance_alerts'] = get_compliance_dashboard_alerts(request.user)
    sync_compliance_notifications(request.user, context['compliance_alerts'])
    context['fleet_can_edit'] = request.user.is_superuser or PermissionChecker.has_permission(
        request.user, 'fleet', 'edit'
    )

    return render(request, 'core/dashboard.html', context)





