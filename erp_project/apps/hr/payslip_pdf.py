"""ReportLab payslip PDF — aligned to page width, compact; optional page 2 for extras (max 2 pages)."""
from __future__ import annotations

import re
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.hr.payroll_allowances import effective_payroll_company
from apps.hr.payroll_processing import compute_iloe_deduction, get_payroll_settings
from apps.settings_app.models import CompanySettings

_PRIMARY = colors.HexColor('#0f2744')
_ACCENT = colors.HexColor('#1d6a8a')
_MUTED = colors.HexColor('#64748b')
_BG_BAND = colors.HexColor('#e8eef4')
_BG_ROW = colors.HexColor('#f6f8fb')
_BORDER = colors.HexColor('#cbd5e1')
_NET_FILL = colors.HexColor('#ecfdf5')
_NET_BORDER = colors.HexColor('#059669')
_WHITE = colors.white

# Margins — slightly tighter vertical to help stay within 2 pages
_M_L = _M_R = 16 * mm
_M_T = _M_B = 14 * mm


def payslip_number(payroll) -> str:
    raw = (payroll.employee.employee_code or str(payroll.employee_id)).strip().upper().replace(' ', '')
    return f'PS-{payroll.month:%Y-%m}-{raw}'


def _content_width() -> float:
    return A4[0] - _M_L - _M_R


_styles: dict = {}


def _init_styles():
    global _styles
    if _styles:
        return
    base = getSampleStyleSheet()
    _styles['cell'] = ParagraphStyle(
        name='PSCell',
        parent=base['Normal'],
        fontSize=8,
        leading=10,
        textColor=_PRIMARY,
        wordWrap='CJK',
    )
    _styles['cell_r'] = ParagraphStyle(
        name='PSCellR',
        parent=base['Normal'],
        fontSize=8,
        leading=10,
        alignment=2,
        textColor=_PRIMARY,
        wordWrap='CJK',
    )
    _styles['cell_b'] = ParagraphStyle(
        name='PSCellB',
        parent=base['Normal'],
        fontSize=8,
        leading=10,
        textColor=_PRIMARY,
        fontName='Helvetica-Bold',
    )
    _styles['section'] = ParagraphStyle(
        name='PSSection',
        parent=base['Normal'],
        fontSize=9,
        spaceBefore=5,
        spaceAfter=3,
        leading=11,
        textColor=_PRIMARY,
        fontName='Helvetica-Bold',
    )
    _styles['section_p2'] = ParagraphStyle(
        name='PSSectionP2',
        parent=base['Normal'],
        fontSize=8,
        spaceBefore=4,
        spaceAfter=2,
        leading=10,
        textColor=_PRIMARY,
        fontName='Helvetica-Bold',
    )
    _styles['cell_p2'] = ParagraphStyle(
        name='PSCellP2',
        parent=base['Normal'],
        fontSize=7,
        leading=9,
        textColor=_PRIMARY,
        wordWrap='CJK',
    )
    _styles['cell_r_p2'] = ParagraphStyle(
        name='PSCellRP2',
        parent=base['Normal'],
        fontSize=7,
        leading=9,
        alignment=2,
        textColor=_PRIMARY,
        wordWrap='CJK',
    )
    _styles['cell_b_p2'] = ParagraphStyle(
        name='PSCellBP2',
        parent=base['Normal'],
        fontSize=7,
        leading=9,
        textColor=_PRIMARY,
        fontName='Helvetica-Bold',
    )
    _styles['footer'] = ParagraphStyle(
        name='PSFooter',
        parent=base['Italic'],
        fontSize=7,
        textColor=_MUTED,
        alignment=1,
        spaceBefore=8,
        leading=9,
    )
    _styles['hdr_white'] = ParagraphStyle(
        name='PSHdrW',
        parent=base['Normal'],
        fontSize=8,
        leading=10,
        textColor=_WHITE,
    )
    _styles['hdr_white_r'] = ParagraphStyle(
        name='PSHdrWR',
        parent=base['Normal'],
        fontSize=8,
        leading=10,
        textColor=_WHITE,
        alignment=2,
    )


def _money_table(
    rows: list,
    col_widths: list[float],
    header: tuple[str, str] | None = None,
    *,
    compact: bool = False,
) -> Table:
    cb = _styles['cell_b_p2'] if compact else _styles['cell_b']
    cl = _styles['cell_p2'] if compact else _styles['cell']
    cr = _styles['cell_r_p2'] if compact else _styles['cell_r']
    data = []
    if header:
        data.append(
            [
                Paragraph(f'<b>{header[0]}</b>', cb),
                Paragraph(f'<b>{header[1]}</b>', cr),
            ]
        )
    for label, value in rows:
        data.append([Paragraph(str(label), cl), Paragraph(str(value), cr)])
    repeat_rows = 1 if header else 0
    t = Table(data, colWidths=col_widths, hAlign='LEFT', repeatRows=repeat_rows)
    nrows = len(data)
    style_cmds = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]
    if nrows > 1:
        style_cmds.append(('LINEBELOW', (0, 0), (-1, nrows - 2), 0.25, _BORDER))
    if header:
        style_cmds.extend(
            [
                ('BACKGROUND', (0, 0), (-1, 0), _BG_BAND),
                ('LINEBELOW', (0, 0), (-1, 0), 1, _ACCENT),
            ]
        )
    else:
        style_cmds.append(('BACKGROUND', (0, 0), (-1, -1), _WHITE))

    if data:
        last_i = nrows - 1
        lbl = rows[-1][0] if rows else ''
        if isinstance(lbl, str) and any(x in lbl.lower() for x in ('gross', 'total', 'net')):
            style_cmds.extend(
                [
                    ('LINEABOVE', (0, last_i), (-1, last_i), 1, _PRIMARY),
                    ('TOPPADDING', (0, last_i), (-1, last_i), 6),
                ]
            )
    t.setStyle(TableStyle(style_cmds))
    return t


def _section_heading(text: str) -> Paragraph:
    return Paragraph(f'<b>{text}</b>', _styles['section'])


def _section_heading_p2(text: str) -> Paragraph:
    return Paragraph(f'<b>{text}</b>', _styles['section_p2'])


def build_payslip_pdf(payroll) -> bytes:
    _init_styles()
    cw = _content_width()
    company = CompanySettings.get_settings()
    emp = payroll.employee
    ent = effective_payroll_company(payroll)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_M_L,
        rightMargin=_M_R,
        topMargin=_M_T,
        bottomMargin=_M_B,
    )
    styles = getSampleStyleSheet()
    body = styles['Normal']

    story = []
    display_name = ent.name if ent else (company.company_name if company else 'Company')
    logo_src = None
    if ent and ent.logo:
        logo_src = ent.logo
    elif company and company.logo:
        logo_src = company.logo

    logo_block = Spacer(1, 1)
    if logo_src:
        path = logo_src.path if hasattr(logo_src, 'path') else ''
        if path:
            try:
                logo_block = Image(path, width=28 * mm, height=12 * mm)
            except Exception:
                logo_block = Paragraph(f'<b>{display_name}</b>', _styles['hdr_white'])

    addr_bits = []
    if ent and ent.address:
        addr_bits.append(ent.address.replace('\n', '<br/>'))
    elif company and company.address and not ent:
        addr_bits.append(company.address.replace('\n', '<br/>'))
    if company:
        if company.phone:
            addr_bits.append(f'Tel: {company.phone}')
        if company.email:
            addr_bits.append(company.email)

    period_str = payroll.month.strftime('%B %Y')
    ps_id = payslip_number(payroll)

    w_logo = 34 * mm
    w_mid = cw - w_logo - 52 * mm
    w_right = 52 * mm

    right_hdr = Paragraph(
        f'<font size="14"><b>PAYSLIP</b></font><br/>'
        f'<font size="7" color="#cbd5e1">Reference</font><br/>'
        f'<font size="9"><b>{ps_id}</b></font><br/>'
        f'<font size="7" color="#cbd5e1">Pay period</font><br/>'
        f'<font size="9"><b>{period_str}</b></font>',
        _styles['hdr_white_r'],
    )

    logo_wrap = Table([[logo_block]], colWidths=[w_logo - 16 * mm])
    logo_wrap.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), _WHITE),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]
        )
    )

    left_hdr = Paragraph(
        f'<font size="11"><b>{display_name}</b></font><br/>'
        f'<font size="7" color="#cbd5e1">{" · ".join(addr_bits) if addr_bits else ""}</font>',
        _styles['hdr_white'],
    )

    header_main = Table([[logo_wrap, left_hdr, right_hdr]], colWidths=[w_logo, w_mid, w_right], hAlign='LEFT')
    header_main.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), _PRIMARY),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('LINEAFTER', (0, 0), (0, 0), 0.25, colors.HexColor('#334155')),
            ]
        )
    )
    story.append(header_main)
    story.append(Spacer(1, 8))

    profile = getattr(emp, 'hr_profile', None)
    nat = profile.nationality_display if profile else ''
    loc_display = emp.get_location_display() if hasattr(emp, 'get_location_display') else (emp.location or '-').upper()

    emp_rows = [
        ('Employee', emp.full_name),
        ('Code', emp.employee_code),
        ('Company', ent.name if ent else '-'),
        ('Location', loc_display),
        ('Department', str(emp.department) if emp.department else '-'),
        ('Designation', str(emp.designation) if emp.designation else '-'),
        ('Date of joining', emp.date_of_joining.strftime('%d/%m/%Y') if emp.date_of_joining else '-'),
        ('Nationality', nat or '-'),
    ]
    story.append(_section_heading('Employee details'))
    w_lbl = cw * 0.19
    w_val = cw * 0.31
    er_grid = []
    for i in range(0, len(emp_rows), 2):
        r = emp_rows[i]
        row_cells = [
            Paragraph(f'<b>{r[0]}</b>', _styles['cell_b']),
            Paragraph(str(r[1]), _styles['cell']),
        ]
        if i + 1 < len(emp_rows):
            r2 = emp_rows[i + 1]
            row_cells.extend([Paragraph(f'<b>{r2[0]}</b>', _styles['cell_b']), Paragraph(str(r2[1]), _styles['cell'])])
        else:
            row_cells.extend([Paragraph('', _styles['cell']), Paragraph('', _styles['cell'])])
        er_grid.append(row_cells)
    t_emp = Table(er_grid, colWidths=[w_lbl, w_val, w_lbl, w_val], hAlign='LEFT')
    t_emp.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), _BG_ROW),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LINEBELOW', (0, 0), (-1, -2), 0.25, _BORDER),
                ('LINEABOVE', (0, 0), (-1, 0), 0.5, _ACCENT),
                ('LINEBELOW', (0, -1), (-1, -1), 0.25, _BORDER),
            ]
        )
    )
    story.append(t_emp)
    story.append(Spacer(1, 6))

    from apps.hr.models_extended import AttendanceSummary
    from datetime import date

    month_first = date(payroll.month.year, payroll.month.month, 1)
    summ = AttendanceSummary.objects.filter(employee=emp, month=month_first).first()

    currency = 'SAR' if (emp.location or '').lower() == 'ksa' else 'AED'

    from apps.hr.models_extended import (
        EmployeeAdvance,
        GratuityRecord,
        PayrollAllowanceLine,
        PayrollDeductionLine,
        UAECompliance,
    )
    from apps.hr.salary_payroll_utils import structural_allowances_total, working_days_divisor_from_settings

    lines = list(payroll.deduction_lines.all())

    w_desc = cw * 0.62
    w_amt = cw - w_desc

    story.append(_section_heading('Earnings'))
    earn_data = [('Basic Salary', f'{currency} {payroll.basic_salary:,.2f}')]
    for ln in payroll.allowance_lines.all().order_by('pk'):
        title = ln.description or ln.code
        if ln.code == PayrollAllowanceLine.CODE_OVERTIME:
            title = title or 'Overtime'
        earn_data.append((title, f'{currency} {ln.amount:,.2f}'))
    gross_full = payroll.basic_salary + payroll.allowances
    earn_data.append(('<b>Gross Salary</b>', f'<b>{currency} {gross_full:,.2f}</b>'))
    earn_tbl = _money_table(earn_data, [w_desc, w_amt], ('Description', 'Amount'))
    story.append(earn_tbl)
    story.append(Spacer(1, 5))

    story.append(_section_heading('Deductions'))

    def _deduction_row_pdf(ln):
        code_u = (ln.code or '').upper()
        if code_u == 'ILOE':
            _, cat = compute_iloe_deduction(payroll.basic_salary)
            lbl = f'ILOE Insurance (Cat {cat})'
            return (lbl, f'- {currency} {ln.amount:,.2f}')
        return (ln.label, f'- {currency} {ln.amount:,.2f}')

    ded_rows = [_deduction_row_pdf(ln) for ln in lines]
    if not ded_rows:
        ded_rows = [('—', f'{currency} 0.00')]
    total_ded = payroll.deductions
    ded_rows.append(('<b>Total Deductions</b>', f'<b>{currency} {total_ded:,.2f}</b>'))
    ded_tbl = _money_table(ded_rows, [w_desc, w_amt], ('Description', 'Amount'))
    story.append(ded_tbl)

    adv_lines = [ln for ln in lines if ln.code == PayrollDeductionLine.CODE_ADVANCE_REPAYMENT]
    if adv_lines:
        adv_total = sum((ln.amount for ln in adv_lines), Decimal('0'))
        id_pat = re.compile(r'\[id:(\d+)\]')
        rem_sum = Decimal('0')
        seen = set()
        for ln in adv_lines:
            m = id_pat.search(ln.label or '')
            if not m:
                continue
            pk = int(m.group(1))
            if pk in seen:
                continue
            seen.add(pk)
            adv_obj = EmployeeAdvance.objects.filter(pk=pk).first()
            if adv_obj:
                rem_sum += adv_obj.amount_remaining
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                f'<b>Advance repayment:</b> {currency} {adv_total:,.2f} &nbsp;·&nbsp; '
                f'<b>Remaining:</b> {currency} {rem_sum:,.2f}',
                _styles['cell'],
            )
        )

    loc = (emp.location or 'uae').lower()

    net_para = Paragraph(
        f'<font color="#065f46" size="12"><b>NET SALARY</b></font><br/>'
        f'<font color="#047857" size="16"><b>{currency} {payroll.net_salary:,.2f}</b></font>',
        ParagraphStyle(name='NetBox', parent=body, alignment=1, leading=18),
    )
    net_box = Table([[net_para]], colWidths=[cw], hAlign='LEFT')
    net_box.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), _NET_FILL),
                ('BOX', (0, 0), (-1, -1), 1.2, _NET_BORDER),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ]
        )
    )

    ps = get_payroll_settings()
    wd_note = working_days_divisor_from_settings(ps)
    struct_gross = payroll.gross_salary or (
        (payroll.basic_salary or Decimal('0')) + structural_allowances_total(payroll)
    )
    daily_note = (struct_gross / Decimal(wd_note)).quantize(Decimal('0.01')) if wd_note else Decimal('0')
    daily_note_para = Paragraph(
        f'<font size="8" color="#64748b"><i>Daily rate used: {currency} {daily_note:,.2f}/day '
        f'({currency} {struct_gross:,.2f} gross ÷ {wd_note} days).</i></font>',
        ParagraphStyle(name='DailyNote', parent=body, alignment=1, leading=10),
    )

    page1_tail = KeepTogether([Spacer(1, 8), net_box, Spacer(1, 6), daily_note_para])
    story.append(page1_tail)

    supplementary = []
    if summ:
        from calendar import monthrange

        cal_days = monthrange(payroll.month.year, payroll.month.month)[1]
        wd = summ.total_working_days if getattr(summ, 'total_working_days', None) else '-'
        att_rows = [
            ('Working days (calendar)', str(cal_days)),
            ('Working days (recorded)', str(wd)),
            ('Present', str(summ.total_present)),
            ('Absent', str(summ.total_absent)),
            ('Late', str(summ.total_late)),
            ('Half day', str(summ.total_half_day)),
            ('Overtime hours', str(summ.total_overtime_hours)),
        ]
        supplementary.append(_section_heading_p2('Attendance'))
        supplementary.append(
            _money_table(att_rows, [cw * 0.62, cw * 0.38], ('Metric', 'Value'), compact=True)
        )
        supplementary.append(Spacer(1, 2))

    if loc == 'uae':
        extras = []
        ps_pdf = get_payroll_settings()
        uc_sup = UAECompliance.objects.filter(employee=emp).first()
        iloe_ln = next((x for x in lines if (x.code or '').upper() == 'ILOE'), None)
        if not iloe_ln and (uc_sup is None or uc_sup.iloe_applicable) and not ps_pdf.iloe_deduct_via_payroll:
            tot_iloe, cat_iloe = compute_iloe_deduction(payroll.basic_salary)
            extras.append(
                f'ILOE Insurance (Cat {cat_iloe}): {currency} {tot_iloe:,.2f} — reminder only (not deducted). '
                f'Pay via iloe.ae; employer may deduct and remit separately if agreed.'
            )
        grat = GratuityRecord.objects.filter(payroll=payroll).first()
        if grat:
            extras.append(f'Gratuity (info): {currency} {grat.provision_amount:,.2f}')
        wps = getattr(payroll, 'wps_record', None)
        if wps:
            st = wps.get_status_display() if hasattr(wps, 'get_status_display') else wps.status
            extras.append(f'WPS: {st}')
        if extras:
            supplementary.append(_section_heading_p2('UAE — compliance'))
            supplementary.append(Paragraph(' · '.join(extras), _styles['cell_p2']))
            supplementary.append(Spacer(1, 2))

    if loc == 'ksa':
        extras = []
        gosi_emp = next((x for x in lines if x.code == PayrollDeductionLine.CODE_GOSI_EMPLOYEE), None)
        if gosi_emp:
            extras.append(f'GOSI employee: {currency} {gosi_emp.amount:,.2f}')
        erc_ksa = list(payroll.employer_contributions.all())
        er_tot = sum((r.amount for r in erc_ksa), Decimal('0'))
        if er_tot > 0:
            extras.append(f'GOSI employer (info): {currency} {er_tot:,.2f}')
        if extras:
            supplementary.append(_section_heading_p2('KSA — compliance'))
            supplementary.append(Paragraph(' · '.join(extras), _styles['cell_p2']))
            supplementary.append(Spacer(1, 2))

    erc = list(payroll.employer_contributions.all())
    if erc and loc != 'ksa':
        supplementary.append(_section_heading_p2('Employer contributions (informational)'))
        er_rows = [(r.label, f'{currency} {r.amount:,.2f}') for r in erc]
        supplementary.append(
            _money_table(er_rows, [cw * 0.58, cw * 0.42], ('Description', 'Amount'), compact=True)
        )
        supplementary.append(Spacer(1, 2))

    grat = GratuityRecord.objects.filter(payroll=payroll).first()
    if grat and loc != 'uae':
        supplementary.append(
            Paragraph(
                f'<b>Gratuity (informational):</b> {currency} {grat.provision_amount:,.2f}',
                _styles['cell_p2'],
            )
        )
        supplementary.append(Spacer(1, 2))

    from apps.hr.models import LeaveBalance

    lbs = (
        LeaveBalance.objects.filter(employee=emp, year=payroll.month.year)
        .select_related('leave_type')
        .filter(leave_type__code__in=('UAE_ANNUAL', 'KSA_ANNUAL'))
    )
    if lbs.exists():
        supplementary.append(_section_heading_p2('Leave balance (informational)'))
        parts = [f'{lb.leave_type.name}: <b>{lb.remaining_days}</b> d' for lb in lbs]
        supplementary.append(Paragraph(' · '.join(parts), _styles['cell_p2']))

    if supplementary:
        story.append(PageBreak())
        story.extend(supplementary)

    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            '<i>Generated electronically — valid without signature. Confidential. Contact HR for payroll queries.</i>',
            _styles['footer'],
        )
    )

    def _on_page_end(canv, doc_):
        canv.saveState()
        canv.setFont('Helvetica', 7)
        canv.setFillColor(_MUTED)
        pn = canv.getPageNumber()
        canv.drawRightString(A4[0] - _M_R, 10 * mm, f'Page {pn}')
        canv.restoreState()

    doc.build(story, onFirstPage=_on_page_end, onLaterPages=_on_page_end)

    pdf = buf.getvalue()
    buf.close()
    return pdf
