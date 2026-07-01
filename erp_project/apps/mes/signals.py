"""MES signals — WIP recalc on floor activity (Oracle sync disabled until enabled in settings)."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.mes.models import Part, PartScan
from apps.mes.services.barcode import save_part_barcode_image
from apps.mes.services.wip import recalculate_wip


@receiver(post_save, sender=Part)
def part_barcode_image(sender, instance, created, **kwargs):
    if instance.barcode and (created or not instance.barcode_image):
        save_part_barcode_image(instance)


@receiver(post_save, sender=Part)
def part_wip_sync(sender, instance, **kwargs):
    recalculate_wip(instance.production_order)


@receiver(post_save, sender=PartScan)
def part_scan_wip_sync(sender, instance, created, **kwargs):
    if created:
        recalculate_wip(instance.part.production_order)
