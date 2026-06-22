"""Load module knowledge for AI compliance evaluation prompts."""
from __future__ import annotations

from apps.core.models import AiComplianceSettings, AiModuleKnowledge

MAX_KNOWLEDGE_CHARS = 12000

MODULE_META: dict[str, dict[str, str]] = {
    AiModuleKnowledge.MODULE_PURCHASE_REQUEST: {
        'icon': 'fa-file-invoice',
        'color': '#2563eb',
        'description': 'Vendor quotes, approval thresholds, and procurement policy for purchase requests.',
    },
    AiModuleKnowledge.MODULE_PURCHASE_ORDER: {
        'icon': 'fa-shopping-cart',
        'color': '#7c3aed',
        'description': 'PO terms, delivery rules, and supplier compliance for purchase orders.',
    },
    AiModuleKnowledge.MODULE_ESTIMATE: {
        'icon': 'fa-file-contract',
        'color': '#0891b2',
        'description': 'Quotation pricing, margin rules, and sales compliance for estimates.',
    },
    AiModuleKnowledge.MODULE_PROJECT: {
        'icon': 'fa-diagram-project',
        'color': '#059669',
        'description': 'Budget limits, milestone rules, and delivery standards for projects.',
    },
    AiModuleKnowledge.MODULE_EMPLOYEE: {
        'icon': 'fa-user-tie',
        'color': '#d97706',
        'description': 'HR policies, visa rules, and labour compliance for employee records.',
    },
    AiModuleKnowledge.MODULE_INVENTORY: {
        'icon': 'fa-boxes-stacked',
        'color': '#0f766e',
        'description': 'Reorder rules, UAE VAT on write-offs, lot traceability, and stock compliance policies.',
    },
}


def module_choices() -> list[tuple[str, str]]:
    return list(AiModuleKnowledge.MODULE_CHOICES)


def _global_auto_run_default() -> bool:
    return AiComplianceSettings.get_settings().auto_run_enabled


def is_ai_analysis_auto_run(module_key: str) -> bool:
    """Whether detail pages should trigger AI compliance checks after load for a module."""
    row = AiModuleKnowledge.objects.filter(module=module_key).only('auto_run_enabled').first()
    if row is not None:
        return row.auto_run_enabled
    return _global_auto_run_default()


def get_knowledge_entries() -> dict[str, str]:
    """Return {module_key: content} for all modules (empty string if unset)."""
    stored = {row.module: row.content for row in AiModuleKnowledge.objects.all()}
    return {key: stored.get(key, '') for key, _label in AiModuleKnowledge.MODULE_CHOICES}


def get_module_auto_run_settings() -> dict[str, bool]:
    """Return {module_key: auto_run_enabled} using stored values or global default."""
    default = _global_auto_run_default()
    stored = {
        row.module: row.auto_run_enabled
        for row in AiModuleKnowledge.objects.only('module', 'auto_run_enabled')
    }
    return {key: stored.get(key, default) for key, _label in AiModuleKnowledge.MODULE_CHOICES}


def build_sections() -> list[dict]:
    """Section payloads for the /ajas/ editor."""
    entries = get_knowledge_entries()
    auto_run = get_module_auto_run_settings()
    sections = []
    for key, label in module_choices():
        meta = MODULE_META.get(key, {})
        sections.append({
            'key': key,
            'label': label,
            'content': entries.get(key, ''),
            'auto_run_enabled': auto_run.get(key, True),
            'icon': meta.get('icon', 'fa-book'),
            'color': meta.get('color', '#64748b'),
            'description': meta.get('description', ''),
        })
    return sections


def save_knowledge_entries(entries: dict[str, str], *, auto_run: dict[str, bool] | None = None) -> None:
    valid_keys = {key for key, _label in AiModuleKnowledge.MODULE_CHOICES}
    auto_run = auto_run or {}
    for module_key, content in entries.items():
        if module_key not in valid_keys:
            continue
        defaults = {'content': (content or '')[:50000]}
        if module_key in auto_run:
            defaults['auto_run_enabled'] = bool(auto_run[module_key])
        AiModuleKnowledge.objects.update_or_create(
            module=module_key,
            defaults=defaults,
        )


def get_ai_knowledge_prompt_block(module_key: str) -> str:
    """Text block appended to AI prompts; empty when no knowledge is stored."""
    try:
        row = AiModuleKnowledge.objects.filter(module=module_key).first()
    except Exception:
        return ''
    if not row or not (row.content or '').strip():
        return ''
    content = row.content.strip()[:MAX_KNOWLEDGE_CHARS]
    return (
        '\n\n--- COMPLIANCE & MODULE KNOWLEDGE (apply strictly when evaluating) ---\n'
        f'{content}\n'
        '--- END KNOWLEDGE ---'
    )
