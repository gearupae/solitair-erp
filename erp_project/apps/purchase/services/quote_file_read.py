"""Prepare vendor quote attachments for GPT — native text + PDF page images (no OCR)."""
from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 12
MAX_PDF_VISION_PAGES = 8
MAX_EXCEL_ROWS = 200
MIN_TEXT_CHARS = 80
PDF_VISION_DPI = 150


def _pdf_native_text(path: str, *, max_pages: int = MAX_PDF_PAGES) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts = []
        for page in reader.pages[:max_pages]:
            parts.append(page.extract_text() or '')
        return '\n'.join(parts).strip()
    except Exception as exc:
        return f'[PDF could not be read: {exc}]'


def _pdf_page_images_base64(path: str, *, max_pages: int = MAX_PDF_VISION_PAGES) -> list[str]:
    """Render PDF pages as PNG for GPT vision (scanned PDFs without a text layer)."""
    try:
        import fitz
    except ImportError:
        return []

    images: list[str] = []
    try:
        doc = fitz.open(path)
        try:
            matrix = fitz.Matrix(PDF_VISION_DPI / 72, PDF_VISION_DPI / 72)
            for idx, page in enumerate(doc):
                if idx >= max_pages:
                    break
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                images.append(base64.b64encode(pix.tobytes('png')).decode('ascii'))
        finally:
            doc.close()
    except Exception as exc:
        logger.warning('PDF vision render failed for %s: %s', path, exc)
    return images


def _xlsx_text(path: str) -> str:
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


def _xls_text(path: str) -> str:
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


def prepare_quote_file_for_ai(path: str, filename: str = '') -> dict:
    """
    Return {text, images, filename, has_content} for one quote attachment.
    When PDF text is sparse, page images are included so GPT can read the document.
    """
    ext = Path(filename or path).suffix.lower()
    name = filename or Path(path).name

    if ext == '.pdf':
        text = _pdf_native_text(path)
        images: list[str] = []
        if text.startswith('[') and text.endswith(']'):
            images = _pdf_page_images_base64(path)
            text = ''
        elif len(text.strip()) < MIN_TEXT_CHARS:
            images = _pdf_page_images_base64(path)
        has_content = bool(text.strip()) or bool(images)
        return {
            'filename': name,
            'text': text,
            'images': images,
            'has_content': has_content,
        }

    if ext == '.xlsx':
        text = _xlsx_text(path)
        return {
            'filename': name,
            'text': text,
            'images': [],
            'has_content': bool(text.strip()) and not text.startswith('['),
        }

    if ext == '.xls':
        text = _xls_text(path)
        return {
            'filename': name,
            'text': text or '[Legacy .xls file could not be parsed.]',
            'images': [],
            'has_content': bool(text.strip()),
        }

    return {'filename': name, 'text': '', 'images': [], 'has_content': False}
