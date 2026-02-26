"""
Property Management Views - PDC & Bank Reconciliation
Enterprise-grade handling with audit controls.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Q, F
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
import json

from apps.core.mixins import CreatePermissionMixin, UpdatePermissionMixin
from .models import (
    Property, Unit, Tenant, Lease, PDCCheque,
    PDCAllocation, PDCAllocationLine, PDCBankMatch, AmbiguousMatchLog
)
from .forms import (
    PropertyForm, UnitForm, TenantForm, LeaseForm, PDCChequeForm,
    PDCDepositForm, PDCClearForm, PDCBounceForm, PDCAllocationForm,
    PDCAllocationLineForm, BankStatementMatchForm, BulkPDCForm
)


# =============================================================================
# Property Views
# =============================================================================

class PropertyListView(LoginRequiredMixin, ListView):
    model = Property
    template_name = 'property/property_list.html'
    context_object_name = 'properties'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Property.objects.filter(is_active=True)
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(property_number__icontains=search) |
                Q(address__icontains=search)
            )
        return queryset
    
    def post(self, request, *args, **kwargs):
        """Handle inline form submission."""
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Property name is required.')
            return redirect('property:property_list')
        
        property_obj = Property.objects.create(
            name=name,
            property_type=request.POST.get('property_type', 'residential'),
            total_units=request.POST.get('total_units', 0) or 0,
            address=request.POST.get('address', ''),
            city=request.POST.get('city', 'Dubai'),
            emirate=request.POST.get('emirate', 'Dubai'),
            created_by=request.user
        )
        messages.success(request, f'Property "{property_obj.name}" created successfully.')
        return redirect('property:property_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_properties'] = Property.objects.filter(is_active=True).count()
        context['total_units'] = Unit.objects.filter(is_active=True).count()
        context['occupied_units'] = Unit.objects.filter(is_active=True, status='occupied').count()
        return context


class PropertyCreateView(CreatePermissionMixin, LoginRequiredMixin, CreateView):
    model = Property
    form_class = PropertyForm
    template_name = 'property/property_form.html'
    success_url = reverse_lazy('property:property_list')
    permission_required = 'property.add_property'


class PropertyUpdateView(UpdatePermissionMixin, LoginRequiredMixin, UpdateView):
    model = Property
    form_class = PropertyForm
    template_name = 'property/property_form.html'
    success_url = reverse_lazy('property:property_list')
    permission_required = 'property.change_property'


class PropertyDetailView(LoginRequiredMixin, DetailView):
    model = Property
    template_name = 'property/property_detail.html'
    context_object_name = 'property'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['units'] = self.object.units.filter(is_active=True)
        return context


# =============================================================================
# Tenant Views
# =============================================================================

class TenantListView(LoginRequiredMixin, ListView):
    model = Tenant
    template_name = 'property/tenant_list.html'
    context_object_name = 'tenants'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Tenant.objects.filter(is_active=True)
        search = self.request.GET.get('search', '')
        status = self.request.GET.get('status', '')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(tenant_number__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search)
            )
        if status:
            queryset = queryset.filter(status=status)
        return queryset
    
    def post(self, request, *args, **kwargs):
        """Handle inline form submission."""
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Tenant name is required.')
            return redirect('property:tenant_list')
        
        tenant = Tenant.objects.create(
            name=name,
            email=request.POST.get('email', ''),
            phone=request.POST.get('phone', ''),
            mobile=request.POST.get('mobile', ''),
            company=request.POST.get('company', ''),
            status=request.POST.get('status', 'active'),
            emirates_id=request.POST.get('emirates_id', ''),
            trade_license=request.POST.get('trade_license', ''),
            trn=request.POST.get('trn', ''),
            address=request.POST.get('address', ''),
            created_by=request.user
        )
        messages.success(request, f'Tenant "{tenant.name}" created successfully.')
        return redirect('property:tenant_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_tenants'] = Tenant.objects.filter(is_active=True).count()
        context['active_tenants'] = Tenant.objects.filter(is_active=True, status='active').count()
        context['active_leases'] = Lease.objects.filter(is_active=True, status='active').count()
        return context


class TenantCreateView(CreatePermissionMixin, LoginRequiredMixin, CreateView):
    model = Tenant
    form_class = TenantForm
    template_name = 'property/tenant_form.html'
    success_url = reverse_lazy('property:tenant_list')
    permission_required = 'property.add_tenant'


class TenantUpdateView(UpdatePermissionMixin, LoginRequiredMixin, UpdateView):
    model = Tenant
    form_class = TenantForm
    template_name = 'property/tenant_form.html'
    success_url = reverse_lazy('property:tenant_list')
    permission_required = 'property.change_tenant'


class TenantDetailView(LoginRequiredMixin, DetailView):
    model = Tenant
    template_name = 'property/tenant_detail.html'
    context_object_name = 'tenant'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['leases'] = self.object.leases.filter(is_active=True)
        context['pdc_cheques'] = self.object.pdc_cheques.filter(is_active=True).order_by('cheque_date')
        context['outstanding_balance'] = self.object.outstanding_balance
        return context


# =============================================================================
# Lease Views
# =============================================================================

class LeaseListView(LoginRequiredMixin, ListView):
    model = Lease
    template_name = 'property/lease_list.html'
    context_object_name = 'leases'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Lease.objects.filter(is_active=True).select_related('unit', 'tenant', 'unit__property')
        search = self.request.GET.get('search', '')
        status = self.request.GET.get('status', '')
        tenant_id = self.request.GET.get('tenant', '')
        if search:
            queryset = queryset.filter(
                Q(lease_number__icontains=search) |
                Q(tenant__name__icontains=search) |
                Q(unit__unit_number__icontains=search)
            )
        if status:
            queryset = queryset.filter(status=status)
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_leases'] = Lease.objects.filter(is_active=True).count()
        context['active_leases'] = Lease.objects.filter(is_active=True, status='active').count()
        context['expiring_soon'] = Lease.objects.filter(
            is_active=True,
            status='active',
            end_date__lte=date.today() + timedelta(days=30)
        ).count()
        context['total_rent'] = Lease.objects.filter(
            is_active=True, status='active'
        ).aggregate(total=Sum('annual_rent'))['total'] or Decimal('0.00')
        context['tenants'] = Tenant.objects.filter(is_active=True)
        context['units'] = Unit.objects.filter(is_active=True).select_related('property')
        return context


class LeaseCreateView(LoginRequiredMixin, CreateView):
    model = Lease
    form_class = LeaseForm
    template_name = 'property/lease_form.html'
    success_url = reverse_lazy('property:lease_list')
    
    def post(self, request, *args, **kwargs):
        """Handle inline form submission from list page."""
        tenant_id = request.POST.get('tenant', '')
        unit_id = request.POST.get('unit', '')
        start_date = request.POST.get('start_date', '')
        end_date = request.POST.get('end_date', '')
        annual_rent = request.POST.get('annual_rent', '')
        
        if not all([tenant_id, start_date, end_date, annual_rent]):
            messages.error(request, 'All required fields must be filled.')
            return redirect('property:lease_list')
        
        try:
            tenant = Tenant.objects.get(pk=tenant_id, is_active=True)
            unit = Unit.objects.get(pk=unit_id, is_active=True) if unit_id else None
            
            lease = Lease.objects.create(
                tenant=tenant,
                unit=unit,
                lease_type=request.POST.get('lease_type', 'residential'),
                start_date=start_date,
                end_date=end_date,
                annual_rent=Decimal(annual_rent),
                num_cheques=request.POST.get('num_cheques', 1) or 1,
                security_deposit=Decimal(request.POST.get('security_deposit', 0) or 0),
                ejari_number=request.POST.get('ejari_number', ''),
                status=request.POST.get('status', 'draft'),
                created_by=request.user
            )
            
            # Mark unit as occupied
            if unit:
                unit.status = 'occupied'
                unit.save()
            
            messages.success(request, f'Lease {lease.lease_number} created successfully.')
        except Tenant.DoesNotExist:
            messages.error(request, 'Selected tenant not found.')
        except Unit.DoesNotExist:
            messages.error(request, 'Selected unit not found.')
        except Exception as e:
            messages.error(request, f'Error creating lease: {str(e)}')
        
        return redirect('property:lease_list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class LeaseUpdateView(LoginRequiredMixin, UpdateView):
    model = Lease
    form_class = LeaseForm
    template_name = 'property/lease_form.html'
    success_url = reverse_lazy('property:lease_list')
    
    def form_valid(self, form):
        messages.success(self.request, 'Lease updated successfully.')
        return super().form_valid(form)


class LeaseDetailView(LoginRequiredMixin, DetailView):
    model = Lease
    template_name = 'property/lease_detail.html'
    context_object_name = 'lease'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pdc_cheques'] = self.object.pdc_cheques.filter(is_active=True).order_by('cheque_date')
        return context


# =============================================================================
# PDC Cheque Views
# =============================================================================

class PDCListView(LoginRequiredMixin, ListView):
    model = PDCCheque
    template_name = 'property/pdc_list.html'
    context_object_name = 'pdcs'
    paginate_by = 30
    
    def get_queryset(self):
        queryset = PDCCheque.objects.filter(is_active=True).select_related('tenant', 'lease', 'deposited_to_bank')
        
        # Filters
        search = self.request.GET.get('search', '')
        status = self.request.GET.get('status', '')
        tenant_id = self.request.GET.get('tenant', '')
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')
        
        if search:
            # Try to search by amount if search is numeric
            search_filter = (
                Q(pdc_number__icontains=search) |
                Q(cheque_number__icontains=search) |
                Q(tenant__name__icontains=search) |
                Q(bank_name__icontains=search)
            )
            try:
                # If search is a number, also search by amount
                amount_search = Decimal(search.replace(',', ''))
                search_filter = search_filter | Q(amount=amount_search)
            except (ValueError, InvalidOperation):
                pass
            queryset = queryset.filter(search_filter)
        if status:
            queryset = queryset.filter(status=status)
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        if date_from:
            queryset = queryset.filter(cheque_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(cheque_date__lte=date_to)
        
        return queryset.order_by('cheque_date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Metrics
        all_pdcs = PDCCheque.objects.filter(is_active=True)
        context['total_pdcs'] = all_pdcs.count()
        context['total_amount'] = all_pdcs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        context['received_count'] = all_pdcs.filter(status='received').count()
        context['received_amount'] = all_pdcs.filter(status='received').aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        context['deposited_count'] = all_pdcs.filter(status='deposited').count()
        context['deposited_amount'] = all_pdcs.filter(status='deposited').aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        context['cleared_count'] = all_pdcs.filter(status='cleared').count()
        context['cleared_amount'] = all_pdcs.filter(status='cleared').aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        context['bounced_count'] = all_pdcs.filter(status='bounced').count()
        context['bounced_amount'] = all_pdcs.filter(status='bounced').aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Due for deposit (cheque_date <= today and status = received)
        context['due_for_deposit'] = all_pdcs.filter(
            status='received',
            cheque_date__lte=date.today()
        ).count()
        
        context['tenants'] = Tenant.objects.filter(is_active=True)
        context['status_choices'] = PDCCheque.STATUS_CHOICES
        context['today'] = date.today()
        
        return context


class PDCCreateView(LoginRequiredMixin, CreateView):
    model = PDCCheque
    form_class = PDCChequeForm
    template_name = 'property/pdc_form.html'
    success_url = reverse_lazy('property:pdc_list')
    
    def post(self, request, *args, **kwargs):
        """Handle inline form submission from list page."""
        tenant_id = request.POST.get('tenant', '')
        if not tenant_id:
            messages.error(request, 'Tenant is required.')
            return redirect('property:pdc_list')
        
        cheque_number = request.POST.get('cheque_number', '').strip()
        if not cheque_number:
            messages.error(request, 'Cheque number is required.')
            return redirect('property:pdc_list')
        
        bank_name = request.POST.get('bank_name', '').strip()
        if not bank_name:
            messages.error(request, 'Bank name is required.')
            return redirect('property:pdc_list')
        
        cheque_date = request.POST.get('cheque_date', '')
        if not cheque_date:
            messages.error(request, 'Cheque date is required.')
            return redirect('property:pdc_list')
        
        amount = request.POST.get('amount', '')
        if not amount:
            messages.error(request, 'Amount is required.')
            return redirect('property:pdc_list')
        
        try:
            tenant = Tenant.objects.get(pk=tenant_id, is_active=True)
            with transaction.atomic():
                pdc = PDCCheque.objects.create(
                    tenant=tenant,
                    cheque_number=cheque_number,
                    bank_name=bank_name,
                    cheque_date=cheque_date,
                    amount=Decimal(amount),
                    drawer_name=request.POST.get('drawer_name', tenant.name),
                    purpose=request.POST.get('purpose', 'rent'),
                    received_by=request.user,
                    created_by=request.user
                )
                journal = pdc.post_received_journal(request.user)
            messages.success(request, f'PDC {pdc.pdc_number} created. Journal: {journal.entry_number}')
        except Tenant.DoesNotExist:
            messages.error(request, 'Selected tenant not found.')
        except Exception as e:
            messages.error(request, f'Error creating PDC: {str(e)}')
        
        return redirect('property:pdc_list')
    
    def form_valid(self, form):
        form.instance.received_by = self.request.user
        form.instance.created_by = self.request.user
        with transaction.atomic():
            response = super().form_valid(form)
            journal = self.object.post_received_journal(self.request.user)
        messages.success(self.request, f'PDC created. Journal: {journal.entry_number}')
        return response


class PDCDetailView(LoginRequiredMixin, DetailView):
    model = PDCCheque
    template_name = 'property/pdc_detail.html'
    context_object_name = 'pdc'
    
    def get_context_data(self, **kwargs):
        from apps.finance.models import BankAccount
        context = super().get_context_data(**kwargs)
        context['deposit_form'] = PDCDepositForm()
        context['clear_form'] = PDCClearForm()
        context['bounce_form'] = PDCBounceForm()
        context['bank_accounts'] = BankAccount.objects.filter(is_active=True)
        context['today'] = date.today().isoformat()
        return context


@login_required
def pdc_deposit(request, pk):
    """Submit PDC to bank for clearing. Status change only — GL was posted on receipt."""
    pdc = get_object_or_404(PDCCheque, pk=pk, is_active=True)

    if request.method == 'POST':
        form = PDCDepositForm(request.POST)
        if form.is_valid():
            try:
                pdc.deposit(
                    bank_account=form.cleaned_data['bank_account'],
                    user=request.user,
                    deposit_date=form.cleaned_data['deposit_date'],
                )
                messages.success(request, f'PDC {pdc.pdc_number} submitted to bank for clearing.')
            except Exception as e:
                messages.error(request, f'Error depositing PDC: {str(e)}')
        else:
            messages.error(request, 'Invalid form data.')

    return redirect('property:pdc_detail', pk=pk)


@login_required
def pdc_clear(request, pk):
    """Mark PDC as cleared."""
    pdc = get_object_or_404(PDCCheque, pk=pk, is_active=True)
    
    if request.method == 'POST':
        form = PDCClearForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    journal = pdc.clear(
                        user=request.user,
                        clearing_date=form.cleaned_data['clearing_date'],
                        clearing_reference=form.cleaned_data.get('clearing_reference', '')
                    )
                    messages.success(request, f'PDC {pdc.pdc_number} cleared. Journal: {journal.entry_number}')
            except Exception as e:
                messages.error(request, f'Error clearing PDC: {str(e)}')
        else:
            messages.error(request, 'Invalid form data.')
    
    return redirect('property:pdc_detail', pk=pk)


@login_required
def pdc_bounce(request, pk):
    """Record PDC bounce."""
    pdc = get_object_or_404(PDCCheque, pk=pk, is_active=True)
    
    if request.method == 'POST':
        form = PDCBounceForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    journal = pdc.bounce(
                        user=request.user,
                        bounce_date=form.cleaned_data['bounce_date'],
                        bounce_reason=form.cleaned_data['bounce_reason'],
                        bounce_charges=form.cleaned_data.get('bounce_charges', Decimal('0.00'))
                    )
                    messages.success(request, f'PDC {pdc.pdc_number} marked as bounced. Journal: {journal.entry_number}')
            except Exception as e:
                messages.error(request, f'Error recording bounce: {str(e)}')
        else:
            messages.error(request, 'Invalid form data.')
    
    return redirect('property:pdc_detail', pk=pk)


@login_required
def bulk_pdc_create(request):
    """Create multiple PDCs from a lease."""
    if request.method == 'POST':
        form = BulkPDCForm(request.POST)
        if form.is_valid():
            lease = form.cleaned_data['lease']
            bank_name = form.cleaned_data['bank_name']
            first_cheque = int(form.cleaned_data['first_cheque_number'])
            drawer_name = form.cleaned_data.get('drawer_name', lease.tenant.name)
            drawer_account = form.cleaned_data.get('drawer_account', '')
            notes = form.cleaned_data.get('notes', '')
            
            # Calculate payment amounts and dates
            payment_amount = lease.payment_amount
            num_payments = lease.number_of_cheques
            
            # Determine payment interval
            if lease.payment_frequency == 'monthly':
                interval_months = 1
            elif lease.payment_frequency == 'quarterly':
                interval_months = 3
            elif lease.payment_frequency == 'semi_annual':
                interval_months = 6
            else:  # annual
                interval_months = 12
            
            created_pdcs = []
            current_date = lease.start_date
            
            try:
                with transaction.atomic():
                    for i in range(num_payments):
                        cheque_number = str(first_cheque + i)
                        
                        # Calculate period
                        period_start = current_date
                        next_date = current_date + timedelta(days=interval_months * 30)
                        period_end = next_date - timedelta(days=1)
                        
                        pdc = PDCCheque.objects.create(
                            tenant=lease.tenant,
                            lease=lease,
                            cheque_number=cheque_number,
                            bank_name=bank_name,
                            cheque_date=current_date,
                            amount=payment_amount,
                            drawer_name=drawer_name,
                            drawer_account=drawer_account,
                            purpose='rent',
                            payment_period_start=period_start,
                            payment_period_end=period_end,
                            received_by=request.user,
                            notes=notes,
                            created_by=request.user
                        )
                        pdc.post_received_journal(request.user)
                        created_pdcs.append(pdc)
                        current_date = next_date
                    
                    messages.success(request, f'{len(created_pdcs)} PDCs created successfully for {lease.tenant.name}')
                    return redirect('property:lease_detail', pk=lease.pk)
            except Exception as e:
                messages.error(request, f'Error creating PDCs: {str(e)}')
    else:
        form = BulkPDCForm()
    
    return render(request, 'property/bulk_pdc_form.html', {'form': form})


# =============================================================================
# Bank Reconciliation with PDC Matching
# =============================================================================

@login_required
def pdc_bank_reconciliation(request):
    """
    Bank reconciliation screen with PDC matching.
    Implements ambiguous match detection.
    """
    from apps.finance.models import BankStatement, BankStatementLine, BankAccount
    
    bank_id = request.GET.get('bank', '')
    statement_id = request.GET.get('statement', '')
    
    banks = BankAccount.objects.filter(is_active=True)
    statements = []
    unmatched_lines = []
    matched_lines = []
    ambiguous_lines = []
    
    if bank_id:
        statements = BankStatement.objects.filter(
            bank_account_id=bank_id,
            is_active=True
        ).order_by('-statement_start_date')
    
    if statement_id:
        statement = get_object_or_404(BankStatement, pk=statement_id)
        
        for line in statement.lines.all():
            # Get potential PDC matches
            potential_matches = find_pdc_matches(line)
            
            if line.reconciliation_status == 'matched':
                matched_lines.append({
                    'line': line,
                    'matches': potential_matches
                })
            elif len(potential_matches) > 1:
                # Ambiguous match - multiple PDCs
                ambiguous_lines.append({
                    'line': line,
                    'matches': potential_matches
                })
                
                # Log ambiguous match
                AmbiguousMatchLog.objects.get_or_create(
                    bank_statement_line=line,
                    defaults={
                        'matching_pdc_ids': [m.pk for m in potential_matches],
                        'match_criteria': {
                            'amount': str(line.credit - line.debit),
                            'date': str(line.transaction_date),
                            'reference': line.reference
                        }
                    }
                )
            else:
                unmatched_lines.append({
                    'line': line,
                    'matches': potential_matches
                })
    
    context = {
        'banks': banks,
        'statements': statements,
        'selected_bank': bank_id,
        'selected_statement': statement_id,
        'unmatched_lines': unmatched_lines,
        'matched_lines': matched_lines,
        'ambiguous_lines': ambiguous_lines,
        'ambiguous_count': len(ambiguous_lines),
    }
    
    return render(request, 'property/pdc_bank_reconciliation.html', context)


def find_pdc_matches(bank_line, date_tolerance=3):
    """
    Find potential PDC matches for a bank statement line.
    
    Priority 1: Amount + Date + Bank Account
    Priority 2: Cheque Number (if available)
    
    Returns list of matching PDCs.
    """
    from apps.finance.models import BankStatementLine
    
    matches = []
    
    # Get deposited PDCs for this bank
    deposited_pdcs = PDCCheque.objects.filter(
        status='deposited',
        deposit_status='in_clearing',
        deposited_to_bank=bank_line.statement.bank_account,
        is_active=True
    )
    
    # Match by amount first (priority) - use credit for deposits
    line_amount = bank_line.credit if bank_line.credit > 0 else bank_line.debit
    amount_matches = deposited_pdcs.filter(amount=line_amount)
    
    for pdc in amount_matches:
        score = 50  # Base score for amount match
        
        # Date match (within tolerance)
        date_diff = abs((bank_line.transaction_date - pdc.cheque_date).days)
        if date_diff <= date_tolerance:
            score += 30
        
        # Cheque number in reference
        if bank_line.reference and pdc.cheque_number in bank_line.reference:
            score += 20
        
        # Create/update match record
        match, created = PDCBankMatch.objects.get_or_create(
            bank_statement_line=bank_line,
            pdc=pdc,
            defaults={
                'match_score': score,
                'amount_matched': True,
                'date_matched': date_diff <= date_tolerance,
                'cheque_number_matched': bank_line.reference and pdc.cheque_number in bank_line.reference,
                'bank_matched': True,
            }
        )
        if not created:
            match.match_score = score
            match.save()
        
        matches.append(pdc)
    
    return matches


@login_required
def pdc_auto_match(request, statement_id):
    """
    Attempt auto-matching of bank statement lines to PDCs.
    Only matches when exactly ONE PDC matches (no ambiguity).
    """
    from apps.finance.models import BankStatement
    
    statement = get_object_or_404(BankStatement, pk=statement_id)
    auto_matched = 0
    ambiguous = 0
    unmatched = 0
    
    for line in statement.lines.filter(reconciliation_status='unmatched'):
        matches = find_pdc_matches(line)
        
        if len(matches) == 1:
            # Single match - auto reconcile
            pdc = matches[0]
            try:
                with transaction.atomic():
                    pdc.clear(request.user, clearing_date=line.transaction_date)
                    pdc.bank_statement_line = line
                    pdc.reconciled = True
                    pdc.reconciled_date = date.today()
                    pdc.reconciled_by = request.user
                    pdc.save()
                    
                    line.reconciliation_status = 'matched'
                    line.match_method = 'auto'
                    line.save()
                    
                    auto_matched += 1
            except Exception:
                unmatched += 1
        elif len(matches) > 1:
            ambiguous += 1
        else:
            unmatched += 1
    
    messages.info(
        request,
        f'Auto-matching complete: {auto_matched} matched, {ambiguous} ambiguous (require manual), {unmatched} unmatched'
    )
    
    return redirect('property:pdc_bank_reconciliation')


@login_required
def pdc_manual_allocation(request, line_id):
    """
    Manual allocation screen for allocating one bank line to multiple PDCs.
    Required when ambiguous matches exist.
    """
    from apps.finance.models import BankStatementLine
    
    bank_line = get_object_or_404(BankStatementLine, pk=line_id)
    potential_pdcs = find_pdc_matches(bank_line, date_tolerance=30)  # Wider tolerance for manual
    
    # Calculate the line amount (credit for deposits, debit for withdrawals)
    line_amount = bank_line.credit if bank_line.credit > 0 else bank_line.debit
    
    if request.method == 'POST':
        allocation_data = json.loads(request.POST.get('allocation_data', '[]'))
        reason = request.POST.get('reason', '')
        
        if not allocation_data:
            messages.error(request, 'No allocation data provided.')
            return redirect('property:pdc_manual_allocation', line_id=line_id)
        
        total_allocated = sum(Decimal(str(item['amount'])) for item in allocation_data)
        
        if total_allocated != line_amount:
            messages.error(
                request,
                f'Total allocated ({total_allocated}) must equal bank line amount ({line_amount})'
            )
            return redirect('property:pdc_manual_allocation', line_id=line_id)
        
        try:
            with transaction.atomic():
                # Create allocation
                allocation = PDCAllocation.objects.create(
                    bank_statement_line=bank_line,
                    allocation_date=date.today(),
                    total_amount=line_amount,
                    allocated_by=request.user,
                    reason=reason
                )
                
                # Create allocation lines
                for item in allocation_data:
                    pdc = get_object_or_404(PDCCheque, pk=item['pdc_id'])
                    PDCAllocationLine.objects.create(
                        allocation=allocation,
                        pdc=pdc,
                        amount=Decimal(str(item['amount'])),
                        notes=item.get('notes', '')
                    )
                
                # Confirm allocation (marks PDCs as reconciled)
                allocation.confirm(request.user)
                
                # Resolve ambiguous match log
                AmbiguousMatchLog.objects.filter(
                    bank_statement_line=bank_line
                ).update(
                    resolution_status='allocated',
                    resolved_at=timezone.now(),
                    resolved_by=request.user,
                    allocation=allocation
                )
                
                messages.success(request, f'Manual allocation {allocation.allocation_number} confirmed successfully.')
                return redirect('property:pdc_bank_reconciliation')
        
        except Exception as e:
            messages.error(request, f'Error creating allocation: {str(e)}')
    
    context = {
        'bank_line': bank_line,
        'potential_pdcs': potential_pdcs,
        'total_to_allocate': line_amount,
    }
    
    return render(request, 'property/pdc_manual_allocation.html', context)


# =============================================================================
# PDC Reports
# =============================================================================

@login_required
def pdc_register_report(request):
    """PDC Register Report - Tenant-wise."""
    tenant_id = request.GET.get('tenant', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    pdcs = PDCCheque.objects.filter(is_active=True).select_related('tenant', 'lease', 'deposited_to_bank')
    
    if tenant_id:
        pdcs = pdcs.filter(tenant_id=tenant_id)
    if status:
        pdcs = pdcs.filter(status=status)
    if date_from:
        pdcs = pdcs.filter(cheque_date__gte=date_from)
    if date_to:
        pdcs = pdcs.filter(cheque_date__lte=date_to)
    
    # Group by tenant
    tenant_data = {}
    for pdc in pdcs.order_by('tenant__name', 'cheque_date'):
        tenant_name = pdc.tenant.name
        if tenant_name not in tenant_data:
            tenant_data[tenant_name] = {
                'tenant': pdc.tenant,
                'pdcs': [],
                'total_amount': Decimal('0.00'),
                'cleared_amount': Decimal('0.00'),
                'pending_amount': Decimal('0.00'),
            }
        tenant_data[tenant_name]['pdcs'].append(pdc)
        tenant_data[tenant_name]['total_amount'] += pdc.amount
        if pdc.status == 'cleared':
            tenant_data[tenant_name]['cleared_amount'] += pdc.amount
        elif pdc.status in ['received', 'deposited']:
            tenant_data[tenant_name]['pending_amount'] += pdc.amount
    
    context = {
        'tenant_data': tenant_data,
        'tenants': Tenant.objects.filter(is_active=True),
        'status_choices': PDCCheque.STATUS_CHOICES,
        'filters': {
            'tenant': tenant_id,
            'status': status,
            'date_from': date_from,
            'date_to': date_to,
        }
    }
    
    return render(request, 'property/reports/pdc_register.html', context)


@login_required
def pdc_outstanding_report(request):
    """PDC Outstanding vs Cleared Report."""
    # Get outstanding PDCs (not cleared/bounced)
    outstanding = PDCCheque.objects.filter(
        is_active=True,
        status__in=['received', 'deposited']
    ).select_related('tenant', 'lease')
    
    # Group by month
    monthly_data = {}
    for pdc in outstanding.order_by('cheque_date'):
        month_key = pdc.cheque_date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                'month': pdc.cheque_date.strftime('%B %Y'),
                'received': Decimal('0.00'),
                'deposited': Decimal('0.00'),
                'count': 0
            }
        monthly_data[month_key]['count'] += 1
        if pdc.status == 'received':
            monthly_data[month_key]['received'] += pdc.amount
        else:
            monthly_data[month_key]['deposited'] += pdc.amount
    
    # Summary
    summary = {
        'total_outstanding': outstanding.aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'total_received': outstanding.filter(status='received').aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'total_deposited': outstanding.filter(status='deposited').aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'total_count': outstanding.count(),
    }
    
    # Cleared summary
    cleared = PDCCheque.objects.filter(is_active=True, status='cleared')
    summary['total_cleared'] = cleared.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    summary['cleared_count'] = cleared.count()
    
    context = {
        'monthly_data': monthly_data,
        'summary': summary,
        'outstanding_pdcs': outstanding[:50],  # Show first 50
    }
    
    return render(request, 'property/reports/pdc_outstanding.html', context)


@login_required
def bank_reconciliation_exceptions_report(request):
    """Bank Reconciliation Exceptions Report."""
    # Ambiguous matches
    ambiguous = AmbiguousMatchLog.objects.filter(
        resolution_status='pending',
        is_active=True
    ).select_related('bank_statement_line')
    
    # Unmatched bank lines with PDC deposits
    from apps.finance.models import BankStatementLine
    unmatched_lines = BankStatementLine.objects.filter(
        reconciliation_status='unmatched',
        credit__gt=0  # Credits (deposits)
    ).select_related('statement', 'statement__bank_account')[:50]
    
    # PDCs deposited but not reconciled for > 7 days
    seven_days_ago = date.today() - timedelta(days=7)
    stale_pdcs = PDCCheque.objects.filter(
        is_active=True,
        status='deposited',
        deposit_status='in_clearing',
        deposited_date__lt=seven_days_ago
    ).select_related('tenant')
    
    context = {
        'ambiguous_matches': ambiguous,
        'unmatched_lines': unmatched_lines,
        'stale_pdcs': stale_pdcs,
        'ambiguous_count': ambiguous.count(),
        'unmatched_count': unmatched_lines.count(),
        'stale_count': stale_pdcs.count(),
    }
    
    return render(request, 'property/reports/reconciliation_exceptions.html', context)


@login_required
def ambiguous_match_log_report(request):
    """Ambiguous Match Log Report."""
    status = request.GET.get('status', '')
    
    logs = AmbiguousMatchLog.objects.filter(is_active=True).select_related(
        'bank_statement_line', 'resolved_by', 'allocation'
    )
    
    if status:
        logs = logs.filter(resolution_status=status)
    
    context = {
        'logs': logs.order_by('-detected_at'),
        'status_choices': AmbiguousMatchLog.RESOLUTION_CHOICES,
        'selected_status': status,
    }
    
    return render(request, 'property/reports/ambiguous_match_log.html', context)


@login_required
def tenant_ledger_report(request, tenant_id):
    """Tenant Ledger with Cheque-level drill-down."""
    tenant = get_object_or_404(Tenant, pk=tenant_id, is_active=True)
    
    # Get all PDCs for this tenant
    pdcs = PDCCheque.objects.filter(
        tenant=tenant,
        is_active=True
    ).order_by('cheque_date')
    
    # Get all journal entries for tenant AR account
    journal_entries = []
    if tenant.ar_account:
        from apps.finance.models import JournalEntryLine
        journal_entries = JournalEntryLine.objects.filter(
            account=tenant.ar_account,
            journal_entry__status='posted'
        ).select_related('journal_entry').order_by('journal_entry__date')
    
    # Calculate running balance
    running_balance = Decimal('0.00')
    ledger_entries = []
    for entry in journal_entries:
        running_balance += entry.debit - entry.credit
        ledger_entries.append({
            'date': entry.journal_entry.date,
            'reference': entry.journal_entry.reference,
            'description': entry.description,
            'debit': entry.debit,
            'credit': entry.credit,
            'balance': running_balance,
            'journal_pk': entry.journal_entry.pk,
        })
    
    context = {
        'tenant': tenant,
        'pdcs': pdcs,
        'ledger_entries': ledger_entries,
        'current_balance': running_balance,
        'pdc_summary': {
            'total': pdcs.count(),
            'received': pdcs.filter(status='received').count(),
            'deposited': pdcs.filter(status='deposited').count(),
            'cleared': pdcs.filter(status='cleared').count(),
            'bounced': pdcs.filter(status='bounced').count(),
        }
    }
    
    return render(request, 'property/reports/tenant_ledger.html', context)


# =============================================================================
# API Endpoints
# =============================================================================

@login_required
def api_pdc_search(request):
    """API endpoint for PDC search (used in allocation screen)."""
    query = request.GET.get('q', '')
    bank_id = request.GET.get('bank', '')
    
    pdcs = PDCCheque.objects.filter(
        is_active=True,
        status='deposited',
        deposit_status='in_clearing'
    ).select_related('tenant')
    
    if query:
        pdcs = pdcs.filter(
            Q(cheque_number__icontains=query) |
            Q(tenant__name__icontains=query) |
            Q(pdc_number__icontains=query)
        )
    
    if bank_id:
        pdcs = pdcs.filter(deposited_to_bank_id=bank_id)
    
    results = [{
        'id': pdc.pk,
        'pdc_number': pdc.pdc_number,
        'cheque_number': pdc.cheque_number,
        'amount': str(pdc.amount),
        'cheque_date': str(pdc.cheque_date),
        'tenant_name': pdc.tenant.name,
        'bank_name': pdc.bank_name,
    } for pdc in pdcs[:20]]
    
    return JsonResponse({'results': results})


@login_required
def api_validate_pdc_uniqueness(request):
    """API endpoint to validate PDC uniqueness before saving."""
    cheque_number = request.GET.get('cheque_number', '')
    bank_name = request.GET.get('bank_name', '')
    cheque_date = request.GET.get('cheque_date', '')
    amount = request.GET.get('amount', '')
    tenant_id = request.GET.get('tenant_id', '')
    pdc_id = request.GET.get('pdc_id', '')  # For edit mode
    
    if not all([cheque_number, bank_name, cheque_date, amount, tenant_id]):
        return JsonResponse({'valid': True, 'message': 'Incomplete data'})
    
    existing = PDCCheque.objects.filter(
        cheque_number=cheque_number,
        bank_name=bank_name,
        cheque_date=cheque_date,
        amount=amount,
        tenant_id=tenant_id,
        is_active=True
    )
    
    if pdc_id:
        existing = existing.exclude(pk=pdc_id)
    
    if existing.exists():
        return JsonResponse({
            'valid': False,
            'message': 'A PDC with the same cheque number, bank, date, amount, and tenant already exists.'
        })
    
    # Check if same cheque exists for different tenant (allowed but warn)
    similar = PDCCheque.objects.filter(
        cheque_number=cheque_number,
        bank_name=bank_name,
        amount=amount,
        is_active=True
    ).exclude(tenant_id=tenant_id)
    
    if similar.exists():
        tenant_names = ', '.join([p.tenant.name for p in similar[:3]])
        return JsonResponse({
            'valid': True,
            'warning': f'Similar cheque exists for other tenants: {tenant_names}'
        })
    
    return JsonResponse({'valid': True})

