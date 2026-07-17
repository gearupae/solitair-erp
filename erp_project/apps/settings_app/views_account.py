"""User-facing account and module access request views."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from apps.core.utils import PermissionChecker
from apps.hr.models import Employee
from apps.hr.models_extended import EmployeeHRProfile
from apps.purchase.email_outbound import email_sent_via_console, outgoing_mail_hint
from apps.settings_app.models import CompanySettings, ModuleAccessRequest, ModulePermission, UserRole
from apps.core.nav_config import (
    MINIMAL_NAV_DEPLOYED_MODULE_CODES,
    MINIMAL_NAV_MENU_MODULE_CODES,
    minimal_nav_enabled,
)
from apps.settings_app.module_catalog import get_module_catalog
from apps.settings_app.module_request_email import send_module_access_request_email


def _user_has_module_access(user, module_code):
    """Role-based module access only — superuser does not auto-grant all modules here."""
    if not user or not user.is_authenticated:
        return False
    user_roles = UserRole.objects.filter(user=user, is_active=True).values_list('role_id', flat=True)
    return ModulePermission.objects.filter(
        role_id__in=user_roles,
        module__iexact=module_code,
        can_view=True,
    ).exists()


def _build_module_cards(user):
    sent = set(
        ModuleAccessRequest.objects.filter(user=user).values_list('module', flat=True)
    )
    cards = []
    for item in get_module_catalog():
        code = item['code']
        if minimal_nav_enabled():
            has_access = code in MINIMAL_NAV_MENU_MODULE_CODES
        else:
            has_access = _user_has_module_access(user, code)
        request_sent = code in sent
        cards.append({
            **item,
            'has_access': has_access,
            'request_sent': request_sent,
            'status': 'active' if has_access else ('sent' if request_sent else 'available'),
        })
    return cards


def _module_stats(cards):
    active = sum(1 for c in cards if c['has_access'])
    sent = sum(1 for c in cards if c['request_sent'] and not c['has_access'])
    available = sum(1 for c in cards if not c['has_access'] and not c['request_sent'])
    return {
        'active_count': active,
        'sent_count': sent,
        'available_count': available,
        'total_count': len(cards),
    }


class UserSettingsView(LoginRequiredMixin, TemplateView):
    template_name = 'account/settings.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        roles = UserRole.objects.filter(user=user, is_active=True).select_related('role')
        sent_count = ModuleAccessRequest.objects.filter(user=user).count()
        catalog = get_module_catalog()
        accessible_count = sum(
            1 for item in catalog
            if _user_has_module_access(user, item['code'])
        )
        context.update({
            'title': 'My Settings',
            'roles': roles,
            'sent_count': sent_count,
            'accessible_count': accessible_count,
            'total_modules': len(catalog),
        })
        return context


class MyProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'account/my_profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        roles = UserRole.objects.filter(user=user, is_active=True).select_related('role')
        employee = (
            Employee.objects.filter(user=user, is_active=True)
            .select_related('department', 'designation', 'company')
            .first()
        )
        leave_context = None
        hr_profile = None
        if employee:
            from apps.hr.leave_context_service import build_employee_leave_context_dict

            leave_context = build_employee_leave_context_dict(employee)
            hr_profile = EmployeeHRProfile.objects.filter(employee=employee).first()

        context.update({
            'title': 'My Profile',
            'roles': roles,
            'employee': employee,
            'leave_context': leave_context,
            'hr_profile': hr_profile,
            'can_link_help': user.is_superuser or PermissionChecker.has_permission(user, 'hr', 'edit'),
        })
        return context


class ModuleRequestView(LoginRequiredMixin, TemplateView):
    template_name = 'account/module_requests.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cards = _build_module_cards(self.request.user)
        context.update({
            'title': 'Request Modules',
            'module_cards': cards,
            'stats': _module_stats(cards),
        })
        return context


@login_required
def submit_module_request(request):
    if request.method != 'POST':
        return redirect('account:module_requests')

    module_code = request.POST.get('module', '').strip()
    reason = request.POST.get('reason', '').strip()
    valid_codes = {item['code'] for item in get_module_catalog()}

    if module_code not in valid_codes:
        messages.error(request, 'Invalid module selected.')
        return redirect('account:module_requests')

    if minimal_nav_enabled() and module_code in MINIMAL_NAV_DEPLOYED_MODULE_CODES:
        messages.info(request, 'This module is already enabled in your deployment.')
        return redirect('account:module_requests')

    if _user_has_module_access(request.user, module_code):
        messages.info(request, 'You already have access to this module.')
        return redirect('account:module_requests')

    if ModuleAccessRequest.objects.filter(user=request.user, module=module_code).exists():
        messages.info(request, 'Request already sent for this module.')
        return redirect('account:module_requests')

    access_request = ModuleAccessRequest.objects.create(
        user=request.user,
        module=module_code,
        reason=reason,
        created_by=request.user,
        updated_by=request.user,
    )

    email_ok = send_module_access_request_email(access_request)
    module_label = dict(ModulePermission.MODULE_CHOICES).get(module_code, module_code)

    if email_ok:
        company = CompanySettings.get_settings()
        if email_sent_via_console(company):
            messages.success(
                request,
                f'Request sent for {module_label}. '
                f'(Development: email logged in server console — not delivered to erp@gear-up.ae.)',
            )
        else:
            messages.success(
                request,
                f'Request sent for {module_label}. Our team at erp@gear-up.ae has been notified.',
            )
    else:
        hint = outgoing_mail_hint(CompanySettings.get_settings()) or 'Check SMTP under Settings → Company.'
        messages.warning(
            request,
            f'Request recorded for {module_label}, but the email could not be sent. {hint}',
        )

    return redirect('account:module_requests')
