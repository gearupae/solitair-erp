"""
Core views for the ERP system.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from apps.settings_app.models import Notification


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
    context = {
        'title': 'Dashboard',
    }
    
    # Try to get counts from various modules
    try:
        from apps.crm.models import Customer
        context['total_customers'] = Customer.objects.filter(is_active=True).count()
        context['total_leads'] = Customer.objects.filter(is_active=True, customer_type='lead').count()
    except:
        context['total_customers'] = 0
        context['total_leads'] = 0
    
    return render(request, 'core/dashboard.html', context)





