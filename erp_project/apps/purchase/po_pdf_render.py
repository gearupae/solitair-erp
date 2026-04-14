"""
Shared Purchase Order PDF context + WeasyPrint rendering (used by po_pdf view and email attach).
"""
from django.template.loader import get_template

from apps.settings_app.models import CompanySettings


def _number_to_words(n):
    ones = [
        '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
        'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
        'Seventeen', 'Eighteen', 'Nineteen',
    ]
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
    if n < 20:
        return ones[n]
    if n < 100:
        return tens[n // 10] + ('' if n % 10 == 0 else ' ' + ones[n % 10])
    if n < 1000:
        return ones[n // 100] + ' Hundred' + ('' if n % 100 == 0 else ' and ' + _number_to_words(n % 100))
    if n < 1000000:
        return _number_to_words(n // 1000) + ' Thousand' + ('' if n % 1000 == 0 else ' ' + _number_to_words(n % 1000))
    if n < 1000000000:
        return (
            _number_to_words(n // 1000000) + ' Million'
            + ('' if n % 1000000 == 0 else ' ' + _number_to_words(n % 1000000))
        )
    return str(n)


def build_po_pdf_context(request, po):
    """Context dict for purchase/po_pdf.html (HTML or PDF)."""
    company = CompanySettings.get_settings()

    try:
        amount_whole = int(po.total_amount)
        amount_decimal = int((po.total_amount - amount_whole) * 100)
        amount_words = _number_to_words(amount_whole)
        if amount_decimal > 0:
            amount_words += f' and {amount_decimal}/100'
        amount_words += ' Dirhams Only'
    except Exception:
        amount_words = ''

    vat_summary = {}
    for item in po.items.all():
        rate = float(item.vat_rate)
        if rate not in vat_summary:
            vat_summary[rate] = {'taxable': 0, 'vat': 0}
        vat_summary[rate]['taxable'] += float(item.total)
        vat_summary[rate]['vat'] += float(item.vat_amount)

    logo_absolute_url = ''
    if company.logo:
        logo_absolute_url = request.build_absolute_uri(company.logo.url)

    return {
        'po': po,
        'company': company,
        'amount_words': amount_words,
        'vat_summary': vat_summary,
        'logo_absolute_url': logo_absolute_url,
        'is_pdf': True,
    }


def render_po_pdf_bytes(request, po):
    """
    Render PO as PDF bytes using WeasyPrint.
    Returns (pdf_bytes, None) on success, or (None, error_message) on failure.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        return None, 'WeasyPrint is not installed; cannot generate PDF for email.'

    context = build_po_pdf_context(request, po)
    template = get_template('purchase/po_pdf.html')
    html_string = template.render(context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()
    return pdf, None
