"""Anonymous knowledge editor at /ajas/ (not linked in navigation)."""
from django.contrib import messages
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.core.ai_knowledge import get_knowledge_entries, module_choices, save_knowledge_entries


@never_cache
@require_http_methods(['GET', 'POST'])
def ajas_knowledge_page(request):
    modules = module_choices()
    if request.method == 'POST':
        entries = {
            key: (request.POST.get(f'content_{key}') or '')
            for key, _label in modules
        }
        save_knowledge_entries(entries)
        messages.success(request, 'Knowledge saved.')
        sections = [{'key': key, 'label': label, 'content': entries.get(key, '')} for key, label in modules]
        return render(
            request,
            'core/ajas_knowledge.html',
            {
                'title': 'AI module knowledge',
                'sections': sections,
                'saved': True,
            },
        )

    entries = get_knowledge_entries()
    sections = [{'key': key, 'label': label, 'content': entries.get(key, '')} for key, label in modules]
    return render(
        request,
        'core/ajas_knowledge.html',
        {
            'title': 'AI module knowledge',
            'sections': sections,
            'saved': False,
        },
    )
