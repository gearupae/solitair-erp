"""Views for the Advances module."""
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView

from apps.core.mixins import PermissionRequiredMixin
from apps.core.utils import PermissionChecker

from .forms import (
    CustomerAdvanceApplicationForm,
    CustomerAdvanceForm,
    SecurityChequeEncashForm,
    SecurityChequeOutwardForm,
    SecurityChequeReturnForm,
    VendorAdvanceApplicationForm,
    VendorAdvanceForm,
)
from .models import (
    CustomerAdvance,
    CustomerAdvanceApplication,
    SecurityChequeOutward,
    VendorAdvance,
    VendorAdvanceApplication,
)


def _can(user, module, ptype):
    return user.is_superuser or PermissionChecker.has_permission(user, module, ptype)


# ===========================================================================
# MODULE 1 — Customer Advance
# ===========================================================================

@login_required
def customer_advance_tab(request, customer_pk):
    """
    Renders the Advances tab content for a Customer detail page.
    Called via a direct URL that returns a partial snippet OR full page.
    """
    from apps.crm.models import Customer
    customer = get_object_or_404(Customer, pk=customer_pk)

    if not _can(request.user, 'crm', 'view'):
        return render(request, 'advances/_403.html', status=403)

    advances = CustomerAdvance.objects.filter(
        customer=customer, is_active=True
    ).select_related('bank_account', 'journal_entry').order_by('-date')

    if request.method == 'POST':
        if not _can(request.user, 'crm', 'create'):
            messages.error(request, 'Permission denied.')
            return redirect('crm:customer_detail', pk=customer_pk)

        form = CustomerAdvanceForm(request.POST)
        if form.is_valid():
            adv = form.save(commit=False)
            adv.customer = customer
            adv.save()
            messages.success(request, f'Advance {adv.advance_number} created.')
            return redirect('crm:customer_detail', pk=customer_pk)
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f'{field}: {e}')
            return redirect('crm:customer_detail', pk=customer_pk)

    form = CustomerAdvanceForm(initial={'date': date.today()})
    return render(request, 'advances/_customer_advance_tab.html', {
        'customer': customer,
        'advances': advances,
        'form': form,
        'can_create': _can(request.user, 'crm', 'create'),
        'can_edit': _can(request.user, 'crm', 'edit'),
        'today': date.today().isoformat(),
    })


@login_required
def customer_advance_detail(request, pk):
    advance = get_object_or_404(CustomerAdvance, pk=pk, is_active=True)

    if not _can(request.user, 'crm', 'view'):
        messages.error(request, 'Permission denied.')
        return redirect('crm:customer_list')

    applications = advance.applications.select_related('invoice', 'journal_entry')
    app_form = CustomerAdvanceApplicationForm(advance=advance, initial={'date': date.today()})

    return render(request, 'advances/customer_advance_detail.html', {
        'title': f'Customer Advance — {advance.advance_number}',
        'advance': advance,
        'applications': applications,
        'app_form': app_form,
        'can_edit': _can(request.user, 'crm', 'edit'),
        'today': date.today().isoformat(),
    })


@login_required
def customer_advance_post(request, pk):
    advance = get_object_or_404(CustomerAdvance, pk=pk, is_active=True)

    if not _can(request.user, 'crm', 'edit'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:customer_advance_detail', pk=pk)

    if request.method == 'POST':
        try:
            advance.post_to_accounting(user=request.user)
            messages.success(request, f'Advance {advance.advance_number} posted to accounting.')
        except (ValidationError, Exception) as exc:
            messages.error(request, f'Error posting: {exc}')
    return redirect('advances:customer_advance_detail', pk=pk)


@login_required
def customer_advance_apply(request, pk):
    advance = get_object_or_404(CustomerAdvance, pk=pk, is_active=True)

    if not _can(request.user, 'crm', 'edit'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:customer_advance_detail', pk=pk)

    if request.method == 'POST':
        form = CustomerAdvanceApplicationForm(request.POST, advance=advance)
        if form.is_valid():
            app = form.save(commit=False)
            app.advance = advance
            app.save()
            try:
                app.apply(user=request.user)
                messages.success(
                    request,
                    f'AED {app.amount_applied:,.2f} applied to {app.invoice.invoice_number}.',
                )
            except (ValidationError, Exception) as exc:
                app.delete()
                messages.error(request, f'Error applying: {exc}')
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f'{field}: {e}')

    return redirect('advances:customer_advance_detail', pk=pk)


# ===========================================================================
# MODULE 2 — Vendor Advance
# ===========================================================================

@login_required
def vendor_detail(request, pk):
    """
    Vendor detail page (does not exist in purchase app) — created here.
    Includes the Advances tab.
    """
    from apps.purchase.models import Vendor, PurchaseOrder, VendorBill
    vendor = get_object_or_404(Vendor, pk=pk, is_active=True)

    if not _can(request.user, 'purchase', 'view'):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:vendor_list')

    advances = VendorAdvance.objects.filter(
        vendor=vendor, is_active=True
    ).select_related('bank_account', 'journal_entry').order_by('-date')

    recent_orders = PurchaseOrder.objects.filter(
        vendor=vendor, is_active=True
    ).order_by('-created_at')[:10]

    recent_bills = VendorBill.objects.filter(
        vendor=vendor, is_active=True
    ).order_by('-created_at')[:10]

    if request.method == 'POST':
        if not _can(request.user, 'purchase', 'create'):
            messages.error(request, 'Permission denied.')
            return redirect('advances:vendor_detail', pk=pk)

        form = VendorAdvanceForm(request.POST)
        if form.is_valid():
            adv = form.save(commit=False)
            adv.vendor = vendor
            adv.save()
            messages.success(request, f'Advance {adv.advance_number} created.')
            return redirect('advances:vendor_detail', pk=pk)
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f'{field}: {e}')
    else:
        form = VendorAdvanceForm(initial={'date': date.today()})

    return render(request, 'advances/vendor_detail.html', {
        'title': f'Vendor: {vendor.name}',
        'vendor': vendor,
        'advances': advances,
        'form': form,
        'recent_orders': recent_orders,
        'recent_bills': recent_bills,
        'can_create': _can(request.user, 'purchase', 'create'),
        'can_edit': _can(request.user, 'purchase', 'edit'),
        'today': date.today().isoformat(),
    })


@login_required
def vendor_advance_detail(request, pk):
    advance = get_object_or_404(VendorAdvance, pk=pk, is_active=True)

    if not _can(request.user, 'purchase', 'view'):
        messages.error(request, 'Permission denied.')
        return redirect('purchase:vendor_list')

    applications = advance.applications.select_related('bill', 'journal_entry')
    app_form = VendorAdvanceApplicationForm(advance=advance, initial={'date': date.today()})

    return render(request, 'advances/vendor_advance_detail.html', {
        'title': f'Vendor Advance — {advance.advance_number}',
        'advance': advance,
        'applications': applications,
        'app_form': app_form,
        'can_edit': _can(request.user, 'purchase', 'edit'),
        'today': date.today().isoformat(),
    })


@login_required
def vendor_advance_post(request, pk):
    advance = get_object_or_404(VendorAdvance, pk=pk, is_active=True)

    if not _can(request.user, 'purchase', 'edit'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:vendor_advance_detail', pk=pk)

    if request.method == 'POST':
        try:
            advance.post_to_accounting(user=request.user)
            messages.success(request, f'Advance {advance.advance_number} posted to accounting.')
        except (ValidationError, Exception) as exc:
            messages.error(request, f'Error posting: {exc}')
    return redirect('advances:vendor_advance_detail', pk=pk)


@login_required
def vendor_advance_apply(request, pk):
    advance = get_object_or_404(VendorAdvance, pk=pk, is_active=True)

    if not _can(request.user, 'purchase', 'edit'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:vendor_advance_detail', pk=pk)

    if request.method == 'POST':
        form = VendorAdvanceApplicationForm(request.POST, advance=advance)
        if form.is_valid():
            app = form.save(commit=False)
            app.advance = advance
            app.save()
            try:
                app.apply(user=request.user)
                messages.success(
                    request,
                    f'AED {app.amount_applied:,.2f} applied to {app.bill.bill_number}.',
                )
            except (ValidationError, Exception) as exc:
                app.delete()
                messages.error(request, f'Error applying: {exc}')
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f'{field}: {e}')

    return redirect('advances:vendor_advance_detail', pk=pk)


# ===========================================================================
# MODULE 3 — Security Cheque Outward
# ===========================================================================

class SecurityChequeListView(PermissionRequiredMixin, ListView):
    model = SecurityChequeOutward
    template_name = 'advances/security_cheque_list.html'
    context_object_name = 'cheques'
    module_name = 'finance'
    permission_type = 'view'
    paginate_by = 30

    def get_queryset(self):
        qs = SecurityChequeOutward.objects.filter(is_active=True)
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                party_name__icontains=q
            ) | SecurityChequeOutward.objects.filter(
                cheque_number__icontains=q, is_active=True
            )
            qs = qs.distinct()
        return qs.order_by('-issued_date')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Security Cheques Outward'
        ctx['status_choices'] = SecurityChequeOutward.STATUS_CHOICES
        ctx['can_create'] = _can(self.request.user, 'finance', 'create')
        ctx['can_edit'] = _can(self.request.user, 'finance', 'edit')
        ctx['selected_status'] = self.request.GET.get('status', '')
        ctx['q'] = self.request.GET.get('q', '')
        # Summary
        all_active = SecurityChequeOutward.objects.filter(is_active=True)
        ctx['total_issued'] = all_active.filter(status='issued').count()
        ctx['total_encashed'] = all_active.filter(status='encashed').count()
        ctx['total_returned'] = all_active.filter(status='returned').count()
        from django.db.models import Sum
        ctx['issued_amount'] = all_active.filter(status='issued').aggregate(
            t=Sum('amount')
        )['t'] or Decimal('0.00')
        return ctx


@login_required
def security_cheque_create(request):
    if not _can(request.user, 'finance', 'create'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:security_cheque_list')

    if request.method == 'POST':
        form = SecurityChequeOutwardForm(request.POST)
        if form.is_valid():
            cheque = form.save()
            try:
                cheque.post_issue_journal(user=request.user)
                messages.success(
                    request,
                    f'Security cheque {cheque.cheque_number} created and journal posted.'
                )
            except (ValidationError, Exception) as exc:
                messages.warning(
                    request,
                    f'Cheque saved but journal error: {exc}',
                )
            return redirect('advances:security_cheque_detail', pk=cheque.pk)
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f'{field}: {e}')
    else:
        form = SecurityChequeOutwardForm(initial={
            'issued_date': date.today(),
            'cheque_date': date.today(),
        })

    return render(request, 'advances/security_cheque_form.html', {
        'title': 'New Security Cheque Outward',
        'form': form,
    })


@login_required
def security_cheque_detail(request, pk):
    cheque = get_object_or_404(SecurityChequeOutward, pk=pk, is_active=True)

    if not _can(request.user, 'finance', 'view'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:security_cheque_list')

    encash_form = SecurityChequeEncashForm(initial={'encash_date': date.today()})
    return_form = SecurityChequeReturnForm(initial={'return_date': date.today()})

    return render(request, 'advances/security_cheque_detail.html', {
        'title': f'Security Cheque — {cheque.cheque_number}',
        'cheque': cheque,
        'encash_form': encash_form,
        'return_form': return_form,
        'can_edit': _can(request.user, 'finance', 'edit'),
    })


@login_required
def security_cheque_encash(request, pk):
    cheque = get_object_or_404(SecurityChequeOutward, pk=pk, is_active=True)

    if not _can(request.user, 'finance', 'edit'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:security_cheque_detail', pk=pk)

    if request.method == 'POST':
        form = SecurityChequeEncashForm(request.POST)
        if form.is_valid():
            bank_account = form.cleaned_data['bank_account']
            encash_date = form.cleaned_data['encash_date']
            try:
                cheque.post_encash_journal(
                    bank_account=bank_account,
                    encash_date=encash_date,
                    user=request.user,
                )
                messages.success(
                    request,
                    f'Cheque {cheque.cheque_number} marked as encashed and journal posted.'
                )
            except (ValidationError, Exception) as exc:
                messages.error(request, f'Error: {exc}')
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f'{field}: {e}')

    return redirect('advances:security_cheque_detail', pk=pk)


@login_required
def security_cheque_return(request, pk):
    cheque = get_object_or_404(SecurityChequeOutward, pk=pk, is_active=True)

    if not _can(request.user, 'finance', 'edit'):
        messages.error(request, 'Permission denied.')
        return redirect('advances:security_cheque_detail', pk=pk)

    if request.method == 'POST':
        form = SecurityChequeReturnForm(request.POST)
        if form.is_valid():
            return_date = form.cleaned_data['return_date']
            try:
                cheque.post_return_journal(return_date=return_date, user=request.user)
                messages.success(
                    request,
                    f'Cheque {cheque.cheque_number} marked as returned and journal posted.'
                )
            except (ValidationError, Exception) as exc:
                messages.error(request, f'Error: {exc}')
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f'{field}: {e}')

    return redirect('advances:security_cheque_detail', pk=pk)


@login_required
def customer_advance_vat_api(request):
    """
    Quick JSON endpoint: given amount, return VAT (5%) and total.
    Called from the advance form via JavaScript.
    """
    try:
        amount = Decimal(str(request.GET.get('amount', '0')))
        vat = (amount * Decimal('0.05')).quantize(Decimal('0.01'))
        total = amount + vat
        return JsonResponse({'vat': str(vat), 'total': str(total)})
    except Exception:
        return JsonResponse({'vat': '0.00', 'total': '0.00'})
