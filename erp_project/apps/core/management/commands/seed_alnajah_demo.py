"""
Seed demo operational data for Al Najah Fire ERP (customers, estimates, projects,
inventory items with groups, vendors, purchase requests/orders).

Safe to re-run: uses DEMO-AN-* identifiers and skips existing rows.

Run on production:
  cd /var/www/alnajahfireerp/erp_project && source ../venv/bin/activate
  python manage.py seed_alnajah_demo
  python manage.py seed_hr_demo   # HR employees (separate idempotent command)
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

SEED_TAG = "DEMO-AN"
SEED_NOTE = "Seeded by seed_alnajah_demo"

CUSTOMERS = [
    ("001", "Emirates Tower Management LLC", "100123456700001", "b2b", "project", ["ff", "fa"]),
    ("002", "Dubai Marina Hotel Group", "100123456700002", "b2b", "amc", ["ff", "em"]),
    ("003", "Al Quoz Industrial Complex", "100123456700003", "b2b", "maintenance", ["fa", "fls"]),
    ("004", "Sharjah Municipality Buildings", "100123456700004", "b2b", "project", ["ff", "mep"]),
    ("005", "Abu Dhabi Mall Operations", "100123456700005", "b2b", "amc", ["ff", "fa", "em"]),
    ("006", "Jumeirah Beach Residence Owners", "100123456700006", "b2b", "project", ["ff"]),
]

PROJECTS = [
    ("001", "001", "Fire Alarm Upgrade – Emirates Tower", "in_progress", "fixed", 285000),
    ("002", "002", "Annual AMC – Dubai Marina Hotel", "in_progress", "fixed", 96000),
    ("003", "003", "Sprinkler System Inspection – Al Quoz", "planning", "time_material", 45000),
    ("004", "004", "Emergency Lighting Fit-out – Sharjah", "in_progress", "milestone", 128000),
    ("005", "005", "Fire Pump Room Maintenance – AD Mall", "planning", "fixed", 72000),
]

ITEM_GROUPS = [
    ("Fire Detection", False),
    ("Fire Suppression", False),
    ("Emergency & Exit", False),
    ("Consumables & Spares", True),
]

ITEMS = [
    ("FD-001", "Smoke Detector – Optical", "Fire Detection", "pcs", 85, 120),
    ("FD-002", "Heat Detector – Fixed 58°C", "Fire Detection", "pcs", 72, 105),
    ("FD-003", "Manual Call Point – Red", "Fire Detection", "pcs", 45, 68),
    ("FS-001", "Sprinkler Head – Upright 68°C", "Fire Suppression", "pcs", 28, 42),
    ("FS-002", "Fire Hose Reel 30m", "Fire Suppression", "pcs", 650, 890),
    ("FS-003", "CO2 Extinguisher 5kg", "Fire Suppression", "pcs", 180, 245),
    ("EE-001", "Emergency Exit Sign – LED", "Emergency & Exit", "pcs", 55, 78),
    ("EE-002", "Emergency Light – Twin Spot", "Emergency & Exit", "pcs", 95, 135),
    ("CS-001", "Fire Sealant Tube 310ml", "Consumables & Spares", "pcs", 12, 18),
    ("CS-002", "Sprinkler Escutcheon Plate", "Consumables & Spares", "pcs", 8, 14),
]

VENDORS = [
    ("001", "Gulf Fire Equipment LLC", "Ahmed Al Rashid", "100987654300001"),
    ("002", "Emirates Safety Supplies", "Sara Mohammed", "100987654300002"),
    ("003", "FirePro Trading FZE", "Khalid Hassan", "100987654300003"),
    ("004", "Al Safe Equipment Co", "Omar Farouk", "100987654300004"),
]

ESTIMATES = [
    ("001", "001", "approved", "commercial", "installation_with_amc", ""),
    ("002", "002", "sent", "restaurants", "amc", ""),
    ("003", "004", "draft", "factories_industries", "maintenance", ""),
]

PR_SPECS = [
    ("001", "001", "approved", "high"),
    ("002", "002", "pending", "medium"),
    ("003", "003", "draft", "low"),
]

PO_SPECS = [
    ("001", "001", "001", "confirmed"),
    ("002", "002", "002", "sent"),
]

SEED_WH_CODE = f"{SEED_TAG}-WH-MAIN"

# Opening qty per demo item (code suffix → quantity)
STOCK_QTY = {
    "FD-001": Decimal("85"),
    "FD-002": Decimal("62"),
    "FD-003": Decimal("40"),
    "FS-001": Decimal("120"),
    "FS-002": Decimal("8"),
    "FS-003": Decimal("25"),
    "EE-001": Decimal("55"),
    "EE-002": Decimal("30"),
    "CS-001": Decimal("200"),
    "CS-002": Decimal("150"),
}


class Command(BaseCommand):
    help = "Seed Al Najah demo data: customers, projects, estimates, items/groups, vendors, PR/PO"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-hr",
            action="store_true",
            help="Do not run seed_hr_demo after operational seed",
        )
        parser.add_argument(
            "--stock-only",
            action="store_true",
            help="Only seed warehouse opening stock for inventory items",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        today = date.today()
        admin = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_active=True).first()
        if not admin:
            self.stderr.write(self.style.ERROR("No active user found."))
            return

        if options["stock_only"]:
            n = self._seed_stock(admin, today)
            self.stdout.write(self.style.SUCCESS(f"\nStock seed complete: {n} opening movements applied"))
            return

        tax_code = self._ensure_tax_code()

        counts = {}
        counts["customers"] = self._seed_customers(admin)
        counts["projects"] = self._seed_projects(admin, today)
        counts["item_groups"], counts["items"] = self._seed_items(tax_code, admin)
        counts["stock_movements"] = self._seed_stock(admin, today)
        counts["estimates"] = self._seed_estimates(admin, today, tax_code)
        counts["vendors"] = self._seed_vendors(admin)
        counts["purchase_requests"] = self._seed_purchase_requests(admin, today)
        counts["purchase_orders"] = self._seed_purchase_orders(admin, today, tax_code)

        self.stdout.write(self.style.SUCCESS("\nOperational demo seed complete:"))
        for key, val in counts.items():
            self.stdout.write(f"  {key}: {val} created")

        if not options["skip_hr"]:
            self.stdout.write("\nRunning seed_hr_demo for HR employees...")
            call_command("seed_hr_demo")

    def _ensure_tax_code(self):
        from apps.finance.models import TaxCode

        code = TaxCode.objects.filter(is_active=True, rate=Decimal("5.00")).first()
        if code:
            return code
        call_command("seed_tax_codes", verbosity=0)
        return TaxCode.objects.filter(is_active=True, rate=Decimal("5.00")).first()

    def _seed_customers(self, admin) -> int:
        from apps.crm.models import Customer

        created = 0
        for seq, name, trn, segment, job_type, scope in CUSTOMERS:
            ref = f"{SEED_TAG}-CUST-{seq}"
            _, was_created = Customer.objects.get_or_create(
                name=f"[{SEED_TAG}] {name}",
                defaults={
                    "email": f"demo.cust{seq}@alnajah.demo",
                    "phone": f"+9714{int(seq):07d}",
                    "company": name,
                    "address": f"{name}, Dubai, UAE",
                    "city": "Dubai",
                    "country": "United Arab Emirates",
                    "trn": trn,
                    "scope": scope,
                    "job_type": job_type,
                    "business_segment": segment,
                    "payment_terms": "Net 30",
                    "credit_limit": Decimal("250000.00"),
                    "status": "active",
                    "customer_type": "customer",
                    "notes": f"{SEED_NOTE} ref {ref}",
                    "created_by": admin,
                },
            )
            if was_created:
                created += 1
        return created

    def _seed_projects(self, admin, today: date) -> int:
        from apps.crm.models import Customer
        from apps.projects.models import Project

        created = 0
        for seq, cust_seq, name, status, billing, value in PROJECTS:
            customer = Customer.objects.filter(name__startswith=f"[{SEED_TAG}]", name__contains=CUSTOMERS[int(cust_seq) - 1][1]).first()
            if not customer:
                customer = Customer.objects.filter(name__startswith=f"[{SEED_TAG}]").order_by("pk").first()

            _, was_created = Project.objects.get_or_create(
                name=f"[{SEED_TAG}] {name}",
                defaults={
                    "description": f"{SEED_NOTE} – fire safety project",
                    "customer": customer,
                    "manager": admin,
                    "status": status,
                    "billing_type": billing,
                    "budget": Decimal(str(int(value * 0.85))),
                    "estimated_cost": Decimal(str(int(value * 0.75))),
                    "contract_value": Decimal(str(value)),
                    "start_date": today - timedelta(days=30),
                    "end_date": today + timedelta(days=180),
                    "created_by": admin,
                },
            )
            if was_created:
                created += 1
        return created

    def _seed_items(self, tax_code, admin) -> tuple[int, int]:
        from apps.inventory.models import Category, Item, ItemGroup

        cat, _ = Category.objects.get_or_create(
            code=f"{SEED_TAG}-CAT-FF",
            defaults={"name": f"[{SEED_TAG}] Fire Safety Products", "description": SEED_NOTE},
        )

        group_map: dict[str, ItemGroup] = {}
        groups_created = 0
        for gname, hide_pdf in ITEM_GROUPS:
            grp, was_created = ItemGroup.objects.get_or_create(
                name=f"[{SEED_TAG}] {gname}",
                defaults={"hide_items_on_pdf": hide_pdf},
            )
            group_map[gname] = grp
            if was_created:
                groups_created += 1

        items_created = 0
        for code_suffix, name, group_name, unit, purchase, selling in ITEMS:
            item_code = f"{SEED_TAG}-{code_suffix}"
            item, was_created = Item.objects.get_or_create(
                item_code=item_code,
                defaults={
                    "name": name,
                    "description": f"{SEED_NOTE} – {name}",
                    "category": cat,
                    "item_type": "product",
                    "status": "active",
                    "unit": unit,
                    "purchase_price": Decimal(str(purchase)),
                    "selling_price": Decimal(str(selling)),
                    "minimum_selling_price": Decimal(str(purchase)),
                    "minimum_stock": Decimal("10"),
                    "tax_code": tax_code,
                    "created_by": admin,
                },
            )
            if was_created:
                items_created += 1
            item.item_groups.set([group_map[group_name]])
        return groups_created, items_created

    def _seed_stock(self, admin, today: date) -> int:
        from apps.inventory.models import Item, Stock, StockMovement, Warehouse

        wh, _ = Warehouse.objects.get_or_create(
            code=SEED_WH_CODE,
            defaults={
                "name": "Al Najah Main Warehouse",
                "address": "Industrial Area, Dubai, UAE",
                "contact_person": "Store Keeper",
                "phone": "+97143334444",
                "status": "active",
                "is_active": True,
                "created_by": admin,
            },
        )

        created = 0
        demo_items = Item.objects.filter(item_code__startswith=f"{SEED_TAG}-", item_type="product", status="active")
        other_items = Item.objects.exclude(item_code__startswith=f"{SEED_TAG}-").filter(
            item_type="product", status="active", is_active=True
        )

        for item in demo_items:
            suffix = item.item_code.removeprefix(f"{SEED_TAG}-")
            qty = STOCK_QTY.get(suffix, Decimal("50"))
            if self._apply_opening_stock(item, wh, qty, admin, today):
                created += 1

        for item in other_items:
            if Stock.objects.filter(item=item, warehouse=wh, quantity__gt=0).exists():
                continue
            if self._apply_opening_stock(item, wh, Decimal("35"), admin, today):
                created += 1

        return created

    def _apply_opening_stock(self, item, warehouse, qty: Decimal, admin, today: date) -> bool:
        from apps.inventory.models import StockMovement

        ref = f"{SEED_TAG}-OB-{item.item_code}"
        if StockMovement.objects.filter(reference=ref).exists():
            return False

        movement = StockMovement.objects.create(
            item=item,
            warehouse=warehouse,
            movement_type="in",
            source="opening",
            quantity=qty,
            unit_cost=item.purchase_price or Decimal("1.00"),
            reference=ref,
            notes=f"Opening balance. {SEED_NOTE}",
            movement_date=today - timedelta(days=30),
            posted=False,
            created_by=admin,
        )
        movement.update_stock()
        return True

    def _seed_estimates(self, admin, today: date, tax_code) -> int:
        from apps.crm.models import Customer
        from apps.inventory.models import Item
        from apps.projects.models import Project
        from apps.sales.models import Estimate, EstimateItem

        created = 0
        line_groups = [
            ("Fire Detection System", ["FD-001", "FD-002", "FD-003"]),
            ("Suppression Equipment", ["FS-001", "FS-002"]),
            ("Emergency Lighting", ["EE-001", "EE-002"]),
        ]

        for seq, cust_seq, status, occupancy, work_type, scope_work in ESTIMATES:
            customer = Customer.objects.filter(name__contains=CUSTOMERS[int(cust_seq) - 1][1]).first()
            if not customer:
                continue

            estimate, was_created = Estimate.objects.get_or_create(
                notes=f"{SEED_NOTE} ref {SEED_TAG}-EST-{seq}",
                customer=customer,
                defaults={
                    "assigned_to": admin,
                    "prepared_by": admin.get_full_name() or admin.username,
                    "type_of_occupancy": occupancy,
                    "type_of_work": work_type,
                    "scope_of_work": scope_work,
                    "date": today - timedelta(days=7),
                    "valid_until": today + timedelta(days=30),
                    "status": status,
                    "client_note": "Demo quotation for fire safety works.",
                    "show_group_totals_on_pdf": True,
                    "created_by": admin,
                },
            )
            if not was_created:
                continue

            created += 1
            sort_order = 0
            for group_name, item_codes in line_groups:
                for code_suffix in item_codes:
                    item = Item.objects.filter(item_code=f"{SEED_TAG}-{code_suffix}").first()
                    if not item:
                        continue
                    EstimateItem.objects.create(
                        estimate=estimate,
                        group_name=group_name,
                        sort_order=sort_order,
                        inventory_item=item,
                        description=item.name,
                        quantity=Decimal("10"),
                        unit_price=item.purchase_price,
                        profit_type="percent",
                        profit_value=Decimal("25"),
                        tax_code=tax_code,
                        is_vat_inclusive=False,
                    )
                    sort_order += 1
            estimate.calculate_totals()
        return created

    def _seed_vendors(self, admin) -> int:
        from apps.purchase.models import Vendor

        created = 0
        for seq, name, contact, trn in VENDORS:
            _, was_created = Vendor.objects.get_or_create(
                name=f"[{SEED_TAG}] {name}",
                defaults={
                    "contact_person": contact,
                    "email": f"vendor{seq}@alnajah.demo",
                    "phone": f"+97150{int(seq):07d}",
                    "address": f"{name}, Industrial Area, Sharjah, UAE",
                    "city": "Sharjah",
                    "trn": trn,
                    "payment_terms": "Net 30",
                    "credit_limit": Decimal("150000.00"),
                    "status": "active",
                    "notes": SEED_NOTE,
                    "created_by": admin,
                },
            )
            if was_created:
                created += 1
        return created

    def _seed_purchase_requests(self, admin, today: date) -> int:
        from apps.hr.models import Department
        from apps.inventory.models import Item
        from apps.purchase.models import PurchaseRequest, PurchaseRequestItem

        dept = Department.objects.filter(code__startswith=SEED_TAG).first()
        created = 0

        pr_items = [
            ("FD-001", Decimal("20"), Decimal("85")),
            ("FS-003", Decimal("15"), Decimal("180")),
            ("CS-001", Decimal("50"), Decimal("12")),
        ]

        for seq, vendor_seq, status, priority in PR_SPECS:
            pr, was_created = PurchaseRequest.objects.get_or_create(
                notes=f"{SEED_NOTE} ref {SEED_TAG}-PR-{seq}",
                defaults={
                    "date": today - timedelta(days=5),
                    "requested_by": admin,
                    "required_by_date": today + timedelta(days=14),
                    "department": dept,
                    "priority": priority,
                    "status": status,
                    "created_by": admin,
                },
            )
            if not was_created:
                continue
            created += 1
            for code_suffix, qty, price in pr_items:
                item = Item.objects.filter(item_code=f"{SEED_TAG}-{code_suffix}").first()
                PurchaseRequestItem.objects.create(
                    purchase_request=pr,
                    inventory_item=item,
                    description=item.name if item else f"Demo item {code_suffix}",
                    quantity=qty,
                    estimated_price=price,
                )
            pr.calculate_total()
        return created

    def _seed_purchase_orders(self, admin, today: date, tax_code) -> int:
        from apps.inventory.models import Item
        from apps.purchase.models import PurchaseOrder, PurchaseOrderItem, PurchaseRequest, Vendor

        created = 0
        po_lines = [
            ("FD-002", Decimal("25"), Decimal("72")),
            ("EE-001", Decimal("30"), Decimal("55")),
            ("FS-001", Decimal("40"), Decimal("28")),
        ]

        for seq, pr_seq, vendor_seq, status in PO_SPECS:
            vendor = Vendor.objects.filter(name__contains=VENDORS[int(vendor_seq) - 1][1]).first()
            pr = PurchaseRequest.objects.filter(notes__contains=f"{SEED_TAG}-PR-{pr_seq}").first()
            if not vendor:
                continue

            po, was_created = PurchaseOrder.objects.get_or_create(
                notes=f"{SEED_NOTE} ref {SEED_TAG}-PO-{seq}",
                vendor=vendor,
                defaults={
                    "purchase_request": pr,
                    "order_date": today - timedelta(days=2),
                    "expected_delivery_date": today + timedelta(days=10),
                    "status": status,
                    "created_by": admin,
                },
            )
            if not was_created:
                continue
            created += 1
            for code_suffix, qty, price in po_lines:
                item = Item.objects.filter(item_code=f"{SEED_TAG}-{code_suffix}").first()
                PurchaseOrderItem.objects.create(
                    purchase_order=po,
                    inventory_item=item,
                    description=item.name if item else f"Demo item {code_suffix}",
                    quantity=qty,
                    unit_price=price,
                    tax_code=tax_code,
                    is_vat_inclusive=False,
                )
            po.calculate_totals()
        return created
