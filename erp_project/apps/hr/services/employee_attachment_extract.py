"""Extract text / image content from employee HR attachments for AI compliance review."""
from __future__ import annotations

import base64
from pathlib import Path

from apps.hr.models import EmployeeAttachment
from apps.purchase.services.file_extract import extract_file_text_from_path

ALLOWED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.jpg', '.jpeg', '.png', '.webp'}
MAX_TEXT_CHARS = 12_000
IMAGE_MIME = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


def attachment_extension(att: EmployeeAttachment) -> str:
    name = (att.filename or '').strip()
    if not name and att.file:
        name = att.file.name
    return Path(name).suffix.lower()


def extract_attachment_for_ai(att: EmployeeAttachment) -> dict:
    """Return payload for one attachment: extracted text and/or base64 image."""
    filename = (att.filename or '').strip()
    if not filename and att.file:
        filename = Path(att.file.name).name
    filename = filename or f'attachment-{att.pk}'
    ext = Path(filename).suffix.lower()
    label = (att.label or '').strip()
    result = {
        'attachment_id': att.pk,
        'filename': filename,
        'label': label,
        'text': '',
        'image_b64': '',
        'image_mime': '',
    }
    if not att.file:
        result['text'] = '[File missing on disk]'
        return result

    path = att.file.path
    if ext in {'.pdf', '.xlsx', '.xls'}:
        text = extract_file_text_from_path(path, filename)
        result['text'] = (text or '[No extractable text in document]')[:MAX_TEXT_CHARS]
        return result

    if ext in IMAGE_MIME:
        try:
            with att.file.open('rb') as fh:
                raw = fh.read()
            result['image_b64'] = base64.standard_b64encode(raw).decode('ascii')
            result['image_mime'] = IMAGE_MIME[ext]
        except Exception as exc:
            result['text'] = f'[Image could not be read: {exc}]'
        return result

    result['text'] = f'[Unsupported file type: {ext or "unknown"}]'
    return result


def build_attachment_ai_parts(attachments: list[EmployeeAttachment]) -> list[dict]:
    """OpenAI chat content parts for employee document review."""
    parts: list[dict] = []
    for att in attachments:
        extracted = extract_attachment_for_ai(att)
        header = f'--- Employee document: {extracted["filename"]}'
        if extracted.get('label'):
            header += f' ({extracted["label"]})'
        header += ' ---'

        if extracted.get('text'):
            parts.append({
                'type': 'text',
                'text': f'{header}\n{extracted["text"]}',
            })
        elif extracted.get('image_b64'):
            parts.append({'type': 'text', 'text': header})
            parts.append({
                'type': 'image_url',
                'image_url': {
                    'url': f'data:{extracted["image_mime"]};base64,{extracted["image_b64"]}',
                },
            })
        else:
            parts.append({'type': 'text', 'text': f'{header}\n[Empty or unreadable file]'})
    return parts
