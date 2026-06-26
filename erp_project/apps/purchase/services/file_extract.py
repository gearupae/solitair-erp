"""Extract plain text from uploaded PDF / Excel files (OCR fallback for scans)."""
from __future__ import annotations

from pathlib import Path

from apps.purchase.services.quote_ocr import enrich_pdf_text

MAX_PAGES = 12
MAX_EXCEL_ROWS = 200


def extract_file_text_from_path(path: str, filename: str = '') -> str:
    ext = Path(filename or path).suffix.lower()

    if ext == '.pdf':
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            parts = []
            for page in reader.pages[:MAX_PAGES]:
                parts.append(page.extract_text() or '')
            native = '\n'.join(parts).strip()
            text, _method = enrich_pdf_text(path, native, max_pages=MAX_PAGES)
            return text
        except Exception as exc:
            return f'[PDF could not be read: {exc}]'

    if ext == '.xlsx':
        return _extract_xlsx_text(path)

    if ext == '.xls':
        text = _extract_xls_text(path)
        if text:
            return text
        return '[Legacy .xls file could not be parsed.]'

    return ''


def _extract_xlsx_text(path: str) -> str:
    try:
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows: list[str] = []
        for sheet in wb.worksheets:
            rows.append(f'--- Sheet: {sheet.title} ---')
            for idx, row in enumerate(sheet.iter_rows(values_only=True)):
                if idx >= MAX_EXCEL_ROWS:
                    rows.append('[…truncated…]')
                    break
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    rows.append('\t'.join(cells))
        wb.close()
        return '\n'.join(rows).strip()
    except Exception as exc:
        return f'[Excel could not be read: {exc}]'


def _extract_xls_text(path: str) -> str:
    try:
        import xlrd

        book = xlrd.open_workbook(path)
        rows: list[str] = []
        for sheet in book.sheets():
            rows.append(f'--- Sheet: {sheet.name} ---')
            for rx in range(min(sheet.nrows, MAX_EXCEL_ROWS)):
                cells = []
                for cx in range(sheet.ncols):
                    val = sheet.cell_value(rx, cx)
                    if val is None or val == '':
                        continue
                    cells.append(str(val).strip())
                if cells:
                    rows.append('\t'.join(cells))
        return '\n'.join(rows).strip()
    except ImportError:
        return ''
    except Exception:
        return ''
