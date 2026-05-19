"""
Shared estimate quotation/proposal PDF context + WeasyPrint rendering (estimate PDF view + send-email attachment).
"""
from django.template.loader import get_template


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

    context = _build_estimate_pdf_context(request, estimate)
    context.update(
        {
            'document_heading': 'QUOTATION',
            'document_number': estimate.estimate_number,
            'page_title': f'Quotation — {estimate.estimate_number}',
            'print_button_label': 'Print quotation',
            'show_pdf_status': True,
            'pdf_variant': 'quotation',
            'pdf_details_heading': 'Quotation details',
            'pdf_date_label': 'Quotation date',
        }
    )
    template = get_template('sales/estimate_pdf.html')
    html_string = template.render(context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()
    return pdf, None
