"""
Shared estimate quotation/proposal PDF context + WeasyPrint rendering (estimate PDF view + send-email attachment).
"""
from django.conf import settings
from django.template.loader import get_template


def _estimate_pdf_base_url(request):
    """Base URL for WeasyPrint assets; avoids DisallowedHost on odd test hosts."""
    try:
        return request.build_absolute_uri('/')
    except Exception:
        pass
    origins = getattr(settings, 'CSRF_TRUSTED_ORIGINS', None) or []
    if origins:
        return str(origins[0]).rstrip('/') + '/'
    return 'http://127.0.0.1:8001/'


def render_estimate_quotation_pdf_bytes(request, estimate):
    """
    Render quotation (proposal) PDF — same heading as sales:estimate_pdf.
    Returns (pdf_bytes, None) on success, or (None, error_message) on failure.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        return None, 'WeasyPrint is not installed; cannot generate PDF for email.'

    # Lazy import avoids circular imports (views imports this module).
    from .views import _build_estimate_pdf_context

    context = _build_estimate_pdf_context(request, estimate, for_weasyprint=True)
    context.update(
        {
            'document_heading': 'QUOTATION',
            'document_number': estimate.display_estimate_number,
            'page_title': f'Quotation — {estimate.display_estimate_number}',
            'print_button_label': 'Print quotation',
            'show_pdf_status': True,
            'pdf_variant': 'quotation',
            'pdf_details_heading': 'Quotation details',
            'pdf_date_label': 'Quotation date',
        }
    )
    template = get_template('sales/estimate_pdf.html')
    html_string = template.render(context)
    try:
        html = HTML(string=html_string, base_url=_estimate_pdf_base_url(request))
        pdf = html.write_pdf()
    except Exception as exc:
        return None, f'PDF generation failed: {exc}'
    if not pdf:
        return None, 'PDF generation returned empty output.'
    return pdf, None
