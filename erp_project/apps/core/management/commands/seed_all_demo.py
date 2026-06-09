"""
Seed demo data across all ERP modules (idempotent where possible).

Usage:
  python manage.py seed_all_demo
  python manage.py seed_all_demo --skip-finance-post
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


class Command(BaseCommand):
    help = "Seed demo data across CRM, sales, projects, inventory, purchase, HR, finance, fleet, etc."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-finance-post",
            action="store_true",
            help="Skip posting draft invoices/bills/expenses to accounting",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        admin = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_active=True).first()
        if not admin:
            self.stderr.write(self.style.ERROR("No active user found. Create a superuser first."))
            return

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("GearUp ERP – Full Demo Data Seed"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

        self._ensure_fiscal_years()
        call_command("seed_standard_coa", verbosity=0)
        call_command("setup_account_mappings", verbosity=0)
        call_command("seed_tax_codes", verbosity=0)
        call_command("seed_alnajah_demo", verbosity=1)
        self._seed_asset_categories()
        call_command("seed_operational_data", verbosity=1)
        call_command("seed_inventory_reports", verbosity=1)
        self._seed_consumables(admin)
        self._seed_contracts(admin)
        self._seed_service_requests(admin)
        call_command("seed_fleet_gatepass_demo", verbosity=1)
        call_command("seed_budgets", verbosity=1)

        if not options["skip_finance_post"]:
            self._post_pending_finance(admin)

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Full demo seed complete"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

    def _ensure_fiscal_years(self):
        from apps.finance.models import FiscalYear

        self.stdout.write("\n📅 Ensuring fiscal years...")
        specs = [
            ("FY 2024", date(2024, 1, 1), date(2024, 12, 31)),
            ("FY 2025", date(2025, 1, 1), date(2025, 12, 31)),
            ("FY 2026", date(2026, 1, 1), date(2026, 12, 31)),
        ]
        created = 0
        for name, start, end in specs:
            _, was_created = FiscalYear.objects.get_or_create(
                name=name,
                defaults={"start_date": start, "end_date": end, "is_active": True},
            )
            if was_created:
                created += 1
        self.stdout.write(f"  Fiscal years OK ({created} new)")

    def _seed_asset_categories(self):
        from apps.assets.models import AssetCategory
        from apps.finance.models import Account

        self.stdout.write("\n🏭 Ensuring asset categories...")
        cat_map = {
            "IT Equipment": ("IT-EQ", 3, "1410", "1411"),
            "Office Furniture": ("FUR", 7, "1400", "1401"),
            "Fire Safety Equipment": ("FS-EQ", 5, "1400", "1401"),
        }
        for cat_name, (code, life, asset_acc, accum_acc) in cat_map.items():
            AssetCategory.objects.get_or_create(
                code=code,
                defaults={
                    "name": cat_name,
                    "useful_life_years": life,
                    "depreciation_method": "straight_line",
                    "asset_account": Account.objects.filter(code=asset_acc).first(),
                    "depreciation_expense_account": Account.objects.filter(code="5300").first(),
                    "accumulated_depreciation_account": Account.objects.filter(code=accum_acc).first(),
                },
            )
        self.stdout.write(f"  Categories: {AssetCategory.objects.count()}")

    def _seed_consumables(self, admin):
        from apps.hr.models import Department
        from apps.inventory.models import ConsumableRequest, ConsumableRequestItem, Item, Warehouse
        from apps.projects.models import Project

        self.stdout.write("\n🧴 Seeding consumable requests...")
        dept = Department.objects.filter(code__startswith=SEED_TAG).first()
        project = Project.objects.filter(name__startswith=f"[{SEED_TAG}]").first()
        wh = Warehouse.objects.filter(code__startswith=SEED_TAG).first()
        items = list(Item.objects.filter(item_code__startswith=f"{SEED_TAG}-CS")[:2])
        if not items:
            items = list(Item.objects.filter(status="active", item_type="product")[:2])
        if not items:
            self.stdout.write("  Skipped – no inventory items")
            return

        today = date.today()
        specs = [
            ("consumable", "submitted", "medium"),
            ("consumable", "approved", "high"),
            ("consumable", "draft", "low"),
        ]
        created = 0
        for idx, (kind, status, priority) in enumerate(specs, start=1):
            ref = f"{SEED_TAG}-CR-{idx:03d}"
            cr, was_created = ConsumableRequest.objects.get_or_create(
                remarks=f"Demo consumable request {ref}",
                defaults={
                    "request_kind": kind,
                    "requested_by": admin,
                    "department": dept,
                    "project": project,
                    "priority": priority,
                    "required_by_date": today + timedelta(days=7),
                    "source_warehouse": wh,
                    "status": status,
                    "created_by": admin,
                },
            )
            if not was_created:
                continue
            created += 1
            for item in items:
                ConsumableRequestItem.objects.create(
                    consumable_request=cr,
                    item=item,
                    quantity=Decimal("5"),
                    qty_approved=Decimal("5") if status == "approved" else Decimal("0"),
                )
        self.stdout.write(f"  Created {created} consumable requests")

    def _seed_contracts(self, admin):
        from apps.contracts.models import Contract, ContractType
        from apps.crm.models import Customer

        self.stdout.write("\n📜 Seeding contracts...")
        customer = Customer.objects.filter(name__startswith=f"[{SEED_TAG}]").first()
        if not customer:
            self.stdout.write("  Skipped – no demo customers")
            return

        amc, _ = ContractType.objects.get_or_create(name="AMC")
        svc, _ = ContractType.objects.get_or_create(name="Service Agreement")
        today = date.today()
        specs = [
            ("Annual Fire Alarm AMC", amc, 96000, "active"),
            ("Emergency Lighting Maintenance", svc, 45000, "active"),
            ("Sprinkler Inspection Contract", svc, 28000, "upcoming"),
        ]
        created = 0
        for name, ctype, value, status in specs:
            contract, was_created = Contract.objects.get_or_create(
                name=f"[{SEED_TAG}] {name}",
                customer=customer,
                defaults={
                    "start_date": today - timedelta(days=30),
                    "end_date": today + timedelta(days=335),
                    "contract_value": Decimal(str(value)),
                    "status": status,
                    "description": "Demo contract seeded for GearUp ERP",
                    "created_by": admin,
                },
            )
            if was_created:
                contract.contract_types.add(ctype)
                created += 1
        self.stdout.write(f"  Created {created} contracts")

    def _seed_service_requests(self, admin):
        from apps.hr.models import Department
        from apps.service_request.models import ServiceRequest, ServiceRequestItem

        self.stdout.write("\n🔧 Seeding service requests...")
        dept = Department.objects.filter(code__startswith=SEED_TAG).first()
        today = date.today()
        specs = [
            ("Fire pump maintenance visit", "approved", "high", 2500),
            ("IT support – CCTV review", "pending", "medium", 800),
            ("Generator load test", "draft", "low", 1200),
        ]
        created = 0
        for desc, status, priority, amount in specs:
            sr, was_created = ServiceRequest.objects.get_or_create(
                notes=f"[{SEED_TAG}] {desc}",
                defaults={
                    "date": today - timedelta(days=3),
                    "required_by_date": today + timedelta(days=10),
                    "department": dept,
                    "requested_by": admin,
                    "priority": priority,
                    "status": status,
                    "created_by": admin,
                },
            )
            if not was_created:
                continue
            created += 1
            ServiceRequestItem.objects.create(
                service_request=sr,
                service_description=desc,
                quantity=Decimal("1"),
                unit="visit",
                estimated_unit_cost=Decimal(str(amount)),
            )
            sr.calculate_total()
        self.stdout.write(f"  Created {created} service requests")

    def _post_pending_finance(self, admin):
        self.stdout.write("\n💳 Posting pending finance documents...")
        posted = {"invoices": 0, "bills": 0, "expenses": 0, "payrolls": 0}

        from apps.sales.models import Invoice
        from apps.purchase.models import VendorBill
        from apps.projects.models import ProjectExpense
        from apps.hr.models import Payroll

        for inv in Invoice.objects.filter(status="draft"):
            try:
                inv.post_to_accounting(user=admin)
                posted["invoices"] += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"  Invoice skip: {exc}"))

        for bill in VendorBill.objects.filter(status="draft"):
            try:
                bill.post_to_accounting(user=admin)
                posted["bills"] += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"  Bill skip: {exc}"))

        for exp in ProjectExpense.objects.filter(status="approved", journal_entry__isnull=True):
            try:
                exp.post_to_accounting(user=admin)
                posted["expenses"] += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"  Expense skip: {exc}"))

        for payroll in Payroll.objects.filter(status="draft"):
            try:
                payroll.calculate_net()
                payroll.post_to_accounting(user=admin)
                posted["payrolls"] += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"  Payroll skip: {exc}"))

        self.stdout.write(
            f"  Posted: {posted['invoices']} invoices, {posted['bills']} bills, "
            f"{posted['expenses']} expenses, {posted['payrolls']} payrolls"
        )
