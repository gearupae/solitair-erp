"""
Core views for the ERP system.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.utils import timezone


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





