"""
Seed deterministic dummy inventory data for testing reports (items, stock, movements).

Safe by default: skips if SEED-* items already exist unless --fresh is passed.
With --fresh: removes only seed-tagged rows (items, categories, warehouse, storage, movements).
Does not modify finance records; movements are created with posted=False and update_stock()
is called directly (no GL posting).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import (
    Category,
    Item,
    Stock,
    StockMovement,
    StorageLocation,
    Warehouse,
)

User = get_user_model()

SEED_ITEM_PREFIX = "SEED-"
SEED_CAT_PREFIX = "SEED-CAT-"
SEED_WH_CODE = "SEED-WH-DEMO"
SEED_NOTE_TAG = "[inventory seed]"
SEED_STORAGE_PREFIX = "[SEED] "

LOCATIONS = [
    "Shelf A1",
    "Shelf A2",
    "Shelf A3",
    "Rack B1",
    "Rack B2",
    "Storeroom C",
]


@dataclass
class ItemSpec:
    name: str
    category_key: str  # SEED-CAT-* code suffix
    unit: str
    purchase_price: Decimal
    minimum_stock: Decimal
    shelf_idx: int
    stock_profile: str  # low | normal | excess
    brand: str
    warranty_kind: str  # expired | expiring | valid


CATEGORY_DEFS = [
    ("SEED-CAT-ELECTRONICS", "Electronics"),
    ("SEED-CAT-CLEANING", "Cleaning Supplies"),
    ("SEED-CAT-OFFICE", "Office Stationery"),
    ("SEED-CAT-TOOLS", "Tools"),
    ("SEED-CAT-SAFETY", "Safety Equipment"),
]

ITEM_DEFS: list[ItemSpec] = [
    ItemSpec("USB-C Hub 7-Port", "SEED-CAT-ELECTRONICS", "pcs", Decimal("45.00"), Decimal("40"), 0, "low", "TechPro", "expiring"),
    ItemSpec("Wireless Mouse M320", "SEED-CAT-ELECTRONICS", "pcs", Decimal("22.50"), Decimal("30"), 1, "normal", "LogiTech", "valid"),
    ItemSpec("HDMI Cable 2m", "SEED-CAT-ELECTRONICS", "pcs", Decimal("8.99"), Decimal("100"), 2, "excess", "CableCo", "valid"),
    ItemSpec("Laptop Stand Aluminium", "SEED-CAT-ELECTRONICS", "pcs", Decimal("65.00"), Decimal("15"), 0, "low", "ErgoDesk", "expired"),
    ItemSpec("Webcam 1080p", "SEED-CAT-ELECTRONICS", "pcs", Decimal("55.00"), Decimal("20"), 3, "normal", "VisionCam", "expiring"),
    ItemSpec("Floor Cleaner 5L", "SEED-CAT-CLEANING", "btl", Decimal("12.40"), Decimal("24"), 4, "normal", "CleanMax", "valid"),
    ItemSpec("Microfiber Mop Pack", "SEED-CAT-CLEANING", "pk", Decimal("18.00"), Decimal("50"), 5, "excess", "SwiffPro", "valid"),
    ItemSpec("Disinfectant Spray 750ml", "SEED-CAT-CLEANING", "pcs", Decimal("6.25"), Decimal("60"), 2, "low", "SafeSpray", "expired"),
    ItemSpec("Trash Bags Heavy 100L", "SEED-CAT-CLEANING", "rl", Decimal("14.80"), Decimal("40"), 1, "normal", "BagMaster", "expiring"),
    ItemSpec("Paper Towels 6-roll", "SEED-CAT-CLEANING", "pk", Decimal("9.99"), Decimal("80"), 3, "excess", "SoftRoll", "valid"),
    ItemSpec("Ballpoint Pens Box (50)", "SEED-CAT-OFFICE", "bx", Decimal("11.00"), Decimal("25"), 0, "normal", "WriteRight", "valid"),
    ItemSpec("A4 Paper Ream 80gsm", "SEED-CAT-OFFICE", "rm", Decimal("6.50"), Decimal("100"), 2, "low", "PaperMill", "expiring"),
    ItemSpec("Sticky Notes Assorted", "SEED-CAT-OFFICE", "pk", Decimal("4.20"), Decimal("70"), 4, "excess", "MemoStick", "valid"),
    ItemSpec("Desk Organizer Mesh", "SEED-CAT-OFFICE", "pcs", Decimal("16.75"), Decimal("12"), 5, "normal", "OfficeMate", "expired"),
    ItemSpec("Stapler Heavy Duty", "SEED-CAT-OFFICE", "pcs", Decimal("13.20"), Decimal("18"), 1, "low", "BindPro", "valid"),
    ItemSpec("Cordless Drill 18V", "SEED-CAT-TOOLS", "pcs", Decimal("120.00"), Decimal("8"), 3, "normal", "DrillKing", "valid"),
    ItemSpec("Socket Wrench Set", "SEED-CAT-TOOLS", "set", Decimal("85.00"), Decimal("6"), 0, "low", "TorqueX", "expiring"),
    ItemSpec("Measuring Tape 8m", "SEED-CAT-TOOLS", "pcs", Decimal("9.50"), Decimal("35"), 2, "excess", "MeasureIt", "valid"),
    ItemSpec("Safety Gloves Nitrile L", "SEED-CAT-SAFETY", "bx", Decimal("22.00"), Decimal("20"), 4, "normal", "ShieldHand", "valid"),
    ItemSpec("Safety Goggles Clear", "SEED-CAT-SAFETY", "pcs", Decimal("7.80"), Decimal("45"), 5, "excess", "EyeSafe", "expired"),
    ItemSpec("Ear Plugs Box 200", "SEED-CAT-SAFETY", "bx", Decimal("35.00"), Decimal("10"), 1, "low", "QuietZone", "valid"),
    ItemSpec("First Aid Kit Medium", "SEED-CAT-SAFETY", "pcs", Decimal("48.00"), Decimal("15"), 0, "normal", "MedReady", "expiring"),
    ItemSpec("Fire Extinguisher 2kg", "SEED-CAT-SAFETY", "pcs", Decimal("95.00"), Decimal("4"), 3, "low", "FlameStop", "valid"),
    ItemSpec("High-Vis Vest XL", "SEED-CAT-SAFETY", "pcs", Decimal("14.25"), Decimal("30"), 2, "excess", "BrightWear", "valid"),
]


def _warranty_dates(today: date, kind: str) -> tuple[date | None, date | None]:
    """Return (purchase_date, warranty_expiry) for warranty report mix."""
    if kind == "expired":
        return today - timedelta(days=800), today - timedelta(days=120)
    if kind == "expiring":
        return today - timedelta(days=300), today + timedelta(days=15)
    return today - timedelta(days=200), today + timedelta(days=500)


def _opening_qty(profile: str) -> Decimal:
    if profile == "low":
        return Decimal("8")
    if profile == "excess":
        return Decimal("400")
    return Decimal("120")


def clear_seed_inventory():
    """Remove only seed-tagged inventory rows (no finance app writes)."""
    seed_items = Item.objects.filter(item_code__startswith=SEED_ITEM_PREFIX)
    seed_ids = list(seed_items.values_list("id", flat=True))
    if seed_ids:
        StockMovement.objects.filter(item_id__in=seed_ids).delete()
        Stock.objects.filter(item_id__in=seed_ids).delete()
    seed_items.delete()
    Category.objects.filter(code__startswith=SEED_CAT_PREFIX).delete()
    Warehouse.objects.filter(code=SEED_WH_CODE).delete()
    StorageLocation.objects.filter(name__startswith=SEED_STORAGE_PREFIX).delete()


def seed_inventory_exists() -> bool:
    return Item.objects.filter(item_code__startswith=SEED_ITEM_PREFIX).exists()


class Command(BaseCommand):
    help = (
        "Seed dummy inventory items, storage locations, warehouse, and stock movements "
        "for testing reports. Skips if seed data exists unless --fresh is used."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh",
            action="store_true",
            help="Remove existing seed-tagged inventory rows and re-seed.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Same as --fresh (wipe seed-tagged rows only, then re-seed).",
        )

    def handle(self, *args, **options):
        use_fresh = options["fresh"] or options["clear"]

        if seed_inventory_exists() and not use_fresh:
            self.stdout.write(
                self.style.WARNING(
                    "Dummy inventory seed already present (items with codes starting with "
                    f"{SEED_ITEM_PREFIX!r}). Run with --fresh to wipe only seed data and re-seed."
                )
            )
            return

        users = list(User.objects.filter(is_active=True).order_by("id")[:10])
        if not users:
            self.stderr.write(self.style.ERROR("No active users found. Create a user before seeding."))
            return

        random.seed(42)
        today = timezone.localdate()

        with transaction.atomic():
            if use_fresh and seed_inventory_exists():
                clear_seed_inventory()
                self.stdout.write(self.style.NOTICE("Cleared previous seed inventory data."))

            wh, _ = Warehouse.objects.get_or_create(
                code=SEED_WH_CODE,
                defaults={
                    "name": "Seed Demo Warehouse",
                    "address": "Demo facility — safe to delete with --fresh",
                    "status": "active",
                    "is_active": True,
                },
            )

            cat_by_code: dict[str, Category] = {}
            for code, name in CATEGORY_DEFS:
                cat, _ = Category.objects.get_or_create(
                    code=code,
                    defaults={"name": name, "description": f"{SEED_NOTE_TAG} {name}"},
                )
                cat_by_code[code] = cat

            loc_by_idx: dict[int, StorageLocation] = {}
            for i, loc_name in enumerate(LOCATIONS):
                full_name = f"{SEED_STORAGE_PREFIX}{loc_name}"
                loc, _ = StorageLocation.objects.get_or_create(
                    name=full_name,
                    defaults={"description": f"{SEED_NOTE_TAG} {loc_name}"},
                )
                loc_by_idx[i] = loc

            items: list[Item] = []
            for n, spec in enumerate(ITEM_DEFS, start=1):
                code = f"{SEED_ITEM_PREFIX}{n:03d}"
                purchase_date, warranty_expiry = _warranty_dates(today, spec.warranty_kind)
                shelf = LOCATIONS[spec.shelf_idx % len(LOCATIONS)]
                barcode = f"SEED-BC{n:06d}"

                item = Item(
                    item_code=code,
                    name=spec.name,
                    description=f"Demo stock for reports. {SEED_NOTE_TAG}",
                    category=cat_by_code[spec.category_key],
                    item_type="product",
                    status="active",
                    purchase_price=spec.purchase_price,
                    selling_price=(spec.purchase_price * Decimal("1.15")).quantize(Decimal("0.01")),
                    unit=spec.unit,
                    minimum_stock=spec.minimum_stock,
                    condition_status="in_store",
                    storage_location_master=loc_by_idx[spec.shelf_idx % len(LOCATIONS)],
                    storage_location=shelf,
                    barcode=barcode,
                    brand=spec.brand,
                    serial_batch_number=f"SN-SEED-{n:04d}",
                    purchase_date=purchase_date,
                    warranty_expiry=warranty_expiry,
                    tax_code=None,
                    vat_rate=Decimal("0.00"),
                    is_active=True,
                )
                item.save()
                items.append(item)

            # Build movement specs: opening balances + scattered activity (chronological apply)
            start = today - timedelta(days=175)
            specs: list[tuple[date, int, str, Decimal, str, str, str, str, str]] = []
            # (date, item_index, movement_type, quantity, source, reference, notes, adj_reason, mover_display)

            for idx, item in enumerate(items):
                open_qty = _opening_qty(ITEM_DEFS[idx].stock_profile)
                specs.append(
                    (
                        start,
                        idx,
                        "in",
                        open_qty,
                        "opening",
                        f"SEED-OB-{item.item_code}",
                        f"Opening balance {SEED_NOTE_TAG}. Moved by: {users[idx % len(users)].get_full_name() or users[idx % len(users)].username}",
                        "",
                        users[idx % len(users)].get_full_name() or users[idx % len(users)].username,
                    )
                )

            move_users = [u.get_full_name() or u.username for u in users]
            ref_seq = 1
            for m in range(52):
                d = start + timedelta(days=random.randint(3, 172))
                idx = random.randint(0, len(items) - 1)
                roll = random.random()
                mover = move_users[m % len(move_users)]
                if roll < 0.36:
                    mt, src, qty = "out", "manual", Decimal(random.randint(1, 14))
                    ref = f"SEED-ISS-{today.year}-{ref_seq:05d}"
                    note = f"Issued to department demo. {SEED_NOTE_TAG} Moved by: {mover}"
                    adj = ""
                elif roll < 0.62:
                    mt, src, qty = "in", "purchase", Decimal(random.randint(15, 85))
                    ref = f"SEED-PO-{today.year}-{ref_seq:05d}"
                    note = f"Goods receipt. {SEED_NOTE_TAG} Moved by: {mover}"
                    adj = ""
                elif roll < 0.78:
                    mt, src, qty = "in", "return", Decimal(random.randint(1, 18))
                    ref = f"SEED-RET-{today.year}-{ref_seq:05d}"
                    note = f"Customer / ward return. {SEED_NOTE_TAG} Moved by: {mover}"
                    adj = ""
                elif roll < 0.90:
                    mt, src, qty = "adjustment_plus", "manual", Decimal(random.randint(1, 14))
                    ref = f"SEED-ADJ+{today.year}-{ref_seq:05d}"
                    note = f"Stock count adjustment (+). {SEED_NOTE_TAG} Moved by: {mover}"
                    adj = "correction"
                else:
                    mt, src, qty = "adjustment_minus", "manual", Decimal(random.randint(1, 8))
                    ref = f"SEED-ADJ-{today.year}-{ref_seq:05d}"
                    note = f"Shrinkage write-down. {SEED_NOTE_TAG} Moved by: {mover}"
                    adj = "shrinkage"
                ref_seq += 1
                specs.append((d, idx, mt, qty, src, ref, note, adj, mover))

            specs.sort(key=lambda s: (s[0], s[1], s[5]))

            movements_created = 0
            for d, idx, mt, qty, src, ref, note, adj, mover_name in specs:
                item = items[idx]
                unit_cost = item.purchase_price or Decimal("1.00")
                if mt in ("out", "adjustment_minus") and unit_cost <= 0:
                    unit_cost = Decimal("1.00")

                q = qty
                applied = False
                while q >= 1 and not applied:
                    movement = StockMovement(
                        item=item,
                        warehouse=wh,
                        movement_type=mt,
                        source=src,
                        quantity=q,
                        unit_cost=unit_cost,
                        reference=ref,
                        notes=note,
                        adjustment_reason=adj,
                        movement_date=d,
                        posted=False,
                        journal_entry=None,
                        to_warehouse=None,
                    )
                    movement.save()
                    actor = users[movements_created % len(users)]
                    StockMovement.objects.filter(pk=movement.pk).update(created_by_id=actor.id)
                    movement.refresh_from_db()
                    try:
                        movement.update_stock()
                        applied = True
                        movements_created += 1
                    except Exception:
                        # Avoid ORM delete cascades when related tables are missing
                        StockMovement.objects.filter(pk=movement.pk)._raw_delete(
                            movement._state.db
                        )
                        if mt in ("out", "adjustment_minus"):
                            q = q // 2
                        else:
                            break
                if not applied and mt not in ("out", "adjustment_minus"):
                    self.stderr.write(self.style.WARNING(f"Skipped movement {ref} ({mt})"))

            cat_names = ", ".join(c.name for c in cat_by_code.values())

        self.stdout.write(self.style.SUCCESS(f"✅ {len(ITEM_DEFS)} items created"))
        self.stdout.write(self.style.SUCCESS(f"✅ {movements_created} stock movements applied"))
        self.stdout.write(self.style.SUCCESS("✅ Warehouse: Seed Demo Warehouse (SEED-WH-DEMO)"))
        self.stdout.write(self.style.SUCCESS(f"✅ Categories: {cat_names}"))
        self.stdout.write(
            self.style.SUCCESS(
                "✅ Locations seeded: "
                + ", ".join(LOCATIONS)
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Date span: {start.isoformat()} → {today.isoformat()} (for report filters)"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "Note: Movements use posted=False and update_stock() only (no GL). "
                f"Remove with: python manage.py seed_inventory_data --fresh"
            )
        )
