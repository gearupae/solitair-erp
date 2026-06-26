"""
Context processors for the ERP system.
"""
from django.conf import settings

from apps.core.utils import PermissionChecker
from apps.core.visibility import crm_show_my_leads_label
from apps.hr.models import Employee
from apps.settings_app.models import Notification


def global_context(request):
    """
    Add global context variables to all templates.
    """
    context = {
        'app_name': 'Gearup ERP',
        'current_year': __import__('datetime').datetime.now().year,
        'nav_hidden_modules': settings.NAV_HIDDEN_MODULES,
        'static_css_version': getattr(settings, 'STATIC_CSS_VERSION', '1'),
    }
    
    if request.user.is_authenticated:
        context['user_permissions'] = PermissionChecker.get_user_permissions(request.user)
        context['is_superuser'] = request.user.is_superuser
        context['header_linked_employee'] = Employee.objects.filter(
            user=request.user, is_active=True
        ).first()
        context['header_notifications'] = list(
            Notification.objects.filter(user=request.user, is_read=False).order_by('-created_at')[:15]
        )
        context['unread_notification_count'] = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
        context['crm_sales_rep_only'] = crm_show_my_leads_label(request.user)
        from apps.settings_app.ceo_access import user_can_access_ceo_dashboard
        context['can_access_ceo_dashboard'] = user_can_access_ceo_dashboard(request.user)
    else:
        context['header_notifications'] = []
        context['unread_notification_count'] = 0
        context['header_linked_employee'] = None
        context['crm_sales_rep_only'] = False
        context['can_access_ceo_dashboard'] = False

    return context

