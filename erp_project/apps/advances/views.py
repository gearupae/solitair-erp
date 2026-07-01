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
            # If user chose "Record & Post", immediately post to accounting
            if request.POST.get('post_now') == '1':
                try:
                    adv.post_to_accounting(user=request.user)
                    messages.success(
                        request,
                        f'Advance {adv.advance_number} recorded and posted to accounting.'
                    )
                except Exception as exc:
                    messages.warning(
                        request,
                        f'Advance {adv.advance_number} saved as draft. '
                        f'Post to accounting failed: {exc}'
                    )
            else:
                messages.success(request, f'Advance {adv.advance_number} saved as draft.')
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
def customer_advance_receipt_pdf(request, pk):
    """
    Receipt payment voucher PDF/HTML using the same layout as sales invoice_pdf.
    """
    from django.http import HttpResponse
    from django.template.loader import get_template

    from apps.settings_app.models import CompanySettings

    advance = get_object_or_404(
        CustomerAdvance.objects.select_related('customer', 'bank_account', 'journal_entry'),
        pk=pk,
        is_active=True,
    )

    if not _can(request.user, 'crm', 'view'):
        messages.error(request, 'Permission denied.')
        return redirect('crm:customer_list')

    company = CompanySettings.get_settings()

    def number_to_words(n):
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
                'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

        if n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + ('' if n % 10 == 0 else ' ' + ones[n % 10])
        elif n < 1000:
            return ones[n // 100] + ' Hundred' + ('' if n % 100 == 0 else ' and ' + number_to_words(n % 100))
        elif n < 1000000:
            return number_to_words(n // 1000) + ' Thousand' + ('' if n % 1000 == 0 else ' ' + number_to_words(n % 1000))
        elif n < 1000000000:
            return number_to_words(n // 1000000) + ' Million' + ('' if n % 1000000 == 0 else ' ' + number_to_words(n % 1000000))
        return str(n)

    try:
        amount_whole = int(advance.total_amount)
        amount_decimal = int((advance.total_amount - amount_whole) * 100)
        amount_words = number_to_words(amount_whole)
        if amount_decimal > 0:
            amount_words += f' and {amount_decimal}/100'
        amount_words += ' Dirhams Only'
    except (TypeError, ValueError, OverflowError):
        amount_words = ''

    vat_summary = {}
    if advance.vat_amount > 0 and advance.amount > 0:
        rate = float((advance.vat_amount / advance.amount) * 100)
        vat_summary[rate] = {'taxable': float(advance.amount), 'vat': float(advance.vat_amount)}
    elif advance.vat_amount > 0:
        vat_summary[5.0] = {'taxable': float(advance.amount), 'vat': float(advance.vat_amount)}

    if advance.amount > 0 and advance.vat_amount > 0:
        line_vat_rate = (advance.vat_amount / advance.amount) * 100
    else:
        line_vat_rate = Decimal('0')

    logo_absolute_url = ''
    if company.logo:
        logo_absolute_url = request.build_absolute_uri(company.logo.url)

    context = {
        'advance': advance,
        'company': company,
        'amount_words': amount_words,
        'vat_summary': vat_summary,
        'logo_absolute_url': logo_absolute_url,
        'is_pdf': True,
        'line_vat_rate': line_vat_rate,
    }

    output_format = request.GET.get('format', 'html')

    if output_format == 'pdf':
        try:
            from weasyprint import HTML

            template = get_template('advances/customer_advance_receipt_pdf.html')
            html_string = template.render(context)
            html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
            pdf = html.write_pdf()
            response = HttpResponse(pdf, content_type='application/pdf')
            safe_ref = advance.advance_number.replace('/', '-')
            response['Content-Disposition'] = f'inline; filename="Receipt_{safe_ref}.pdf"'
            return response
        except ImportError:
            messages.info(request, 'PDF generation requires WeasyPrint. Showing printable HTML version.')
            return render(request, 'advances/customer_advance_receipt_pdf.html', context)

    return render(request, 'advances/customer_advance_receipt_pdf.html', context)


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

def _vendor_purchased_items(vendor, limit: int = 100) -> list[dict]:
    """Unique line items from this vendor's purchase orders (qty rolled up)."""
    from apps.purchase.models import PurchaseOrderItem

    lines = (
        PurchaseOrderItem.objects.filter(
            purchase_order__vendor=vendor,
            purchase_order__is_active=True,
        )
        .exclude(purchase_order__status='cancelled')
        .select_related('purchase_order', 'inventory_item')
        .order_by('-purchase_order__order_date', '-pk')
    )

    grouped: dict[str, dict] = {}
    for line in lines:
        if line.inventory_item_id:
            key = f'inv:{line.inventory_item_id}'
        else:
            key = '|'.join([
                (line.brand or '').strip().lower(),
                (line.model or '').strip().lower(),
                (line.description or '').strip().lower(),
            ])
            if key == '||':
                continue

        if key not in grouped:
            inv = line.inventory_item
            grouped[key] = {
                'label': line.formatted_line_display(),
                'brand': (line.brand or '').strip(),
                'model': (line.model or '').strip(),
                'description': (line.description or '').strip(),
                'inventory_code': inv.item_code if inv else '',
                'total_qty': Decimal('0'),
                'order_count': 0,
                'last_order_date': line.purchase_order.order_date,
                'last_po_number': line.purchase_order.po_number,
                'last_po_pk': line.purchase_order_id,
            }

        row = grouped[key]
        row['total_qty'] += line.quantity or Decimal('0')
        row['order_count'] += 1
        po_date = line.purchase_order.order_date
        if po_date and (not row['last_order_date'] or po_date >= row['last_order_date']):
            row['last_order_date'] = po_date
            row['last_po_number'] = line.purchase_order.po_number
            row['last_po_pk'] = line.purchase_order_id

    rows = sorted(
        grouped.values(),
        key=lambda r: (r['last_order_date'] or date.min, r['label']),
        reverse=True,
    )
    return rows[:limit]


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
    ).select_related('purchase_order', 'project').order_by('-created_at')[:10]

    from apps.purchase.po_retention import vendor_bill_retention_summary_rows

    retention_bills = VendorBill.objects.filter(
        vendor=vendor, is_active=True, retention_amount__gt=0,
    ).exclude(status='cancelled').select_related('purchase_order', 'project').order_by('-bill_date', '-pk')
    bill_retention_summary = vendor_bill_retention_summary_rows(retention_bills)

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
        'purchased_items': _vendor_purchased_items(vendor),
        'bill_retention_rows': bill_retention_summary['rows'],
        'vendor_total_retention': bill_retention_summary['total_retention'],
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
            cheque = form.save(commit=False)
            # Auto-populate party_name from selected vendor
            if cheque.vendor:
                cheque.party_name = cheque.vendor.name
            cheque.save()
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
