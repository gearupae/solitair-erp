"""Contract-only PDF rendering for estimates / quotations / sales orders."""
from django.conf import settings
from django.template.loader import get_template


def _contract_pdf_base_url(request):
    try:
        return request.build_absolute_uri('/')
    except Exception:
        pass
    origins = getattr(settings, 'CSRF_TRUSTED_ORIGINS', None) or []
    if origins:
        return str(origins[0]).rstrip('/') + '/'
    return 'http://127.0.0.1:8001/'


def build_estimate_contract_pdf_context(request, estimate, *, for_weasyprint=False):
    from apps.settings_app.models import CompanySettings

    from .views import _pdf_media_absolute_url

    company = CompanySettings.get_settings()
    media_kw = {'for_weasyprint': for_weasyprint}
    customer = estimate.customer
    doc_number = estimate.display_estimate_number
    if estimate.status == 'quotation_won' and estimate.sales_order_number:
        doc_number = estimate.display_sales_order_number

    return {
        'estimate': estimate,
        'company': company,
        'customer': customer,
        'document_number': doc_number,
        'page_title': f'Contract — {doc_number}',
        'logo_absolute_url': _pdf_media_absolute_url(request, company.logo, **media_kw),
        'is_pdf': True,
    }


def render_estimate_contract_pdf_bytes(request, estimate):
    try:
        from weasyprint import HTML
    except ImportError:
        return None, 'WeasyPrint is not installed; cannot generate contract PDF.'

    context = build_estimate_contract_pdf_context(request, estimate, for_weasyprint=True)
    template = get_template('sales/estimate_contract_pdf.html')
    html_string = template.render(context)
    try:
        html = HTML(string=html_string, base_url=_contract_pdf_base_url(request))
        pdf = html.write_pdf()
    except Exception as exc:
        return None, f'PDF generation failed: {exc}'
    if not pdf:
        return None, 'PDF generation returned empty output.'
    return pdf, None
