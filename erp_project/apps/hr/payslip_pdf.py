"""ReportLab payslip PDF generation."""
from __future__ import annotations

import re
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.hr.payroll_allowances import effective_payroll_company
from apps.settings_app.models import CompanySettings


def payslip_number(payroll) -> str:
    raw = (payroll.employee.employee_code or str(payroll.employee_id)).strip().upper().replace(' ', '')
    return f'PS-{payroll.month:%Y-%m}-{raw}'


def build_payslip_pdf(payroll) -> bytes:
    company = CompanySettings.get_settings()
    emp = payroll.employee
    ent = effective_payroll_company(payroll)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(name='Title', parent=styles['Heading2'], fontSize=14, spaceAfter=6)
    body = styles['Normal']

    story = []

    display_name = ent.name if ent else (company.company_name if company else '')
    logo_src = None
    if ent and ent.logo:
        logo_src = ent.logo
    elif company and company.logo:
        logo_src = company.logo

    logo_cell = ''
    if logo_src:
        path = logo_src.path if hasattr(logo_src, 'path') else ''
        if path:
            try:
                from reportlab.platypus import Image

                logo_cell = Image(path, width=3 * cm, height=1.2 * cm)
            except Exception:
                logo_cell = Paragraph(display_name or '', body)

    addr_parts = [display_name]
    if company:
        if company.address and not ent:
            addr_parts.append(company.address.replace('\n', '<br/>'))
        elif ent and ent.address:
            addr_parts.append(ent.address.replace('\n', '<br/>'))
        if company.phone:
            addr_parts.append(f'Tel: {company.phone}')
        if company.email:
            addr_parts.append(company.email)

    right_txt = '<br/>'.join([p for p in addr_parts if p])
    hdr_data = [[logo_cell, Paragraph(right_txt, body)]]
    hdr = Table(hdr_data, colWidths=[4 * cm, 12 * cm])
    hdr.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
    story.append(hdr)
    story.append(Spacer(1, 12))

    story.append(Paragraph(f'<b>Payslip</b> — {payslip_number(payroll)}', title))

    profile = getattr(emp, 'hr_profile', None)
    nat = profile.nationality_display if profile else ''

    loc_display = emp.get_location_display() if hasattr(emp, 'get_location_display') else (emp.location or '-').upper()

    emp_rows = [
        ['Employee', emp.full_name],
        ['Code', emp.employee_code],
        ['Company (entity)', ent.name if ent else '-'],
        ['Location', loc_display],
        ['Department', str(emp.department) if emp.department else '-'],
        ['Designation', str(emp.designation) if emp.designation else '-'],
        ['Date of joining', emp.date_of_joining.strftime('%d/%m/%Y') if emp.date_of_joining else '-'],
        ['Nationality', nat or '-'],
    ]
    t1 = Table(emp_rows, colWidths=[4 * cm, 12 * cm])
    t1.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('GRID', (0, 0), (-1, -1), 0.25, colors.grey)]))
    story.append(t1)
    story.append(Spacer(1, 10))

    from apps.hr.models_extended import AttendanceSummary
    from datetime import date

    month_first = date(payroll.month.year, payroll.month.month, 1)
    summ = AttendanceSummary.objects.filter(employee=emp, month=month_first).first()
    if summ:
        story.append(Paragraph('<b>Attendance breakdown</b>', title))
        from calendar import monthrange

        cal_days = monthrange(payroll.month.year, payroll.month.month)[1]
        wd = summ.total_working_days if getattr(summ, 'total_working_days', None) else '-'
        att_rows = [
            ['Working days (calendar)', str(cal_days)],
            ['Working days (recorded)', str(wd)],
            ['Present', str(summ.total_present)],
            ['Absent', str(summ.total_absent)],
            ['Late', str(summ.total_late)],
            ['Half day', str(summ.total_half_day)],
            ['Overtime hours', str(summ.total_overtime_hours)],
        ]
        t_att = Table(att_rows, colWidths=[6 * cm, 4 * cm])
        t_att.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('GRID', (0, 0), (-1, -1), 0.25, colors.grey)]))
        story.append(t_att)
        story.append(Spacer(1, 10))

    currency = 'SAR' if (emp.location or '').lower() == 'ksa' else 'AED'

    story.append(Paragraph('<b>Earnings</b>', title))
    earn_rows = [['Basic salary', f'{currency} {payroll.basic_salary:.2f}']]
    for ln in payroll.allowance_lines.all().order_by('pk'):
        earn_rows.append([ln.description or ln.code, f'{currency} {ln.amount:.2f}'])
    gross = payroll.basic_salary + payroll.allowances
    earn_rows.append(['Gross', f'{currency} {gross:.2f}'])
    te = Table(earn_rows, colWidths=[8 * cm, 8 * cm])
    te.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('GRID', (0, 0), (-1, -1), 0.25, colors.grey)]))
    story.append(te)
    story.append(Spacer(1, 10))

    story.append(Paragraph('<b>Deductions breakdown</b>', title))
    lines = list(payroll.deduction_lines.all())
    ded_rows = [[ln.label, f'{currency} {ln.amount:.2f}'] for ln in lines]
    if not ded_rows:
        ded_rows = [['—', f'{currency} 0.00']]
    total_ded = payroll.deductions
    ded_rows.append(['Total deductions', f'{currency} {total_ded:.2f}'])
    td = Table(ded_rows, colWidths=[8 * cm, 8 * cm])
    td.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('GRID', (0, 0), (-1, -1), 0.25, colors.grey)]))
    story.append(td)
    story.append(Spacer(1, 10))

    from apps.hr.models_extended import EmployeeAdvance, GratuityRecord, PayrollDeductionLine

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
        story.append(
            Paragraph(
                f'<b>Advance repayment:</b> {currency} {adv_total:.2f} (Remaining: {currency} {rem_sum:.2f})',
                body,
            )
        )
        story.append(Spacer(1, 10))

    loc = (emp.location or 'uae').lower()

    if loc == 'uae':
        story.append(Paragraph('<b>UAE</b>', title))
        iloe_ln = next((x for x in lines if x.code == PayrollDeductionLine.CODE_ILOE), None)
        if iloe_ln:
            story.append(Paragraph(f'ILOE Deduction: {currency} {iloe_ln.amount:.2f}', body))
        grat = GratuityRecord.objects.filter(payroll=payroll).first()
        if grat:
            story.append(
                Paragraph(f'Gratuity provision (informational): {currency} {grat.provision_amount:.2f}', body)
            )
        wps = getattr(payroll, 'wps_record', None)
        if wps:
            st = wps.get_status_display() if hasattr(wps, 'get_status_display') else wps.status
            story.append(Paragraph(f'WPS Status: {st}', body))
        story.append(Spacer(1, 8))

    if loc == 'ksa':
        story.append(Paragraph('<b>KSA</b>', title))
        gosi_emp = next((x for x in lines if x.code == PayrollDeductionLine.CODE_GOSI_EMPLOYEE), None)
        if gosi_emp:
            story.append(Paragraph(f'GOSI employee contribution: {currency} {gosi_emp.amount:.2f}', body))
        erc = list(payroll.employer_contributions.all())
        er_tot = sum((r.amount for r in erc), Decimal('0'))
        if er_tot > 0:
            story.append(Paragraph(f'GOSI employer contribution (informational): {currency} {er_tot:.2f}', body))
        story.append(Spacer(1, 8))

    erc = list(payroll.employer_contributions.all())
    if erc and loc != 'ksa':
        story.append(Paragraph('<b>Employer contributions (informational)</b>', title))
        er_rows = [[r.label, f'{currency} {r.amount:.2f}'] for r in erc]
        ter = Table(er_rows, colWidths=[8 * cm, 8 * cm])
        ter.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('GRID', (0, 0), (-1, -1), 0.25, colors.grey)]))
        story.append(ter)
        story.append(Spacer(1, 10))

    grat = GratuityRecord.objects.filter(payroll=payroll).first()
    if grat and loc != 'uae':
        story.append(
            Paragraph(
                f'<b>Gratuity provision (informational):</b> {currency} {grat.provision_amount:.2f}',
                body,
            )
        )
        story.append(Spacer(1, 8))

    from apps.hr.models import LeaveBalance

    lbs = (
        LeaveBalance.objects.filter(employee=emp, year=payroll.month.year)
        .select_related('leave_type')
        .filter(leave_type__code__in=('UAE_ANNUAL', 'KSA_ANNUAL'))
    )
    if lbs.exists():
        story.append(Paragraph('<b>Leave balance (informational)</b>', title))
        parts = []
        for lb in lbs:
            parts.append(f'{lb.leave_type.name}: {lb.remaining_days} days remaining')
        story.append(Paragraph(' · '.join(parts), body))
        story.append(Spacer(1, 10))

    net_style = ParagraphStyle(name='NetBig', parent=body, fontSize=14, textColor=colors.HexColor('#0d6efd'), leading=18)
    story.append(Paragraph(f'<b>Net salary: {currency} {payroll.net_salary:.2f}</b>', net_style))
    story.append(Spacer(1, 16))
    story.append(
        Paragraph(
            '<i>This is a system-generated payslip. Confidential.</i>',
            styles['Italic'],
        )
    )

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf
