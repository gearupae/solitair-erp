"""QR barcode image generation for MES parts."""

from __future__ import annotations

import io

import qrcode
from django.core.files.base import ContentFile

from apps.mes.models import Part


def generate_part_barcode_image(part: Part) -> bytes:
    """QR encodes the floor barcode string (what scanners type)."""
    img = qrcode.make(part.barcode, border=2)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


def save_part_barcode_image(part: Part) -> None:
    if not part.pk or not part.barcode:
        return
    try:
        raw = generate_part_barcode_image(part)
    except Exception:
        return
    name = f'part_{part.pk}_qr.png'
    part.barcode_image.save(name, ContentFile(raw), save=False)
    Part.objects.filter(pk=part.pk).update(barcode_image=part.barcode_image.name)
