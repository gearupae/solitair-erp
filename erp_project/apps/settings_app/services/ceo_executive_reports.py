"""CEO executive report sections — read-only aggregation from live ERP modules."""
from __future__ import annotations

from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.contracts.models import Contract, ContractType
from apps.crm.lead_dashboard import (
    base_leads_queryset,
    infer_lead_source,
)
from apps.crm.models import CrmLeadKanbanStage, Customer
from apps.finance.models import Account, AccountType, BankAccount, Budget, Payment
from apps.hr.models import Employee
from apps.hr.models_extended import EmployeeCommission
from apps.inventory.models import ConsumableRequest
from apps.projects.models import Inspection, Project
from apps.purchase.models import PurchaseOrder, PurchaseRequest, VendorBill
from apps.purchase.pr_approval_rules import get_configured_pr_approver
from apps.sales.estimate_dashboard import infer_lost_reason
from apps.sales.models import Estimate, Invoice
from apps.settings_app.models import ApprovalConfiguration, AuditLog
from apps.support.models import SupportTicket, SupportTicketKanbanStage

from .ceo_metrics import (
    MONTH_FIELDS,
    ZERO,
    _ar_aging_buckets,
    _invoice_balance_qs,
    _money,
    _month_expense,
    _payables_due_week,
    _profit_for_month,
    _revenue_target_month,
    _revenue_target_mtd,
    build_collection_candidates,
)

INVOICE_OPEN = ('posted', 'sent', 'paid', 'partial', 'overdue')
PAYMENT_CONFIRMED = ('confirmed', 'reconciled')
WON_STATUSES = ('quotation_won',)
QUOTATION_STATUSES = ('sent', 'approved', 'under_negotiation', 'quotation_won', 'quotation_lost')
OPEN_PROJECT = ('planning', 'ongoing', 'on_hold', 'ongoing_payment_received')
COMPLETED_PROJECT = ('completed', 'completed_payment_pending')


@dataclass
class CeoFilters:
    period: str
    date_from: date
    date_to: date
    service_line: str
    department: str
    salesperson_id: int | None
    client_type: str
    project_status: str
    approval_status: str

    @property
    def period_label(self) -> str:
        if self.period == 'today':
            return 'Today'
        if self.period == 'week':
            return 'This week'
        if self.period == 'month':
            return 'This month'
        if self.period == 'quarter':
            return 'This quarter'
        return f'{self.date_from:%d %b %Y} – {self.date_to:%d %b %Y}'


def parse_ceo_filters(request) -> CeoFilters:
    today = timezone.localdate()
    period = (request.GET.get('period') or 'month').strip().lower()
    if period == 'today':
        date_from, date_to = today, today
    elif period == 'week':
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif period == 'quarter':
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        date_from = date(today.year, q_start_month, 1)
        date_to = today
    elif period == 'custom':
        try:
            date_from = date.fromisoformat((request.GET.get('date_from') or '').strip())
        except ValueError:
            date_from = today.replace(day=1)
        try:
            date_to = date.fromisoformat((request.GET.get('date_to') or '').strip())
        except ValueError:
            date_to = today
        if date_to < date_from:
            date_from, date_to = date_to, date_from
    else:
        period = 'month'
        date_from = today.replace(day=1)
        date_to = today

    sp_raw = (request.GET.get('salesperson') or '').strip()
    salesperson_id = int(sp_raw) if sp_raw.isdigit() else None

    return CeoFilters(
        period=period,
        date_from=date_from,
        date_to=date_to,
        service_line=(request.GET.get('service_line') or 'all').strip().lower(),
        department=(request.GET.get('department') or 'all').strip().lower(),
        salesperson_id=salesperson_id,
        client_type=(request.GET.get('client_type') or 'all').strip().lower(),
        project_status=(request.GET.get('project_status') or 'all').strip().lower(),
        approval_status=(request.GET.get('approval_status') or 'all').strip().lower(),
    )


def _filter_choices(user) -> dict:
    salespeople = Employee.objects.filter(
        is_active=True,
        status='active',
    ).order_by('first_name', 'last_name', 'employee_code')
    return {
        'salespeople': salespeople,
        'periods': [
            ('today', 'Today'),
            ('week', 'This week'),
            ('month', 'This month'),
            ('quarter', 'This quarter'),
            ('custom', 'Custom range'),
        ],
        'service_lines': [
            ('all', 'All service lines'),
            ('fire', 'Fire Protection'),
            ('amc', 'AMC & Maintenance'),
            ('decor', 'Décor'),
            ('gas', 'Central Gas'),
            ('cctv', 'CCTV'),
        ],
        'departments': [
            ('all', 'All departments'),
            ('sales', 'Sales'),
            ('operations', 'Operations'),
            ('accounts', 'Accounts'),
            ('procurement', 'Procurement'),
            ('amc', 'AMC'),
        ],
        'client_types': [
            ('all', 'All client types'),
            ('new', 'New'),
            ('existing', 'Existing'),
            ('amc', 'AMC'),
            ('prime', 'Prime account'),
        ],
        'project_statuses': [
            ('all', 'All statuses'),
            ('open', 'Open'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('billed', 'Billed'),
            ('collected', 'Collected'),
        ],
        'approval_statuses': [
            ('all', 'All'),
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('clarification', 'Need clarification'),
        ],
    }


DEPT_KEYWORDS = {
    'sales': ('sales', 'business'),
    'operations': ('operation', 'project', 'technical', 'engineer'),
    'accounts': ('account', 'finance'),
    'procurement': ('procure', 'purchase'),
    'amc': ('amc', 'maintenance', 'service'),
}


def _dept_employee_ids(department: str) -> list[int] | None:
    if department == 'all':
        return None
    keywords = DEPT_KEYWORDS.get(department, (department,))
    q = Q()
    for kw in keywords:
        q |= Q(department__name__icontains=kw)
    return list(Employee.objects.filter(is_active=True, status='active').filter(q).values_list('pk', flat=True))


def _apply_department_to_employee_ids(department: str, ids: list[int] | None) -> list[int] | None:
    dept_ids = _dept_employee_ids(department)
    if dept_ids is None:
        return ids
    if ids is None:
        return dept_ids
    return [i for i in ids if i in dept_ids]


def _apply_salesperson_filter(salesperson_id: int | None, department: str) -> list[int] | None:
    if salesperson_id:
        return _apply_department_to_employee_ids(department, [salesperson_id])
    return _dept_employee_ids(department)


def _apply_service_line_to_projects(qs, service_line: str):
    if service_line == 'all':
        return qs
    if service_line == 'fire':
        return qs.filter(category='fire')
    if service_line == 'gas':
        return qs.filter(category='gas')
    if service_line == 'cctv':
        return qs.filter(category='cctv')
    if service_line == 'amc':
        return qs.filter(sub_category__in=('amc', 'maintenance', 'maintenance_with_amc'))
    if service_line == 'decor':
        return qs.filter(sub_category__in=('decor', 'decor_with_amc'))
    return qs


def _apply_service_line_to_estimates(qs, service_line: str):
    if service_line == 'all':
        return qs
    mapping = {
        'fire': Q(type_of_work__icontains='installation') | Q(scope='project'),
        'amc': Q(scope='amc') | Q(type_of_work='amc') | Q(type_of_work='maintenance'),
        'decor': Q(scope='fitout') | Q(scope='amc_fitout'),
        'gas': Q(scope='project'),
        'cctv': Q(scope='project'),
    }
    flt = mapping.get(service_line)
    return qs.filter(flt) if flt else qs


def _apply_client_type(qs, client_type: str, *, lead_mode: bool = False):
    if client_type == 'all':
        return qs
    if client_type == 'new':
        if lead_mode:
            return qs.filter(customer_type='lead')
        cutoff = timezone.now() - timedelta(days=90)
        return qs.filter(created_at__gte=cutoff)
    if client_type == 'existing':
        if lead_mode:
            return qs.filter(customer_type='customer')
        cutoff = timezone.now() - timedelta(days=90)
        return qs.filter(created_at__lt=cutoff)
    if client_type == 'amc':
        return qs.filter(Q(scope__icontains='amc') | Q(sub_category__icontains='amc'))
    if client_type == 'prime':
        return qs.filter(credit_limit__gte=Decimal('50000'))
    return qs


def _apply_salesperson_to_estimates(qs, salesperson_id: int | None):
    if not salesperson_id:
        return qs
    return qs.filter(sales_engineer_id=salesperson_id)


def _apply_salesperson_to_leads(qs, salesperson_id: int | None):
    if not salesperson_id:
        return qs
    return qs.filter(assigned_salesperson_id=salesperson_id)


def _amc_contracts_qs():
    amc_types = ContractType.objects.filter(
        Q(name__icontains='amc') | Q(slug__icontains='amc'),
        is_active=True,
    )
    return Contract.objects.filter(is_active=True, contract_types__in=amc_types).distinct()


def _payments_in_period(date_from: date, date_to: date):
    return Payment.objects.filter(
        is_active=True,
        status__in=PAYMENT_CONFIRMED,
        payment_date__gte=date_from,
        payment_date__lte=date_to,
    )


def _budget_expense_month(year: int, month: int) -> Decimal:
    month_start = date(year, month, 1)
    field = MONTH_FIELDS[month - 1]
    budget = (
        Budget.objects.filter(
            is_active=True,
            status__in=('approved', 'locked'),
            fiscal_year__start_date__lte=month_start,
            fiscal_year__end_date__gte=month_start,
        )
        .order_by('-approved_date', '-id')
        .first()
    )
    target = ZERO
    if budget:
        lines = budget.lines.filter(
            Q(account__account_type=AccountType.EXPENSE)
            | Q(account__account_category__in=(
                'cost_of_sales', 'rent_expense', 'salary_expense', 'banking_expense',
                'bad_debts', 'depreciation_expense', 'utilities', 'project_costs',
                'marketing', 'admin_expense', 'other_expense',
            )),
        )
        for line in lines:
            monthly = _money(getattr(line, field, ZERO))
            if monthly <= ZERO and line.amount > ZERO:
                monthly = _money(line.amount / Decimal('12'))
            target += monthly
    return target


def _cash_reserve_balance() -> float:
    reserve = _money(
        Account.objects.filter(
            is_active=True,
            account_category='reserves',
        ).aggregate(t=Sum('balance'))['t']
    )
    if reserve:
        return float(reserve)
    return float(_money(
        Account.objects.filter(
            is_active=True,
            account_type=AccountType.EQUITY,
            name__icontains='reserve',
        ).aggregate(t=Sum('balance'))['t']
    ))


def _estimate_first_sent_at(estimate_id: int):
    return (
        AuditLog.objects.filter(model='Estimate', record_id=str(estimate_id))
        .filter(
            Q(changes__field='status', changes__to='sent')
            | Q(changes__to='sent')
            | Q(changes__to_display__icontains='sent')
        )
        .order_by('timestamp')
        .values_list('timestamp', flat=True)
        .first()
    )


def _quote_48h_stats(est_qs) -> tuple[float, int, int]:
    sent_statuses = ('sent', 'approved', 'under_negotiation', 'quotation_won', 'quotation_lost')
    rows = list(est_qs.filter(status__in=sent_statuses).values_list('pk', 'date', 'created_at')[:500])
    if not rows:
        return 0.0, 0, 0
    fast = 0
    for pk, est_date, created in rows:
        sent_at = _estimate_first_sent_at(pk)
        ref = created
        if sent_at and ref:
            if (sent_at - ref).total_seconds() <= 172800:
                fast += 1
        elif est_date and sent_at is None:
            fast += 1
    total = len(rows)
    pct = round(fast / total * 100, 1) if total else 0.0
    return pct, fast, total


def _site_visit_stats(filters: CeoFilters, site_stage) -> tuple[int, int]:
    if not site_stage:
        return 0, 0
    slug = site_stage.slug
    moved_in = AuditLog.objects.filter(
        model='Customer',
        timestamp__date__gte=filters.date_from,
        timestamp__date__lte=filters.date_to,
        changes__lead_kanban_stage=slug,
    ).values_list('record_id', flat=True)
    scheduled_ids = {int(r) for r in moved_in if str(r).isdigit()}
    scheduled = len(scheduled_ids)
    completed = 0
    if scheduled_ids:
        completed = (
            Customer.objects.filter(pk__in=scheduled_ids, is_active=True)
            .exclude(lead_kanban_stage=site_stage)
            .count()
        )
    return scheduled, completed


def _collections_for_salesperson(emp_id: int, date_from: date, date_to: date) -> float:
    customer_ids = list(
        Estimate.objects.filter(
            is_active=True,
            sales_engineer_id=emp_id,
            status='quotation_won',
        ).values_list('customer_id', flat=True).distinct()
    )
    customer_ids = [c for c in customer_ids if c]
    if not customer_ids:
        return 0.0
    return float(_money(
        _payments_in_period(date_from, date_to)
        .filter(payment_type='received', party_type='customer', party_id__in=customer_ids)
        .aggregate(t=Sum('amount'))['t']
    ))


def _amc_payments_in_period(amc_customer_ids, date_from: date, date_to: date) -> float:
    ids = [c for c in amc_customer_ids if c]
    if not ids:
        return 0.0
    return float(_money(
        _payments_in_period(date_from, date_to)
        .filter(payment_type='received', party_type='customer', party_id__in=ids)
        .aggregate(t=Sum('amount'))['t']
    ))


def _pr_above_approval_limit(pr) -> str:
    config = ApprovalConfiguration.objects.filter(module='purchase_request', is_active=True).first()
    if not config or config.approval_type != 'multi':
        return 'No'
    top = config.levels.filter(is_active=True).order_by('-amount_threshold').first()
    if top and (pr.total_amount or ZERO) > top.amount_threshold:
        return 'Yes'
    return 'No'


def _build_summary_cards(filters: CeoFilters, user) -> list[dict]:
    from .ceo_finance_summary import build_finance_summary_cards

    today = filters.date_to
    fin = build_finance_summary_cards(filters.date_from, filters.date_to, period=filters.period)

    amc_qs = _amc_contracts_qs()
    active_amc = amc_qs.filter(status='active', start_date__lte=today, end_date__gte=today).count()
    new_amc = amc_qs.filter(created_at__date__gte=filters.date_from, created_at__date__lte=filters.date_to).count()
    expired_amc = amc_qs.filter(status='expired').count()
    renewed_amc = amc_qs.filter(
        status='active',
        start_date__gte=filters.date_from,
        start_date__lte=filters.date_to,
    ).exclude(created_at__date=F('start_date')).count()

    proj_qs = _apply_service_line_to_projects(
        Project.objects.filter(is_active=True), filters.service_line,
    )
    active_projects = proj_qs.filter(status__in=OPEN_PROJECT)
    progress_vals = [p.task_progress_percent for p in active_projects.only('pk')[:500]]
    work_completion = round(sum(progress_vals) / len(progress_vals), 1) if progress_vals else None

    inspections = Inspection.objects.filter(
        is_active=True,
        inspection_date__gte=filters.date_from,
        inspection_date__lte=filters.date_to,
    )
    insp_total = inspections.count()
    insp_done = inspections.filter(checklist_items__isnull=False).distinct().count()

    pending = _pending_ceo_approvals(filters)
    pending_count = pending['count']
    pending_value = pending['value']

    def card(label, value, *, fmt='money', hint='', alert=False):
        empty = value is None
        display = value
        if not empty and fmt == 'money':
            display = float(value)
        elif not empty and fmt == 'pct':
            display = value
        elif not empty and fmt == 'int':
            display = int(value)
        return {
            'label': label,
            'value': display,
            'format': fmt,
            'hint': hint,
            'alert': alert,
            'empty': empty,
        }

    gap_alert = fin['revenue_gap'] is not None and fin['revenue_gap'] > ZERO
    overdue_alert = fin['overdue_receivables'] is not None and fin['overdue_receivables'] > ZERO

    return [
        card('Revenue target', fin['rev_target'], hint=fin['rev_target_hint']),
        card('Revenue achieved', fin['revenue_achieved'], hint=fin['revenue_achieved_hint']),
        card('Revenue gap', fin['revenue_gap'], hint='Budget target − GL revenue', alert=gap_alert),
        card('Collection target', fin['invoiced'], hint=fin['collection_target_hint']),
        card('Collection achieved', fin['collected'], hint=fin['collection_achieved_hint']),
        card('Cash inflow', fin['collected'], hint=fin['cash_hint']),
        card('Cash outflow', fin['paid_out'], hint=fin['cash_hint']),
        card('Net cash position', fin['net_cash'], hint='Inflow − outflow (Finance payments)'),
        card('Gross profit %', fin['gross_profit_pct'], fmt='pct', hint=fin['gross_hint']),
        card('Net profit %', fin['net_profit_pct'], fmt='pct', hint=fin['net_hint']),
        card('Active AMC', active_amc, fmt='int'),
        card('New AMC', new_amc, fmt='int'),
        card('AMC renewals', renewed_amc, fmt='int', hint='Contracts re-started in period'),
        card('Expired AMC', expired_amc, fmt='int', alert=expired_amc > 0),
        card('Work completion %', work_completion, fmt='pct', hint='Avg task progress on active projects' if work_completion is not None else 'No active projects'),
        card(
            'Inspections',
            insp_done if insp_total else 0,
            fmt='int',
            hint=f'{insp_done} / {insp_total} with checklist' if insp_total else 'No inspections in period',
        ),
        card('Overdue receivables', fin['overdue_receivables'], hint=fin['overdue_hint'], alert=overdue_alert),
        card(
            'Pending CEO approvals',
            pending_count,
            fmt='int',
            hint=f'AED {float(pending_value):,.0f} total value' if pending_value else 'Awaiting sign-off',
        ),
    ]


def _pending_ceo_approvals(filters: CeoFilters) -> dict:
    count = 0
    value = ZERO
    prs = PurchaseRequest.objects.filter(is_active=True, status='pending')
    if filters.approval_status in ('all', 'pending'):
        count += prs.count()
        value += _money(prs.aggregate(t=Sum('total_amount'))['t'])

    est = Estimate.objects.filter(is_active=True, edit_approval_status='pending')
    count += est.count()
    value += _money(est.aggregate(t=Sum('total_amount'))['t'])

    proj_conv = Project.objects.filter(is_active=True, conversion_approval_status='pending', status='draft')
    count += proj_conv.count()
    value += _money(proj_conv.aggregate(t=Coalesce(Sum('contract_value'), Sum('budget'), ZERO))['t'])

    proj_comp = Project.objects.filter(is_active=True, edit_approval_status='pending')
    count += proj_comp.count()

    consumables = ConsumableRequest.objects.filter(is_active=True, status='pending')
    count += consumables.count()
    value += _money(consumables.aggregate(t=Sum('total_cost'))['t'])

    return {'count': count, 'value': float(value)}


def _build_sales_section(filters: CeoFilters, user) -> dict:
    sp_ids = _apply_salesperson_filter(filters.salesperson_id, filters.department)

    leads = base_leads_queryset(user)
    leads = leads.filter(created_at__date__gte=filters.date_from, created_at__date__lte=filters.date_to)
    if sp_ids is not None:
        leads = leads.filter(assigned_salesperson_id__in=sp_ids)
    elif filters.salesperson_id:
        leads = _apply_salesperson_to_leads(leads, filters.salesperson_id)
    leads = _apply_client_type(leads, filters.client_type, lead_mode=True)

    leads_received = leads.count()
    contacted_qs = leads.filter(
        Q(notes__gt='') | Q(lead_kanban_stage__isnull=False)
    ).distinct()
    leads_contacted = contacted_qs.count()

    fast_contact = 0
    for lead_id, created in leads.values_list('pk', 'created_at')[:500]:
        first_touch = AuditLog.objects.filter(
            model='Customer',
            record_id=str(lead_id),
        ).exclude(action='create').order_by('timestamp').values_list('timestamp', flat=True).first()
        if first_touch and created and (first_touch - created).total_seconds() <= 900:
            fast_contact += 1
    sla_pct = round(fast_contact / leads_received * 100, 1) if leads_received else 0.0

    qualified = leads.exclude(lead_kanban_stage__isnull=True).exclude(
        lead_kanban_stage__slug='lost',
    ).count()

    site_stage = CrmLeadKanbanStage.objects.filter(is_active=True, is_site_visit=True).first()
    site_visits_scheduled, site_visits_completed = _site_visit_stats(filters, site_stage)
    site_visits_current = leads.filter(lead_kanban_stage=site_stage).count() if site_stage else 0

    est_qs = Estimate.objects.filter(is_active=True, date__gte=filters.date_from, date__lte=filters.date_to)
    est_qs = _apply_service_line_to_estimates(est_qs, filters.service_line)
    if sp_ids is not None:
        est_qs = est_qs.filter(sales_engineer_id__in=sp_ids)
    else:
        est_qs = _apply_salesperson_to_estimates(est_qs, filters.salesperson_id)

    quotations = est_qs.filter(status__in=QUOTATION_STATUSES)
    quotations_count = quotations.count()
    quotations_value = float(_money(quotations.aggregate(t=Sum('total_amount'))['t']))

    quote_48_pct, quote_48_fast, quote_48_total = _quote_48h_stats(est_qs)

    orders = est_qs.filter(status='quotation_won')
    orders_count = orders.count()
    orders_value = float(_money(orders.aggregate(t=Sum('total_amount'))['t']))
    conversion_pct = round(orders_count / quotations_count * 100, 1) if quotations_count else 0.0

    lost = est_qs.filter(status='quotation_lost')
    lost_count = lost.count()
    lost_value = float(_money(lost.aggregate(t=Sum('total_amount'))['t']))
    lost_reasons = Counter()
    for e in lost.only('rejection_reason', 'notes')[:200]:
        lost_reasons[infer_lost_reason(e.rejection_reason or e.notes)] += 1

    today = filters.date_to
    followups_due = Estimate.objects.filter(
        is_active=True,
        status__in=('sent', 'approved', 'under_negotiation'),
        valid_until=today,
    ).count()
    followups_missed = Estimate.objects.filter(
        is_active=True,
        status__in=('sent', 'approved', 'under_negotiation'),
        valid_until__lt=today,
    ).count()

    top_pending = (
        Estimate.objects.filter(
            is_active=True,
            status__in=('sent', 'approved', 'under_negotiation'),
        )
        .select_related('customer', 'sales_engineer', 'assigned_to')
        .order_by('-total_amount')[:10]
    )
    pending_deals = []
    for e in top_pending:
        owner = ''
        if e.sales_engineer_id:
            owner = str(e.sales_engineer)
        elif e.assigned_to_id:
            owner = e.assigned_to.get_full_name() or e.assigned_to.username
        pending_deals.append({
            'client': e.customer.display_name if e.customer_id else '—',
            'value': float(_money(e.total_amount)),
            'stage': e.get_status_display(),
            'blocker': (e.rejection_reason or e.notes or '')[:80] or '—',
            'owner': owner or '—',
        })

    source_rows = Counter()
    for lead in leads[:500]:
        source_rows[infer_lead_source(lead)] += 1

    metrics = [
        ('Leads received', leads_received, 'int', 'Count by created date'),
        ('Leads contacted', leads_contacted, 'int', 'Notes or pipeline stage assigned'),
        ('Contacted ≤ 15 min', f'{sla_pct}%', 'text', f'{fast_contact} of {leads_received}'),
        ('Leads qualified', qualified, 'int', 'In pipeline excluding lost'),
        ('Site visits scheduled', site_visits_scheduled, 'int', 'Moved to site-visit stage'),
        ('Site visits completed', site_visits_completed, 'int', f'{site_visits_current} currently in stage'),
        ('Quotations issued', quotations_count, 'int', ''),
        ('Quotation value', quotations_value, 'money', ''),
        ('Quotes ≤ 48h %', f'{quote_48_pct}%', 'text', f'{quote_48_fast} of {quote_48_total} sent'),
        ('Orders closed', orders_count, 'int', 'Quot Won'),
        ('Order value', orders_value, 'money', ''),
        ('Conversion %', f'{conversion_pct}%', 'text', 'Orders / quotations'),
        ('Lost deals', f'{lost_count} (AED {lost_value:,.0f})', 'text', ''),
        ('Follow-ups due today', followups_due, 'int', 'Valid until today'),
        ('Follow-ups missed', followups_missed, 'int', 'Past valid-until date'),
    ]

    return {
        'metrics': metrics,
        'lost_reasons': [{'label': k, 'count': v} for k, v in lost_reasons.most_common(8)],
        'lead_sources': [{'label': k, 'count': v} for k, v in source_rows.most_common(8)],
        'top_pending_deals': pending_deals,
    }


def _build_salesperson_section(filters: CeoFilters, user) -> list[dict]:
    sp_ids = _apply_salesperson_filter(filters.salesperson_id, filters.department)
    employees = Employee.objects.filter(is_active=True, status='active').select_related('department')
    if sp_ids is not None:
        employees = employees.filter(pk__in=sp_ids)
    employees = employees.order_by('first_name')

    month_start = filters.date_to.replace(day=1)
    rows = []
    emp_count = max(employees.count(), 1)
    company_target = float(_revenue_target_month(filters.date_to.year, filters.date_to.month))

    for emp in employees[:40]:
        est_qs = Estimate.objects.filter(
            is_active=True,
            sales_engineer=emp,
            date__gte=filters.date_from,
            date__lte=filters.date_to,
        )
        leads = Customer.objects.filter(
            is_active=True,
            customer_type='lead',
            assigned_salesperson=emp,
            created_at__date__gte=filters.date_from,
            created_at__date__lte=filters.date_to,
        ).count()
        quotes = est_qs.filter(status__in=QUOTATION_STATUSES).count()
        quote_val = float(_money(est_qs.filter(status__in=QUOTATION_STATUSES).aggregate(t=Sum('total_amount'))['t']))
        orders = est_qs.filter(status='quotation_won')
        order_count = orders.count()
        order_val = float(_money(orders.aggregate(t=Sum('total_amount'))['t']))
        target = company_target / emp_count
        achievement = round(order_val / target * 100, 1) if target else 0.0

        amc_new = _amc_contracts_qs().filter(
            customer__assigned_salesperson=emp,
            created_at__date__gte=filters.date_from,
            created_at__date__lte=filters.date_to,
        ).count()
        amc_renewed = _amc_contracts_qs().filter(
            customer__assigned_salesperson=emp,
            status='active',
            start_date__gte=filters.date_from,
            start_date__lte=filters.date_to,
        ).exclude(created_at__date=F('start_date')).count()

        collected = _collections_for_salesperson(emp.pk, filters.date_from, filters.date_to)

        commission = EmployeeCommission.objects.filter(
            is_active=True,
            employee=emp,
            month=month_start,
            status__in=('active', 'paid'),
        ).first()
        incentive_eligible = bool(commission and commission.commission_amount > 0) or (order_val > 0 and achievement >= 80)
        incentive_pending = bool(
            order_count > 0 and collected < order_val * Decimal('0.5')
        )

        crm_leads = Customer.objects.filter(is_active=True, assigned_salesperson=emp, customer_type='lead')
        crm_updated = 'Updated' if crm_leads.filter(
            Q(notes__gt='') | Q(lead_kanban_stage__isnull=False)
        ).exists() else 'Not updated'

        if not (leads or quotes or order_count):
            continue

        rows.append({
            'name': emp.full_name or emp.employee_code,
            'branch': '—',
            'target': target,
            'achieved': order_val,
            'achievement_pct': achievement,
            'leads': leads,
            'quotations': quotes,
            'quotation_value': quote_val,
            'orders': order_count,
            'order_value': order_val,
            'amc_new': amc_new,
            'amc_renewed': amc_renewed,
            'collection': collected,
            'incentive_eligible': incentive_eligible,
            'incentive_pending': incentive_pending,
            'crm_updated': 'Updated' if crm_updated else 'Not updated',
        })
    return rows


def _build_amc_section(filters: CeoFilters) -> dict:
    today = filters.date_to
    amc = _amc_contracts_qs()
    active = amc.filter(status='active', start_date__lte=today, end_date__gte=today)
    new_count = amc.filter(
        created_at__date__gte=filters.date_from,
        created_at__date__lte=filters.date_to,
    ).count()
    renewed = amc.filter(
        status='active',
        start_date__gte=filters.date_from,
        start_date__lte=filters.date_to,
    ).exclude(created_at__date=F('start_date')).count()
    due_30 = active.filter(end_date__lte=today + timedelta(days=30), end_date__gte=today).count()
    due_total = active.filter(end_date__lte=today + timedelta(days=90), end_date__gte=today).count()
    renewal_rate = round(renewed / due_total * 100, 1) if due_total else 0.0

    amc_customer_ids = list(active.values_list('customer_id', flat=True))
    amc_collection = _amc_payments_in_period(amc_customer_ids, filters.date_from, filters.date_to)

    ppm_qs = Inspection.objects.filter(
        is_active=True,
        link_type='amc',
        inspection_date__gte=filters.date_from,
        inspection_date__lte=filters.date_to,
    )
    ppm_planned = ppm_qs.count()
    ppm_completed = ppm_qs.filter(checklist_items__isnull=False).distinct().count()
    ppm_pct = round(ppm_completed / ppm_planned * 100, 1) if ppm_planned else 0.0

    closed_stages = SupportTicketKanbanStage.objects.filter(is_active=True, is_closed=True)
    emergency = SupportTicket.objects.filter(
        is_active=True,
        link_type='amc',
        priority='urgent',
        opened_date__gte=filters.date_from,
        opened_date__lte=filters.date_to,
    ).count()
    complaints = SupportTicket.objects.filter(
        is_active=True,
        link_type='amc',
    ).exclude(kanban_stage__in=closed_stages).count()

    metrics = [
        ('Total active AMC', active.count(), 'int'),
        ('New AMC added', new_count, 'int'),
        ('AMC renewed', renewed, 'int'),
        ('AMC expired', amc.filter(status='expired').count(), 'int'),
        ('Due in 30 days', due_30, 'int'),
        ('Due in 60 days', active.filter(
            end_date__lte=today + timedelta(days=60),
            end_date__gt=today + timedelta(days=30),
        ).count(), 'int'),
        ('Due in 90 days', active.filter(
            end_date__lte=today + timedelta(days=90),
            end_date__gt=today + timedelta(days=60),
        ).count(), 'int'),
        ('AMC lost', amc.filter(status='cancelled').count(), 'int'),
        ('AMC revenue', float(_money(active.aggregate(t=Sum('contract_value'))['t'])), 'money'),
        ('AMC collection', amc_collection, 'money'),
        ('PPM planned', ppm_planned, 'int'),
        ('PPM completed', ppm_completed, 'int'),
        ('PPM completion %', f'{ppm_pct}%', 'text'),
        ('Emergency calls', emergency, 'int'),
        ('AMC complaints (open)', complaints, 'int'),
        ('AMC renewal rate %', f'{renewal_rate}%', 'text'),
    ]
    due_rows = []
    for c in active.filter(end_date__lte=today + timedelta(days=90)).select_related(
        'customer', 'customer__assigned_salesperson',
    ).order_by('end_date')[:20]:
        owner = '—'
        if c.customer_id and c.customer.assigned_salesperson_id:
            owner = str(c.customer.assigned_salesperson)
        due_rows.append({
            'contract': c.contract_number,
            'customer': c.customer.display_name if c.customer_id else '—',
            'value': float(c.contract_value),
            'end_date': c.end_date,
            'days_left': (c.end_date - today).days,
            'owner': owner,
        })
    return {'metrics': metrics, 'due_rows': due_rows}


def _build_operations_section(filters: CeoFilters) -> list[dict]:
    qs = Project.objects.filter(is_active=True).select_related('customer', 'manager').prefetch_related('technicians')
    qs = _apply_service_line_to_projects(qs, filters.service_line)

    if filters.project_status == 'open':
        qs = qs.filter(status__in=('planning', 'draft'))
    elif filters.project_status == 'running':
        qs = qs.filter(status__in=('ongoing', 'ongoing_payment_received', 'on_hold'))
    elif filters.project_status == 'completed':
        qs = qs.filter(status__in=COMPLETED_PROJECT)
    elif filters.project_status == 'billed':
        qs = qs.filter(total_billed__gt=0)
    elif filters.project_status == 'collected':
        qs = qs.filter(total_revenue__gt=0)

    if filters.approval_status == 'pending':
        qs = qs.filter(
            Q(conversion_approval_status='pending') | Q(edit_approval_status='pending'),
        )
    elif filters.approval_status == 'approved':
        qs = qs.filter(conversion_approval_status='none', edit_approval_status='none')
    elif filters.approval_status == 'rejected':
        qs = qs.filter(
            Q(conversion_approval_status='rejected') | Q(edit_approval_status='rejected'),
        )

    qs = qs.filter(
        Q(start_date__lte=filters.date_to) | Q(start_date__isnull=True),
        Q(created_at__date__lte=filters.date_to),
    )

    closed_ticket_stages = SupportTicketKanbanStage.objects.filter(is_active=True, is_closed=True)
    rows = []
    for p in qs.order_by('-created_at')[:40]:
        order_val = float(p.contract_value or p.budget or ZERO)
        completed_pct = float(p.task_progress_percent or 0)
        completed_val = order_val * completed_pct / 100
        pending_val = order_val - completed_val
        billing_eligible = completed_val - float(p.total_billed or 0)
        if billing_eligible < 0:
            billing_eligible = 0
        delayed = p.end_date and p.end_date < filters.date_to and p.status in OPEN_PROJECT
        delay_reason = 'Past deadline' if delayed else ('On hold' if p.status == 'on_hold' else '—')
        if p.edit_approval_status == 'pending':
            delay_reason = 'Awaiting approval'

        supervisor = '—'
        tech = p.technicians.first()
        if tech:
            supervisor = tech.get_full_name() or tech.username

        has_complaint = SupportTicket.objects.filter(
            is_active=True,
            project=p,
        ).exclude(kanban_stage__in=closed_ticket_stages).exists()

        actual_end = None
        if p.status in COMPLETED_PROJECT:
            last_task = p.tasks.filter(is_active=True, status='completed').order_by('-updated_at').first()
            actual_end = last_task.updated_at.date() if last_task else p.updated_at.date()

        rows.append({
            'job_number': p.project_code,
            'project_number': p.project_code,
            'client': p.customer.display_name if p.customer_id else '—',
            'branch': '—',
            'service_line': p.get_category_display() or p.get_sub_category_display() or '—',
            'work_type': p.get_sub_category_display() or 'Project',
            'order_value': order_val,
            'planned_start': p.start_date,
            'planned_end': p.end_date,
            'actual_completion': actual_end,
            'completion_pct': completed_pct,
            'completed_value': completed_val,
            'pending_value': pending_val,
            'billing_eligible': billing_eligible,
            'status': p.get_status_display(),
            'delay_reason': delay_reason,
            'responsible': p.manager.get_full_name() if p.manager_id else '—',
            'supervisor': supervisor,
            'complaint': 'Yes' if has_complaint else 'No',
        })
    return rows


def _build_inspection_section(filters: CeoFilters) -> list[dict]:
    qs = Inspection.objects.filter(
        is_active=True,
        inspection_date__gte=filters.date_from,
        inspection_date__lte=filters.date_to,
    ).select_related('project', 'amc_contract').prefetch_related('checklist_items')

    rows = []
    for insp in qs.order_by('-inspection_date')[:40]:
        items = list(insp.checklist_items.filter(is_active=True))
        total = len(items)
        passed = sum(1 for i in items if not i.is_flagged_red)
        failed = sum(1 for i in items if i.is_flagged_red)
        if not total:
            status = 'Pending'
        elif failed:
            status = 'Failed'
        elif passed == total:
            status = 'Passed'
        else:
            status = 'Completed'

        failed_reasons = [i.text[:40] for i in items if i.is_flagged_red][:3]
        failed_reason = ', '.join(failed_reasons) if failed_reasons else '—'

        cert_pending = 'Yes' if failed else ('No' if status == 'Passed' else '—')
        billing_triggered = 'No'
        if insp.project_id and status == 'Passed':
            billing_triggered = 'Yes' if (insp.project.total_billed or 0) > 0 else 'No'

        rows.append({
            'number': insp.inspection_number,
            'type': insp.get_link_type_display(),
            'target': insp.target_label,
            'planned_date': insp.inspection_date,
            'completed_date': insp.inspection_date if total else None,
            'status': status,
            'pass_pct': round(passed / total * 100, 1) if total else 0,
            'failed_reason': failed_reason,
            'reinspection': 'Yes' if failed else 'No',
            'reinspection_date': '—',
            'certificate_pending': cert_pending,
            'certificate_received': insp.inspection_date if status == 'Passed' and not failed else None,
            'billing_triggered': billing_triggered,
        })
    return rows


def _build_finance_section(filters: CeoFilters) -> dict:
    today = filters.date_to
    inv_qs = Invoice.objects.filter(
        is_active=True,
        invoice_date__gte=filters.date_from,
        invoice_date__lte=filters.date_to,
        status__in=INVOICE_OPEN,
    )
    invoice_value = float(_money(inv_qs.aggregate(t=Sum('total_amount'))['t']))
    collected = float(_money(
        _payments_in_period(filters.date_from, filters.date_to)
        .filter(payment_type='received')
        .aggregate(t=Sum('amount'))['t']
    ))
    paid_out = float(_money(
        _payments_in_period(filters.date_from, filters.date_to)
        .filter(payment_type='made')
        .aggregate(t=Sum('amount'))['t']
    ))
    outstanding = float(_money(_invoice_balance_qs().aggregate(t=Sum(F('total_amount') - F('paid_amount')))['t']))
    aging = _ar_aging_buckets(today)
    bank = float(_money(BankAccount.objects.filter(is_active=True).aggregate(t=Sum('current_balance'))['t']))
    pay_week = _payables_due_week(today)
    profit = _profit_for_month(today.year, today.month)
    budget_exp = float(_budget_expense_month(today.year, today.month))
    actual_exp = float(_month_expense(today.year, today.month))
    gross_rev = float(_money(
        Invoice.objects.filter(
            is_active=True,
            invoice_date__gte=filters.date_from,
            invoice_date__lte=filters.date_to,
            status__in=INVOICE_OPEN,
        ).aggregate(t=Sum('subtotal'))['t']
    ))
    direct_cost = float(_money(
        VendorBill.objects.filter(
            is_active=True,
            bill_date__gte=filters.date_from,
            bill_date__lte=filters.date_to,
            status__in=('posted', 'paid', 'partial', 'overdue', 'pending'),
        ).aggregate(t=Sum('subtotal'))['t']
    ))
    gross_pct = round((gross_rev - direct_cost) / gross_rev * 100, 1) if gross_rev else 0.0

    top_clients = []
    for row in build_collection_candidates(20):
        owner = '—'
        if row.get('customer_id'):
            cust = Customer.objects.filter(pk=row['customer_id']).select_related('assigned_salesperson').first()
            if cust and cust.assigned_salesperson_id:
                owner = str(cust.assigned_salesperson)
        top_clients.append({
            'name': row['name'],
            'amount': row['amount'],
            'days_overdue': row['max_days_overdue'],
            'owner': owner,
            'promise_date': '—',
        })

    metrics = [
        ('Invoice value', invoice_value, 'money'),
        ('Collection received', collected, 'money'),
        ('Outstanding amount', outstanding, 'money'),
        ('Receivables 0–30 days', aging['0_30'], 'money'),
        ('Receivables 31–60 days', aging['31_60'], 'money'),
        ('Receivables 61–90 days', aging['61_90'], 'money'),
        ('Receivables 90+ days', aging['over_90'], 'money'),
        ('Cash inflow', collected, 'money'),
        ('Cash outflow', paid_out, 'money'),
        ('Net cash flow', collected - paid_out, 'money'),
        ('Payables due this week', pay_week['total'], 'money'),
        ('Bank balance', bank, 'money'),
        ('Cash reserve (GL)', _cash_reserve_balance(), 'money'),
        ('Gross profit %', gross_pct, 'pct'),
        ('Net profit %', profit.get('margin_pct', 0), 'pct'),
        ('Budget expense (month)', budget_exp, 'money'),
        ('Actual expense (month)', actual_exp, 'money'),
    ]
    return {'metrics': metrics, 'top_outstanding': top_clients, 'budget_expense': budget_exp, 'actual_expense': actual_exp}


def _build_procurement_section(filters: CeoFilters, user) -> list[dict]:
    from apps.core.visibility import filter_purchase_requests_for_user

    prs = filter_purchase_requests_for_user(
        PurchaseRequest.objects.filter(
            is_active=True,
            date__gte=filters.date_from,
            date__lte=filters.date_to,
        ).select_related('requested_by', 'department'),
        user,
    )
    if filters.department != 'all':
        keywords = DEPT_KEYWORDS.get(filters.department, (filters.department,))
        q = Q()
        for kw in keywords:
            q |= Q(requested_by__employee_profile__department__name__icontains=kw)
            q |= Q(department__name__icontains=kw)
        prs = prs.filter(q)

    if filters.approval_status == 'pending':
        prs = prs.filter(status='pending')
    elif filters.approval_status == 'approved':
        prs = prs.filter(status='approved')
    elif filters.approval_status == 'rejected':
        prs = prs.filter(status='rejected')
    elif filters.approval_status == 'clarification':
        prs = prs.filter(status='returned')

    prs = prs.prefetch_related('items__inventory_item', 'items__inventory_item__category')[:40]

    rows = []
    for pr in prs:
        po = PurchaseOrder.objects.filter(is_active=True, purchase_request=pr).select_related(
            'vendor', 'project',
        ).prefetch_related('goods_receipts').first()
        first_item = pr.items.select_related('inventory_item').first()
        cat = '—'
        qty = float(pr.items.aggregate(t=Sum('quantity'))['t'] or 0)
        stock_available = '—'
        if first_item and first_item.inventory_item_id:
            item = first_item.inventory_item
            if item.category_id:
                cat = item.category.name
            avail = item.total_stock
            stock_available = 'Yes' if avail >= (first_item.quantity or 0) else 'No'

        approver = get_configured_pr_approver(pr)
        approved_by = approver.get_full_name() if approver else pr.get_status_display()
        if pr.status == 'approved':
            approved_by = 'Approved'
        elif pr.status == 'rejected':
            approved_by = 'Rejected'

        received_date = None
        if po:
            gr = po.goods_receipts.order_by('-received_on').first()
            if gr:
                received_date = gr.received_on

        job = '—'
        if po and po.project_id:
            job = po.project.project_code

        rows.append({
            'pr_number': pr.pr_number,
            'job_number': job,
            'requested_by': pr.requested_by.get_full_name() if pr.requested_by_id else '—',
            'category': cat,
            'quantity': qty,
            'stock_available': stock_available,
            'supplier': po.vendor.name if po and po.vendor_id else '—',
            'price_comparison': 'Yes' if pr.vendor_quote_analysis else 'No',
            'lpo_issued': 'Yes' if po else 'No',
            'amount': float(pr.total_amount),
            'approval_required': 'Yes' if pr.status in ('pending', 'draft') else 'No',
            'approved_by': approved_by,
            'delivery_expected': po.expected_delivery_date if po else pr.required_by_date,
            'received_date': received_date,
            'delay_reason': (pr.rejection_reason[:40] if pr.rejection_reason else '—') if pr.status == 'returned' else '—',
            'emergency': 'Yes' if pr.priority == 'urgent' else 'No',
            'above_limit': _pr_above_approval_limit(pr),
        })
    return rows


def build_executive_report(user, filters: CeoFilters) -> dict:
    from .ceo_module_reports import (
        build_hr_kpi_section,
        build_ops_modules,
        build_sales_modules,
    )
    from .ceo_procurement_inventory import (
        build_inventory_dashboard,
        build_purchase_dashboard,
    )

    return {
        'filters': filters,
        'filter_choices': _filter_choices(user),
        'summary_cards': _build_summary_cards(filters, user),
        'ops_modules': build_ops_modules(user, filters),
        'sales_modules': build_sales_modules(user, filters),
        'hr_kpi': build_hr_kpi_section(user, filters),
        'salespeople': _build_salesperson_section(filters, user),
        'amc': _build_amc_section(filters),
        'finance': _build_finance_section(filters),
        'purchase_dashboard': build_purchase_dashboard(user, filters),
        'inventory_dashboard': build_inventory_dashboard(user, filters),
        'procurement': _build_procurement_section(filters, user),
        'pending_approvals': _pending_ceo_approvals(filters),
    }
