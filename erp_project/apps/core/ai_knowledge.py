"""Load module knowledge for AI compliance evaluation prompts."""
from __future__ import annotations

from apps.core.models import AiModuleKnowledge

MAX_KNOWLEDGE_CHARS = 12000


def module_choices() -> list[tuple[str, str]]:
    return list(AiModuleKnowledge.MODULE_CHOICES)


def get_knowledge_entries() -> dict[str, str]:
    """Return {module_key: content} for all modules (empty string if unset)."""
    stored = {row.module: row.content for row in AiModuleKnowledge.objects.all()}
    return {key: stored.get(key, '') for key, _label in AiModuleKnowledge.MODULE_CHOICES}


def save_knowledge_entries(entries: dict[str, str]) -> None:
    valid_keys = {key for key, _label in AiModuleKnowledge.MODULE_CHOICES}
    for module_key, content in entries.items():
        if module_key not in valid_keys:
            continue
        AiModuleKnowledge.objects.update_or_create(
            module=module_key,
            defaults={'content': (content or '')[:50000]},
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
