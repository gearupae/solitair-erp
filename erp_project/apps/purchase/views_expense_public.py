"""Public expense claim submission and employee lookup."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from apps.hr.models import Employee
from apps.hr.user_provisioning import default_roles_for_new_hire, provision_user_for_employee
from apps.purchase.forms import PublicExpenseClaimForm
from apps.purchase.models import ExpenseClaim, ExpenseClaimItem
from apps.purchase.services.expense_bill_ai import (
    build_item_description,
    extract_bill_from_uploaded_file,
)


def _public_branding_context():
    from apps.settings_app.models import CompanySettings

    co = CompanySettings.get_settings()
    logo_url = ''
    if co and getattr(co, 'logo', None) and co.logo.name:
        try:
            logo_url = co.logo.url
        except ValueError:
            logo_url = ''
    return {
        'company_name': co.company_name if co else '',
        'company_logo_url': logo_url,
    }


def _resolve_employee_user(employee: Employee):
    if employee.user_id:
        return employee.user, None
    roles = default_roles_for_new_hire()
    if not roles:
        return None, 'ERP login could not be created — contact HR to link your employee profile.'
    try:
        user, _ = provision_user_for_employee(employee, roles)
        return user, None
    except Exception as exc:
        return None, f'Could not link employee to ERP account: {exc}'


@transaction.atomic
def create_public_expense_claim(employee: Employee, bill_files: list) -> tuple[ExpenseClaim, list[str]]:
    """Create a submitted expense claim from public bill uploads."""
    user, err = _resolve_employee_user(employee)
    if err or not user:
        raise ValueError(err or 'Employee account not available.')

    warnings: list[str] = []
    items_data = []
    for uploaded in bill_files:
        uploaded.seek(0)
        extracted = extract_bill_from_uploaded_file(uploaded)
        if not extracted.get('ok'):
            raise ValueError(extracted.get('error') or f'Could not process {uploaded.name}.')
        warnings.extend(extracted.get('warnings') or [])
        items_data.append((uploaded, extracted))

    claim_date = date.today()
    for _, ext in items_data:
        if ext.get('bill_date'):
            try:
                claim_date = date.fromisoformat(ext['bill_date'])
                break
            except ValueError:
                pass

    claim = ExpenseClaim.objects.create(
        employee=user,
        claim_date=claim_date,
        description=f'Public submission — {employee.full_name} ({employee.employee_code})',
        status='submitted',
        submission_source='public_link',
        submitted_at=timezone.now(),
    )

    for uploaded, extracted in items_data:
        item_date = claim_date
        if extracted.get('bill_date'):
            try:
                item_date = date.fromisoformat(extracted['bill_date'])
            except ValueError:
                pass

        amount = extracted.get('total_amount')
        if amount is None:
            amount = Decimal('0.00')
            warnings.append(
                f'Amount not detected for {uploaded.name} — approver should set amount before approval.'
            )
        else:
            amount = Decimal(str(amount)).quantize(Decimal('0.01'))

        uploaded.seek(0)
        ExpenseClaimItem.objects.create(
            expense_claim=claim,
            date=item_date,
            category=extracted.get('category') or 'other',
            description=build_item_description(extracted),
            amount=amount,
            has_receipt=True,
            receipt=uploaded,
        )

    claim.calculate_totals()
    return claim, warnings


class PublicExpenseClaimView(TemplateView):
    """Anonymous expense claim submission (share URL with staff)."""

    template_name = 'purchase/public_expense_claim.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_public_branding_context())
        ctx['form'] = PublicExpenseClaimForm()
        ctx['heading'] = 'Submit expense bills'
        return ctx

    def post(self, request, *args, **kwargs):
        ctx = self.get_context_data(**kwargs)
        form = PublicExpenseClaimForm(request.POST, request.FILES)
        ctx['form'] = form
        if not form.is_valid():
            return self.render_to_response(ctx)

        employee = form.cleaned_data['employee']
        bills = form.cleaned_data['bills']
        try:
            claim, warnings = create_public_expense_claim(employee, bills)
        except ValueError as exc:
            form.add_error(None, str(exc))
            return self.render_to_response(ctx)
        except Exception as exc:
            form.add_error(None, f'Submission failed: {exc}')
            return self.render_to_response(ctx)

        request.session['public_expense_claim_ref'] = claim.claim_number
        request.session['public_expense_claim_warnings'] = warnings[:10]
        return redirect('purchase:public_expense_claim_done')


class PublicExpenseClaimDoneView(TemplateView):
    template_name = 'purchase/public_expense_claim_done.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_public_branding_context())
        ctx['claim_number'] = self.request.session.pop('public_expense_claim_ref', '')
        ctx['warnings'] = self.request.session.pop('public_expense_claim_warnings', [])
        ctx['heading'] = 'Expense claim submitted'
        return ctx


@require_GET
def public_expense_claim_lookup(request):
    """JSON employee lookup by code (no auth)."""
    code = (request.GET.get('code') or '').strip()
    if not code:
        return JsonResponse({'ok': False, 'error': 'Enter employee code.'}, status=400)
    emp = Employee.objects.filter(employee_code__iexact=code, is_active=True).first()
    if not emp or emp.status != 'active':
        return JsonResponse({'ok': False, 'error': 'Employee not found.'}, status=404)
    return JsonResponse({
        'ok': True,
        'employee_code': emp.employee_code,
        'name': emp.full_name,
        'department': emp.department.name if emp.department_id else '',
    })
