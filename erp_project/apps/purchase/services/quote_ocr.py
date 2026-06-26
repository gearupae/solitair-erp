"""OCR fallback for scanned PDFs — keeps LLM off image/PDF bytes."""
from __future__ import annotations

import io
import logging
import shutil

logger = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 35
OCR_DPI = 175
MAX_OCR_PAGES = 12


def _ocr_available() -> bool:
    if shutil.which('tesseract') is None:
        return False
    try:
        import pytesseract  # noqa: F401
        import fitz  # noqa: F401
        return True
    except ImportError:
        return False


def _ocr_pdf_page_images(path: str, *, max_pages: int = MAX_OCR_PAGES) -> str:
    import fitz
    import pytesseract
    from PIL import Image

    doc = fitz.open(path)
    parts: list[str] = []
    try:
        for idx, page in enumerate(doc):
            if idx >= max_pages:
                parts.append('[…OCR page limit…]')
                break
            matrix = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes('png')))
            text = (pytesseract.image_to_string(img) or '').strip()
            if text:
                parts.append(text)
    finally:
        doc.close()
    return '\n\n'.join(parts).strip()


def enrich_pdf_text(path: str, native_text: str, *, max_pages: int = MAX_OCR_PAGES) -> tuple[str, str]:
    """
    Return (text, method) where method is native|ocr|native+ocr|empty.
    Runs OCR when native pypdf text is too sparse (typical scanned PDF).
    """
    native = (native_text or '').strip()
    page_guess = max(1, native.count('\f') + 1, min(max_pages, 3))
    if len(native) >= MIN_CHARS_PER_PAGE * page_guess:
        return native, 'native'

    if not _ocr_available():
        if native:
            return native, 'native_sparse'
        return (
            '[Scanned PDF — install tesseract-ocr and pip packages pymupdf pytesseract for OCR]',
            'ocr_unavailable',
        )

    try:
        ocr_text = _ocr_pdf_page_images(path, max_pages=max_pages)
    except Exception as exc:
        logger.warning('OCR failed for %s: %s', path, exc)
        if native:
            return native, 'native_sparse'
        return f'[OCR failed: {exc}]', 'ocr_error'

    if not ocr_text and native:
        return native, 'native_sparse'
    if native and ocr_text:
        return f'{native}\n\n--- OCR ---\n\n{ocr_text}', 'native+ocr'
    return ocr_text or native, 'ocr' if ocr_text else 'empty'
