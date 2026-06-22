"""Anonymous knowledge editor at /ajas/ (not linked in navigation)."""
from django.contrib import messages
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.core.ai_knowledge import (
    build_sections,
    module_choices,
    save_knowledge_entries,
)


def _page_context(*, sections, saved: bool) -> dict:
    return {
        'title': 'AI module knowledge',
        'sections': sections,
        'saved': saved,
    }


@never_cache
@require_http_methods(['GET', 'POST'])
def ajas_knowledge_page(request):
    modules = module_choices()
    if request.method == 'POST':
        entries = {
            key: (request.POST.get(f'content_{key}') or '')
            for key, _label in modules
        }
        auto_run = {
            key: (request.POST.get(f'auto_run_{key}') == '1')
            for key, _label in modules
        }
        save_knowledge_entries(entries, auto_run=auto_run)
        messages.success(request, 'Settings saved.')
        sections = build_sections()
        for section in sections:
            section['auto_run_enabled'] = auto_run.get(section['key'], False)
            section['content'] = entries.get(section['key'], '')
        return render(
            request,
            'core/ajas_knowledge.html',
            _page_context(sections=sections, saved=True),
        )

    return render(
        request,
        'core/ajas_knowledge.html',
        _page_context(sections=build_sections(), saved=False),
    )
