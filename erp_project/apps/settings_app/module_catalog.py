"""Display metadata for ERP modules (icons, colors)."""
from apps.core.nav_config import minimal_nav_module_choices
from apps.settings_app.models import ModulePermission

# Admin/system modules — not shown on the user request page.
EXCLUDED_FROM_REQUEST = frozenset({'settings'})

MODULE_DISPLAY = {
    'crm': {
        'icon': 'fa-users',
        'gradient': 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
        'desc': 'Leads, customers & pipeline',
    },
    'sales': {
        'icon': 'fa-shopping-cart',
        'gradient': 'linear-gradient(135deg, #22c55e 0%, #16a34a 100%)',
        'desc': 'Estimates, orders & invoicing',
    },
    'purchase': {
        'icon': 'fa-truck',
        'gradient': 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)',
        'desc': 'Vendors, POs & procurement',
    },
    'inventory': {
        'icon': 'fa-boxes',
        'gradient': 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)',
        'desc': 'Stock, items & warehouses',
    },
    'finance': {
        'icon': 'fa-coins',
        'gradient': 'linear-gradient(135deg, #eab308 0%, #ca8a04 100%)',
        'desc': 'Accounts, payments & VAT',
    },
    'projects': {
        'icon': 'fa-project-diagram',
        'gradient': 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
        'desc': 'Projects, tasks & expenses',
    },
    'hr': {
        'icon': 'fa-user-friends',
        'gradient': 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
        'desc': 'Employees, leave & payroll',
    },
    'documents': {
        'icon': 'fa-folder-open',
        'gradient': 'linear-gradient(135deg, #64748b 0%, #475569 100%)',
        'desc': 'Files, contracts & expiry',
    },
    'assets': {
        'icon': 'fa-building',
        'gradient': 'linear-gradient(135deg, #78716c 0%, #57534e 100%)',
        'desc': 'Fixed assets & depreciation',
    },
    'property': {
        'icon': 'fa-city',
        'gradient': 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%)',
        'desc': 'Tenants, leases & PDC',
    },
    'service_request': {
        'icon': 'fa-tools',
        'gradient': 'linear-gradient(135deg, #a855f7 0%, #9333ea 100%)',
        'desc': 'Internal service requests',
    },
    'contracts': {
        'icon': 'fa-file-contract',
        'gradient': 'linear-gradient(135deg, #4f46e5 0%, #4338ca 100%)',
        'desc': 'AMC & contract management',
    },
    'support': {
        'icon': 'fa-life-ring',
        'gradient': 'linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)',
        'desc': 'Tickets & help desk',
    },
    'fleet': {
        'icon': 'fa-truck-moving',
        'gradient': 'linear-gradient(135deg, #334155 0%, #1e293b 100%)',
        'desc': 'Vehicles & fleet documents',
    },
    'reports': {
        'icon': 'fa-chart-pie',
        'gradient': 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)',
        'desc': 'Cross-module analytics',
    },
}


def get_module_catalog(include_admin=False):
    """Return ordered list of module cards for display."""
    catalog = []
    for code, label in minimal_nav_module_choices(ModulePermission.MODULE_CHOICES):
        if not include_admin and code in EXCLUDED_FROM_REQUEST:
            continue
        meta = MODULE_DISPLAY.get(code, {
            'icon': 'fa-cube',
            'gradient': 'linear-gradient(135deg, #94a3b8 0%, #64748b 100%)',
            'desc': 'ERP module',
        })
        catalog.append({
            'code': code,
            'label': label,
            'icon': meta['icon'],
            'gradient': meta['gradient'],
            'desc': meta.get('desc', ''),
        })
    return catalog
