import io
import json

import qrcode
from django.core.files.base import ContentFile
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Item


def build_item_qr_payload(item: Item) -> str:
    location = item.get_storage_shelf_label()
    data = {
        'id': str(item.pk),
        'name': item.name,
        'sku': item.item_code,
        'location': location,
    }
    return json.dumps(data, ensure_ascii=False)


def generate_item_qr_bytes(item: Item) -> bytes:
    payload = build_item_qr_payload(item)
    img = qrcode.make(payload, border=2)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


@receiver(post_save, sender=Item)
def item_regenerate_qr(sender, instance, **kwargs):
    if not instance.pk or instance.item_type != 'product':
        return
    try:
        raw = generate_item_qr_bytes(instance)
    except Exception:
        return
    name = f'item_{instance.pk}_qr.png'
    content = ContentFile(raw, name=name)
    instance.qr_code.save(name, content, save=False)
    Item.objects.filter(pk=instance.pk).update(qr_code=instance.qr_code.name)
