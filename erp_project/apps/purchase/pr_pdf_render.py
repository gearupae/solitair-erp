"""Purchase Request PDF context + WeasyPrint rendering."""
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


def build_pr_pdf_context(request, pr):
    """Context dict for purchase/pr_pdf.html."""
    company = CompanySettings.get_settings()

    try:
        amount_whole = int(pr.total_amount)
        amount_decimal = int((pr.total_amount - amount_whole) * 100)
        amount_words = _number_to_words(amount_whole)
        if amount_decimal > 0:
            amount_words += f' and {amount_decimal}/100'
        amount_words += ' Dirhams Only'
    except Exception:
        amount_words = ''

    logo_absolute_url = ''
    if company.logo:
        logo_absolute_url = request.build_absolute_uri(company.logo.url)

    pdf_image_1_url = ''
    if company.estimate_pdf_stamp_image:
        pdf_image_1_url = request.build_absolute_uri(company.estimate_pdf_stamp_image.url)
    pdf_image_2_url = ''
    if company.estimate_pdf_footer_image:
        pdf_image_2_url = request.build_absolute_uri(company.estimate_pdf_footer_image.url)

    return {
        'pr': pr,
        'company': company,
        'amount_words': amount_words,
        'logo_absolute_url': logo_absolute_url,
        'pdf_image_1_url': pdf_image_1_url,
        'pdf_image_2_url': pdf_image_2_url,
        'is_pdf': True,
    }


def render_pr_pdf_bytes(request, pr):
    """Render PR as PDF bytes using WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError:
        return None, 'WeasyPrint is not installed; cannot generate PDF.'

    context = build_pr_pdf_context(request, pr)
    template = get_template('purchase/pr_pdf.html')
    html_string = template.render(context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()
    return pdf, None
