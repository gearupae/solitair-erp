"""Support module helpers."""

from django.db.models import Q

from apps.contracts.models import Contract, ContractType


SUPPORT_KANBAN_STAGE_THEMES = [
    {'header_bg': '#dbeafe', 'header_color': '#1e40af', 'accent': '#3b82f6', 'body_bg': '#eff6ff'},
    {'header_bg': '#fef3c7', 'header_color': '#b45309', 'accent': '#f59e0b', 'body_bg': '#fffbeb'},
    {'header_bg': '#fce7f3', 'header_color': '#be185d', 'accent': '#ec4899', 'body_bg': '#fdf2f8'},
    {'header_bg': '#ccfbf1', 'header_color': '#0f766e', 'accent': '#14b8a6', 'body_bg': '#f0fdfa'},
    {'header_bg': '#e0e7ff', 'header_color': '#4338ca', 'accent': '#6366f1', 'body_bg': '#eef2ff'},
    {'header_bg': '#ffedd5', 'header_color': '#c2410c', 'accent': '#f97316', 'body_bg': '#fff7ed'},
]

SUPPORT_KANBAN_UNASSIGNED_THEME = {
    'header_bg': '#f3f4f6',
    'header_color': '#374151',
    'accent': '#6b7280',
    'body_bg': '#f9fafb',
}

SUPPORT_KANBAN_CLOSED_THEME = {
    'header_bg': '#dcfce7',
    'header_color': '#166534',
    'accent': '#22c55e',
    'body_bg': '#f0fdf4',
}


def kanban_theme_style(theme):
    return (
        f'--kb-header-bg:{theme["header_bg"]};'
        f'--kb-header-color:{theme["header_color"]};'
        f'--kb-accent:{theme["accent"]};'
        f'--kb-body-bg:{theme["body_bg"]};'
        f'--kb-card-border:{theme.get("card_border", "#e2e8f0")};'
    )


def get_amc_contract_queryset():
    """Active contracts; prefer those tagged as AMC when types exist."""
    qs = Contract.objects.filter(is_active=True).select_related('customer').prefetch_related(
        'contract_types'
    )
    amc_types = ContractType.objects.filter(
        Q(name__icontains='amc') | Q(slug__icontains='amc'),
        is_active=True,
    )
    if amc_types.exists():
        qs = qs.filter(contract_types__in=amc_types).distinct()
    return qs.order_by('-created_at')


def get_default_support_kanban_stage():
    from .models import SupportTicketKanbanStage

    stage = SupportTicketKanbanStage.objects.filter(
        is_active=True,
        is_closed=False,
        slug='new',
    ).first()
    if stage:
        return stage
    return SupportTicketKanbanStage.objects.filter(is_active=True, is_closed=False).order_by(
        'sort_order', 'id'
    ).first()


def _customer_display_label(customer):
    parts = []
    if customer.company:
        parts.append(customer.company)
    if customer.name and customer.name not in parts:
        parts.append(customer.name)
    if not parts:
        parts.append(customer.customer_number)
    return ' — '.join(parts[:2])


def search_public_link_suggestions(query, limit=8):
    """
    Fuzzy match customers, projects, and AMC contracts for the public support form.
    Returns list of dicts: type, id, label, subtitle.
    """
    q = (query or '').strip()
    if len(q) < 2:
        return []

    from apps.crm.models import Customer
    from apps.projects.models import Project

    results = []
    seen = set()

    def add(item_type, pk, label, subtitle):
        key = (item_type, pk)
        if key in seen or len(results) >= limit:
            return
        seen.add(key)
        results.append({
            'type': item_type,
            'id': pk,
            'label': label,
            'subtitle': subtitle,
        })

    customer_qs = Customer.objects.filter(is_active=True).filter(
        Q(name__icontains=q)
        | Q(company__icontains=q)
        | Q(customer_number__icontains=q)
        | Q(email__icontains=q)
        | Q(phone__icontains=q)
    ).order_by('company', 'name')[:5]
    for customer in customer_qs:
        add(
            'customer',
            customer.pk,
            _customer_display_label(customer),
            f'Customer · {customer.customer_number}',
        )

    project_qs = Project.objects.filter(is_active=True).select_related('customer').filter(
        Q(name__icontains=q)
        | Q(project_code__icontains=q)
        | Q(customer__name__icontains=q)
        | Q(customer__company__icontains=q)
    ).order_by('-created_at')[:5]
    for project in project_qs:
        subtitle = f'Project · {project.project_code}'
        if project.customer_id:
            subtitle += f' · {_customer_display_label(project.customer)}'
        add('project', project.pk, f'{project.project_code} — {project.name}', subtitle)

    amc_qs = get_amc_contract_queryset().filter(
        Q(name__icontains=q)
        | Q(contract_number__icontains=q)
        | Q(customer__name__icontains=q)
        | Q(customer__company__icontains=q)
    )[:5]
    for contract in amc_qs:
        subtitle = f'AMC · {contract.contract_number}'
        if contract.customer_id:
            subtitle += f' · {_customer_display_label(contract.customer)}'
        add('amc', contract.pk, f'{contract.contract_number} — {contract.name}', subtitle)

    return results[:limit]

