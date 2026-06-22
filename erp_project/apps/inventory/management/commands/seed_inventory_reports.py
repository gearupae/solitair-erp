"""
Seed dummy inventory data so every inventory report has meaningful rows.

Runs seed_inventory_data (items, stock, movements) then adds:
  - Consumable requests (monthly request / consumption / cost reports)
  - Open purchase orders + in-transit inter-entity transfers (demand vs supply gap)
  - AI forecast cache rows (AI forecast report without OpenAI)
  - Aging-bucket and slow/dead stock scenarios
  - FIFO layer rebuild

Usage:
  python manage.py seed_inventory_reports
  python manage.py seed_inventory_reports --fresh
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.inventory.management.commands.seed_inventory_data import (
    SEED_ITEM_PREFIX,
    SEED_NOTE_TAG,
    SEED_WH_CODE,
    clear_seed_inventory,
    seed_inventory_exists,
)
from apps.inventory.models import (
    Category,
    ConsumableRequest,
    ConsumableRequestItem,
    Item,
    Stock,
    StockMovement,
    Warehouse,
)
from apps.inventory.models_inter_entity import InterEntityTransfer, InterEntityTransferLine
from apps.inventory.models_reporting import InventoryForecast
from apps.inventory.services.fifo_service import rebuild_fifo_layers

User = get_user_model()

SEED_REPORT_TAG = "[inv-reports seed]"
SEED_CR_PREFIX = "SEED-CR-"
SEED_PO_NOTES = f"{SEED_REPORT_TAG} demo PO"
SEED_IET_NOTES = f"{SEED_REPORT_TAG} demo transfer"


def clear_seed_report_extras():
    """Remove report-specific seed rows (not base inventory items)."""
    cr_ids = list(
        ConsumableRequest.objects.filter(remarks__contains=SEED_REPORT_TAG).values_list("id", flat=True)
    )
    if cr_ids:
        ConsumableRequestItem.objects.filter(consumable_request_id__in=cr_ids).delete()
        ConsumableRequest.objects.filter(id__in=cr_ids).delete()

    from apps.purchase.models import PurchaseOrder, PurchaseOrderItem

    po_ids = list(PurchaseOrder.objects.filter(notes__contains=SEED_REPORT_TAG).values_list("id", flat=True))
    if po_ids:
        PurchaseOrderItem.objects.filter(purchase_order_id__in=po_ids).delete()
        PurchaseOrder.objects.filter(id__in=po_ids).delete()

    iet_ids = list(
        InterEntityTransfer.objects.filter(notes__contains=SEED_REPORT_TAG).values_list("id", flat=True)
    )
    if iet_ids:
        InterEntityTransferLine.objects.filter(transfer_id__in=iet_ids).delete()
        InterEntityTransfer.objects.filter(id__in=iet_ids).delete()

    seed_item_ids = list(Item.objects.filter(item_code__startswith=SEED_ITEM_PREFIX).values_list("id", flat=True))
    if seed_item_ids:
        InventoryForecast.objects.filter(item_id__in=seed_item_ids).delete()

    from django.db.models import Q

    extra_items = Item.objects.filter(
        Q(item_code__startswith="SEED-SLOW-") | Q(item_code__startswith="SEED-DEAD-")
    )
    extra_ids = list(extra_items.values_list("id", flat=True))
    if extra_ids:
        StockMovement.objects.filter(item_id__in=extra_ids).delete()
        Stock.objects.filter(item_id__in=extra_ids).delete()
        InventoryForecast.objects.filter(item_id__in=extra_ids).delete()
        extra_items.delete()


class Command(BaseCommand):
    help = "Seed inventory dummy data for all inventory reports (idempotent unless --fresh)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh",
            action="store_true",
            help="Wipe seed-tagged inventory + report extras, then re-seed.",
        )

    def handle(self, *args, **options):
        use_fresh = options["fresh"]
        if seed_inventory_exists() and not use_fresh:
            extras_exist = ConsumableRequest.objects.filter(remarks__contains=SEED_REPORT_TAG).exists()
            if extras_exist:
                admin = User.objects.filter(is_active=True).order_by("id").first()
                wh = Warehouse.objects.filter(code=SEED_WH_CODE).first()
                items = list(Item.objects.filter(item_code__startswith=SEED_ITEM_PREFIX).order_by("item_code")[:12])
                if admin and wh and items and not InterEntityTransfer.objects.filter(notes=SEED_IET_NOTES).exists():
                    transfers = self._seed_in_transit_transfers(items, wh, admin, timezone.localdate())
                    if transfers:
                        self.stdout.write(self.style.SUCCESS(f"Added in-transit transfer ({transfers})"))
                        return
                self.stdout.write(
                    self.style.WARNING(
                        "Inventory report seed already present. Run with --fresh to rebuild."
                    )
                )
                return
            self.stdout.write(self.style.NOTICE("Base inventory seed found; adding report extras only."))
        else:
            if use_fresh:
                clear_seed_report_extras()
                if seed_inventory_exists():
                    clear_seed_inventory()
                    self.stdout.write(self.style.NOTICE("Cleared previous seed inventory."))
            call_command("seed_inventory_data", fresh=use_fresh, verbosity=0)

        users = list(User.objects.filter(is_active=True).order_by("id")[:8])
        if not users:
            self.stderr.write(self.style.ERROR("No active users. Create a user first."))
            return

        admin = users[0]
        today = timezone.localdate()
        random.seed(42)

        with transaction.atomic():
            wh = Warehouse.objects.filter(code=SEED_WH_CODE).first()
            if not wh:
                self.stderr.write(self.style.ERROR("Seed warehouse missing. seed_inventory_data failed?"))
                return

            items = list(Item.objects.filter(item_code__startswith=SEED_ITEM_PREFIX).order_by("item_code"))
            if not items:
                self.stderr.write(self.style.ERROR("No SEED items found."))
                return

            aging = self._seed_aging_scenarios(items, wh, users, today)
            slow_dead = self._seed_slow_dead_scenarios(wh, users, today)
            consumables = self._seed_consumable_requests(items, wh, users, admin, today)
            pos = self._seed_open_purchase_orders(items, admin, today)
            transfers = self._seed_in_transit_transfers(items, wh, admin, today)
            forecasts = self._seed_ai_forecasts(items, today)
            demo_tune = self._tune_ai_demo_scenarios(items, wh, users, admin, today)
            fifo_layers = rebuild_fifo_layers()

        self.stdout.write(self.style.SUCCESS("Inventory report seed complete"))
        self.stdout.write(f"  Aging scenario movements: {aging}")
        self.stdout.write(f"  Slow/dead stock items: {slow_dead}")
        self.stdout.write(f"  Consumable requests: {consumables}")
        self.stdout.write(f"  Open PO lines: {pos}")
        self.stdout.write(f"  In-transit transfers: {transfers}")
        self.stdout.write(f"  AI forecast rows: {forecasts}")
        self.stdout.write(f"  AI demo tuning: {demo_tune}")
        self.stdout.write(f"  FIFO layers: {fifo_layers}")
        self.stdout.write(
            self.style.NOTICE(
                f"Filter reports using warehouse '{wh.name}' or items starting with {SEED_ITEM_PREFIX!r}."
            )
        )

    def _apply_movement(self, *, item, wh, users, d, mt, qty, src, ref, actor_idx=0):
        movement = StockMovement(
            item=item,
            warehouse=wh,
            movement_type=mt,
            source=src,
            quantity=qty,
            unit_cost=item.purchase_price or Decimal("1.00"),
            reference=ref,
            notes=f"{SEED_REPORT_TAG} {SEED_NOTE_TAG}",
            movement_date=d,
            posted=False,
        )
        movement.save()
        StockMovement.objects.filter(pk=movement.pk).update(created_by_id=users[actor_idx % len(users)].id)
        movement.refresh_from_db()
        try:
            movement.update_stock()
        except Exception:
            StockMovement.objects.filter(pk=movement.pk)._raw_delete(movement._state.db)
            raise
        return movement

    def _seed_aging_scenarios(self, items, wh, users, today) -> int:
        """Add receipt-only movements at fixed ages so aging buckets are populated."""
        specs = [
            (items[0], 12, Decimal("25")),   # Fresh 0-30
            (items[1], 40, Decimal("30")),   # Monitor 31-60
            (items[2], 75, Decimal("40")),   # Slow 61-90
            (items[3], 120, Decimal("35")),  # Critical 91-180
            (items[4], 210, Decimal("20")),  # Dead 180+
        ]
        created = 0
        for item, days_ago, qty in specs:
            ref = f"SEED-AGE-{item.item_code}"
            if StockMovement.objects.filter(reference=ref).exists():
                continue
            d = today - timedelta(days=days_ago)
            self._apply_movement(
                item=item,
                wh=wh,
                users=users,
                d=d,
                mt="in",
                qty=qty,
                src="purchase",
                ref=ref,
            )
            created += 1
        return created

    def _seed_slow_dead_scenarios(self, wh, users, today) -> int:
        """Dedicated items with old last movement but stock on hand."""
        cat = Category.objects.filter(code__startswith="SEED-CAT-").first()
        if not cat:
            return 0

        specs = [
            ("SEED-SLOW-001", "Seed Slow-Moving Kit", 95, Decimal("45")),
            ("SEED-DEAD-001", "Seed Dead Stock Pallet", 220, Decimal("60")),
            ("SEED-DEAD-002", "Seed Obsolete Filters", 300, Decimal("30")),
        ]
        created = 0
        for code, name, days_since_move, qty in specs:
            item, was_new = Item.objects.get_or_create(
                item_code=code,
                defaults={
                    "name": name,
                    "description": f"{SEED_REPORT_TAG} {SEED_NOTE_TAG}",
                    "category": cat,
                    "item_type": "product",
                    "status": "active",
                    "purchase_price": Decimal("18.50"),
                    "minimum_stock": Decimal("10"),
                    "unit": "pcs",
                    "is_active": True,
                },
            )
            if not was_new and Stock.objects.filter(item=item, quantity__gt=0).exists():
                continue
            d = today - timedelta(days=days_since_move)
            ref = f"SEED-SD-OB-{code}"
            if not StockMovement.objects.filter(reference=ref).exists():
                self._apply_movement(
                    item=item,
                    wh=wh,
                    users=users,
                    d=d,
                    mt="in",
                    qty=qty,
                    src="opening",
                    ref=ref,
                )
                created += 1
        return created

    def _seed_consumable_requests(self, items, wh, users, admin, today) -> int:
        from apps.hr.models import Department

        from dateutil.relativedelta import relativedelta

        dept = Department.objects.filter(is_active=True).first()
        created = 0

        # Legacy single-item requests for monthly request / consumption / cost reports
        for month_offset in range(6):
            month_start = (today.replace(day=1) - relativedelta(months=month_offset))
            if month_start.month == 12:
                month_end = date(month_start.year + 1, 1, 1)
            else:
                month_end = date(month_start.year, month_start.month + 1, 1)

            for i in range(4):
                user = users[(month_offset + i) % len(users)]
                item = items[(month_offset * 3 + i) % len(items)]
                qty = Decimal(str(random.randint(2, 12)))
                unit_cost = item.purchase_price or Decimal("5.00")
                req_day = month_start + timedelta(days=min(25, 3 + i * 5))
                if req_day >= month_end:
                    req_day = month_start + timedelta(days=2)

                status_roll = (month_offset + i) % 5
                if status_roll == 0:
                    status = "submitted"
                    dispensed_dt = None
                elif status_roll == 1:
                    status = "approved"
                    dispensed_dt = None
                elif status_roll == 2:
                    status = "rejected"
                    dispensed_dt = None
                else:
                    status = "dispensed"
                    dispensed_dt = timezone.make_aware(
                        datetime.combine(req_day + timedelta(days=2), datetime.min.time())
                    )

                ref_key = f"{SEED_CR_PREFIX}{month_start.strftime('%Y%m')}-{i+1:02d}"
                if ConsumableRequest.objects.filter(remarks__contains=ref_key).exists():
                    continue

                cr = ConsumableRequest(
                    request_kind="consumable",
                    requested_by=user,
                    department=dept,
                    priority=random.choice(["low", "medium", "high"]),
                    required_by_date=req_day + timedelta(days=7),
                    item=item,
                    quantity=qty,
                    warehouse=wh,
                    source_warehouse=wh,
                    unit_cost=unit_cost,
                    total_cost=(unit_cost * qty).quantize(Decimal("0.01")),
                    status=status,
                    remarks=f"{SEED_REPORT_TAG} {ref_key}",
                    created_by=user,
                )
                cr.save()
                ConsumableRequest.objects.filter(pk=cr.pk).update(request_date=req_day)
                if status == "dispensed" and dispensed_dt:
                    ConsumableRequest.objects.filter(pk=cr.pk).update(
                        dispensed_date=dispensed_dt,
                        dispensed_by_id=admin.id,
                    )
                created += 1

        # Multi-line pending requests for demand vs supply gap
        pending_specs = [
            ("approved", Decimal("20"), Decimal("0")),
            ("partially_issued", Decimal("30"), Decimal("10")),
            ("submitted", Decimal("15"), Decimal("0")),
        ]
        for idx, (status, qty, issued) in enumerate(pending_specs, start=1):
            ref_key = f"{SEED_CR_PREFIX}GAP-{idx:02d}"
            if ConsumableRequest.objects.filter(remarks__contains=ref_key).exists():
                continue
            cr = ConsumableRequest(
                request_kind="consumable",
                requested_by=admin,
                department=dept,
                priority="high",
                source_warehouse=wh,
                status=status,
                remarks=f"{SEED_REPORT_TAG} {ref_key}",
                created_by=admin,
            )
            cr.save()
            ConsumableRequest.objects.filter(pk=cr.pk).update(request_date=today - timedelta(days=3))
            for line_idx, item in enumerate(items[:3]):
                ConsumableRequestItem.objects.create(
                    consumable_request=cr,
                    item=item,
                    quantity=qty + Decimal(line_idx * 5),
                    qty_approved=qty + Decimal(line_idx * 5),
                    qty_issued=issued,
                )
            created += 1

        return created

    def _seed_open_purchase_orders(self, items, admin, today) -> int:
        from apps.purchase.models import PurchaseOrder, PurchaseOrderItem, Vendor

        vendor = Vendor.objects.filter(status="active").first()
        if not vendor:
            return 0

        created = 0
        specs = [
            ("confirmed", Decimal("100"), Decimal("25")),
            ("partial_received", Decimal("80"), Decimal("50")),
            ("sent", Decimal("60"), Decimal("0")),
        ]
        for idx, (status, ordered, received) in enumerate(specs, start=1):
            note_tag = f"{SEED_PO_NOTES} #{idx}"
            if PurchaseOrder.objects.filter(notes=note_tag).exists():
                continue
            po = PurchaseOrder(
                vendor=vendor,
                order_date=today - timedelta(days=14),
                expected_delivery_date=today + timedelta(days=7),
                status=status,
                notes=note_tag,
                created_by=admin,
            )
            po.save()
            item = items[idx % len(items)]
            PurchaseOrderItem.objects.create(
                purchase_order=po,
                inventory_item=item,
                description=f"{item.item_code} - {item.name}",
                quantity=ordered,
                unit_price=item.purchase_price or Decimal("10.00"),
                quantity_received=received,
            )
            po.calculate_totals()
            created += 1
        return created

    def _tune_ai_demo_scenarios(self, items, wh, users, admin, today) -> int:
        """Tune SEED items for stockout-risk and no-history fallback demos."""
        tuned = 0
        ear_plugs = Item.objects.filter(item_code='SEED-021').first()
        if ear_plugs:
            ear_plugs.minimum_stock = Decimal('20')
            ear_plugs.lead_time_days = 14
            ear_plugs.safety_stock_qty = Decimal('5')
            ear_plugs.save(update_fields=['minimum_stock', 'lead_time_days', 'safety_stock_qty'])
            Stock.objects.filter(item=ear_plugs, warehouse=wh).update(quantity=Decimal('0'))
            if not StockMovement.objects.filter(item=ear_plugs, reference__startswith='SEED-DEMO-ISS').exists():
                self._apply_movement(
                    item=ear_plugs,
                    wh=wh,
                    users=users,
                    d=today - timedelta(days=30),
                    mt='out',
                    qty=Decimal('15'),
                    src='issue',
                    ref='SEED-DEMO-ISS-EAR',
                    actor_idx=0,
                )
            tuned += 1

        for code in ('SEED-019', 'SEED-020', 'SEED-022'):
            item = Item.objects.filter(item_code=code).first()
            if not item:
                continue
            if StockMovement.objects.filter(item=item, movement_type='out').exists():
                continue
            cat_siblings = Item.objects.filter(
                category_id=item.category_id,
                item_code__startswith=SEED_ITEM_PREFIX,
            ).exclude(pk=item.pk)[:3]
            for sib in cat_siblings:
                if StockMovement.objects.filter(item=sib, movement_type='out').exists():
                    self._apply_movement(
                        item=item,
                        wh=wh,
                        users=users,
                        d=today - timedelta(days=45),
                        mt='out',
                        qty=Decimal('2'),
                        src='issue',
                        ref=f'SEED-DEMO-CAT-{item.item_code}',
                        actor_idx=1,
                    )
                    tuned += 1
                    break
        return tuned

    def _seed_in_transit_transfers(self, items, wh, admin, today) -> int:
        from apps.settings_app.models import Company

        companies = list(Company.objects.order_by("id")[:2])
        if len(companies) < 2:
            second, _ = Company.objects.get_or_create(
                name="SEED Demo Entity B",
                defaults={
                    "country": "uae",
                    "base_currency": "AED",
                    "created_by": admin,
                },
            )
            companies = list(Company.objects.order_by("id")[:2])
        if len(companies) < 2:
            return 0

        dest_wh = Warehouse.objects.filter(is_active=True, status="active").exclude(pk=wh.pk).first()
        if not dest_wh:
            dest_wh, _ = Warehouse.objects.get_or_create(
                code="SEED-WH-DEST",
                defaults={
                    "name": "Seed Destination Warehouse",
                    "status": "active",
                    "is_active": True,
                    "created_by": admin,
                },
            )

        note_tag = SEED_IET_NOTES
        if InterEntityTransfer.objects.filter(notes=note_tag).exists():
            return 0

        transfer = InterEntityTransfer(
            source_entity=companies[0],
            source_warehouse=wh,
            destination_entity=companies[1],
            destination_warehouse=dest_wh,
            transfer_date=today - timedelta(days=2),
            status=InterEntityTransfer.STATUS_IN_TRANSIT,
            notes=note_tag,
            created_by=admin,
        )
        transfer.save()
        for item in items[:4]:
            InterEntityTransferLine.objects.create(
                transfer=transfer,
                item=item,
                quantity=Decimal(str(random.randint(5, 20))),
                unit_price=item.purchase_price or Decimal("10.00"),
            )
        return 1

    def _seed_ai_forecasts(self, items, today) -> int:
        created = 0
        for idx, item in enumerate(items[:12]):
            if InventoryForecast.objects.filter(item=item, reasoning__contains=SEED_REPORT_TAG).exists():
                continue
            base = Decimal(str(8 + (idx % 5) * 3))
            InventoryForecast.objects.create(
                item=item,
                forecast_date=today,
                forecast_30=(base * Decimal("1.0")).quantize(Decimal("0.01")),
                forecast_60=(base * Decimal("1.8")).quantize(Decimal("0.01")),
                forecast_90=(base * Decimal("2.5")).quantize(Decimal("0.01")),
                avg_monthly_consumption=(base * Decimal("1.1")).quantize(Decimal("0.01")),
                confidence=random.choice(["low", "medium", "high"]),
                reasoning=f"{SEED_REPORT_TAG} Demo forecast from seeded consumption history.",
                raw_response='{"seed": true}',
                refreshed_at=timezone.now(),
            )
            created += 1
        return created
