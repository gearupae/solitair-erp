"""
Seed TechFlow Solutions Ltd data from JSON specification.
Customers, Projects, Fixed Assets, and Inventory Movements.

Run: python manage.py seed_techflow_data
"""
from datetime import date
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

User = get_user_model()

# JSON data - TechFlow Solutions Ltd
CUSTOMERS_DATA = [
    {"id": "CUST001", "name": "Zenith Digital Ltd", "email": "accounts@zenithdigital.co.uk", "phone": "+44 20 7946 0101", "country": "UK", "currency": "GBP", "vat_number": "GB123456789", "payment_terms": 30, "credit_limit": 10000, "status": "active"},
    {"id": "CUST002", "name": "NovaSpark Technologies", "email": "finance@novaspark.io", "phone": "+44 20 7946 0202", "country": "UK", "currency": "GBP", "vat_number": "GB987654321", "payment_terms": 14, "credit_limit": 25000, "status": "active"},
    {"id": "CUST003", "name": "BluePeak Consulting", "email": "billing@bluepeak.co.uk", "phone": "+44 20 7946 0303", "country": "UK", "currency": "GBP", "vat_number": "GB456789123", "payment_terms": 30, "credit_limit": 15000, "status": "active"},
    {"id": "CUST004", "name": "Orion Systems Inc", "email": "ap@orionsystems.com", "phone": "+1 415 555 0101", "country": "USA", "currency": "USD", "vat_number": None, "payment_terms": 30, "credit_limit": 20000, "status": "active"},
    {"id": "CUST005", "name": "Meridian Group GmbH", "email": "rechnungen@meridian.de", "phone": "+49 30 123 4567", "country": "Germany", "currency": "EUR", "vat_number": "DE345678901", "payment_terms": 14, "credit_limit": 18000, "status": "active"},
    {"id": "CUST006", "name": "Apex Retail Solutions", "email": "finance@apexretail.co.uk", "phone": "+44 20 7946 0606", "country": "UK", "currency": "GBP", "vat_number": "GB654321987", "payment_terms": 30, "credit_limit": 5000, "status": "inactive"},
    {"id": "CUST007", "name": "Cloudify Me Ltd", "email": "accounts@cloudifyme.io", "phone": "+44 161 555 0707", "country": "UK", "currency": "GBP", "vat_number": "GB111222333", "payment_terms": 7, "credit_limit": 8000, "status": "active"},
    {"id": "CUST008", "name": "DataStream Analytics", "email": "billing@datastream.ai", "phone": "+44 20 7946 0808", "country": "UK", "currency": "GBP", "vat_number": "GB444555666", "payment_terms": 30, "credit_limit": 30000, "status": "active"},
]

PROJECTS_DATA = [
    {"id": "PROJ001", "name": "Zenith Digital – Enterprise Onboarding", "customer_id": "CUST001", "type": "billable", "status": "in_progress", "start_date": "2024-11-01", "end_date": "2025-02-28", "budget": 12000, "actual_cost": 8400, "billed_to_date": 6000, "currency": "GBP", "manager": "Sarah Chen", "description": "Full onboarding and custom integration for Zenith Digital enterprise tier"},
    {"id": "PROJ002", "name": "Platform UI Redesign", "customer_id": None, "type": "internal", "status": "in_progress", "start_date": "2024-10-01", "end_date": "2025-03-31", "budget": 35000, "actual_cost": 22000, "billed_to_date": 0, "currency": "GBP", "manager": "James Okafor", "description": "Internal redesign of the customer-facing dashboard and onboarding flow"},
    {"id": "PROJ003", "name": "R&D Tax Credit Documentation", "customer_id": None, "type": "internal", "status": "completed", "start_date": "2024-07-01", "end_date": "2024-09-30", "budget": 5000, "actual_cost": 4200, "billed_to_date": 0, "currency": "GBP", "manager": "Priya Nair", "description": "Compile qualifying R&D activities and costs for HMRC R&D tax credit claim"},
    {"id": "PROJ004", "name": "NovaSpark API Integration", "customer_id": "CUST002", "type": "billable", "status": "completed", "start_date": "2024-08-01", "end_date": "2024-10-31", "budget": 8000, "actual_cost": 7500, "billed_to_date": 8000, "currency": "GBP", "manager": "Sarah Chen", "description": "Custom REST API integration between TechFlow and NovaSpark CRM"},
    {"id": "PROJ005", "name": "Orion Systems US Market Launch Support", "customer_id": "CUST004", "type": "billable", "status": "in_progress", "start_date": "2025-01-01", "end_date": "2025-06-30", "budget": 20000, "actual_cost": 3200, "billed_to_date": 5000, "currency": "USD", "manager": "Tom Bradley", "description": "Dedicated support and localization for US market go-live"},
    {"id": "PROJ006", "name": "DataStream Analytics Custom Reporting Module", "customer_id": "CUST008", "type": "billable", "status": "in_progress", "start_date": "2024-12-01", "end_date": "2025-04-30", "budget": 15000, "actual_cost": 5800, "billed_to_date": 7500, "currency": "GBP", "manager": "James Okafor", "description": "Build bespoke analytics reporting module integrated into TechFlow platform"},
]

ASSETS_DATA = [
    {"id": "AST001", "name": "MacBook Pro 16\" – Sarah Chen", "category": "IT Equipment", "purchase_date": "2023-04-01", "purchase_price": 2499.00, "supplier": "Apple Store", "useful_life_years": 3, "depreciation_method": "straight_line", "accumulated_depreciation": 1666.00, "net_book_value": 833.00, "location": "London HQ", "serial_number": "FVFXQ2HMHV2P", "status": "active"},
    {"id": "AST002", "name": "MacBook Pro 16\" – James Okafor", "category": "IT Equipment", "purchase_date": "2023-04-01", "purchase_price": 2499.00, "supplier": "Apple Store", "useful_life_years": 3, "depreciation_method": "straight_line", "accumulated_depreciation": 1666.00, "net_book_value": 833.00, "location": "London HQ", "serial_number": "FVFXQ2HMHV2Q", "status": "active"},
    {"id": "AST003", "name": "Dell PowerEdge Server – Dev Environment", "category": "IT Infrastructure", "purchase_date": "2022-06-15", "purchase_price": 8500.00, "supplier": "Dell UK", "useful_life_years": 5, "depreciation_method": "straight_line", "accumulated_depreciation": 3825.00, "net_book_value": 4675.00, "location": "Data Centre – Equinix LD8", "serial_number": "DL8X-9922-UK", "status": "active"},
    {"id": "AST004", "name": "Office Fit-Out – London HQ", "category": "Leasehold Improvements", "purchase_date": "2022-04-01", "purchase_price": 45000.00, "supplier": "Interiors by Design Ltd", "useful_life_years": 5, "depreciation_method": "straight_line", "accumulated_depreciation": 27000.00, "net_book_value": 18000.00, "location": "London HQ", "serial_number": None, "status": "active"},
    {"id": "AST005", "name": "Cisco Meraki Network Switch x3", "category": "IT Infrastructure", "purchase_date": "2023-09-01", "purchase_price": 3600.00, "supplier": "CDW UK", "useful_life_years": 4, "depreciation_method": "straight_line", "accumulated_depreciation": 975.00, "net_book_value": 2625.00, "location": "London HQ", "serial_number": "MR-CSCUK-3X", "status": "active"},
    {"id": "AST006", "name": "Proprietary Software Platform – v2.0", "category": "Intangible Asset", "purchase_date": "2023-04-01", "purchase_price": 120000.00, "supplier": "Internal Development", "useful_life_years": 5, "depreciation_method": "straight_line", "accumulated_depreciation": 48000.00, "net_book_value": 72000.00, "location": "N/A", "serial_number": None, "status": "active"},
    {"id": "AST007", "name": "Standing Desk x10", "category": "Office Furniture", "purchase_date": "2022-04-01", "purchase_price": 5000.00, "supplier": "Fully.com", "useful_life_years": 7, "depreciation_method": "straight_line", "accumulated_depreciation": 2143.00, "net_book_value": 2857.00, "location": "London HQ", "serial_number": None, "status": "active"},
    {"id": "AST008", "name": "iPhone 15 Pro – Tom Bradley", "category": "IT Equipment", "purchase_date": "2024-01-15", "purchase_price": 1199.00, "supplier": "Apple Store", "useful_life_years": 2, "depreciation_method": "straight_line", "accumulated_depreciation": 549.54, "net_book_value": 649.46, "location": "Remote – Manchester", "serial_number": "F2LX99XXAB1C", "status": "active"},
]

INVENTORY_MOVEMENTS_DATA = [
    {"id": "INV001", "date": "2024-04-03", "item_code": "HW-LAPTOP-MBP16", "description": "MacBook Pro 16\" – Staff Laptop", "movement_type": "purchase", "quantity": 5, "unit_cost": 2499.00, "total_cost": 12495.00, "reference": "PO-2024-001", "supplier": "Apple Store", "project_id": None, "location": "London HQ – IT Store", "stock_after": 5},
    {"id": "INV002", "date": "2024-04-05", "item_code": "HW-LAPTOP-MBP16", "description": "MacBook Pro 16\" issued to Priya Nair", "movement_type": "issue", "quantity": -1, "unit_cost": 2499.00, "total_cost": 2499.00, "reference": "ISSUE-2024-001", "supplier": None, "project_id": None, "location": "London HQ – IT Store", "stock_after": 4},
    {"id": "INV003", "date": "2024-05-10", "item_code": "HW-LAPTOP-MBP16", "description": "MacBook Pro 16\" issued to new hire – Dev Team", "movement_type": "issue", "quantity": -1, "unit_cost": 2499.00, "total_cost": 2499.00, "reference": "ISSUE-2024-002", "supplier": None, "project_id": None, "location": "London HQ – IT Store", "stock_after": 3},
    {"id": "INV004", "date": "2024-06-01", "item_code": "MERCH-TSHIRT-L", "description": "TechFlow branded T-shirts – Large", "movement_type": "purchase", "quantity": 100, "unit_cost": 8.50, "total_cost": 850.00, "reference": "PO-2024-022", "supplier": "Printful UK", "project_id": None, "location": "London HQ – Storage", "stock_after": 100},
    {"id": "INV005", "date": "2024-06-15", "item_code": "MERCH-TSHIRT-L", "description": "T-shirts distributed at SaaStr London event", "movement_type": "issue", "quantity": -60, "unit_cost": 8.50, "total_cost": 510.00, "reference": "EVENT-2024-SAAS", "supplier": None, "project_id": None, "location": "London HQ – Storage", "stock_after": 40},
    {"id": "INV006", "date": "2024-07-20", "item_code": "SW-LICENCE-ANNUAL", "description": "TechFlow Annual Licence Pack – 10 seats", "movement_type": "purchase", "quantity": 10, "unit_cost": 0.00, "total_cost": 0.00, "reference": "INT-LIC-2024-001", "supplier": "Internal", "project_id": "PROJ001", "location": "Digital – Licence Portal", "stock_after": 10},
    {"id": "INV007", "date": "2024-07-25", "item_code": "SW-LICENCE-ANNUAL", "description": "Licence assigned to Zenith Digital Ltd – PROJ001", "movement_type": "issue", "quantity": -5, "unit_cost": 0.00, "total_cost": 0.00, "reference": "PROJ001-LIC-001", "supplier": None, "project_id": "PROJ001", "location": "Digital – Licence Portal", "stock_after": 5},
    {"id": "INV008", "date": "2024-09-01", "item_code": "HW-MONITOR-27", "description": "LG 27\" 4K Monitor – bulk purchase", "movement_type": "purchase", "quantity": 8, "unit_cost": 349.00, "total_cost": 2792.00, "reference": "PO-2024-045", "supplier": "Scan Computers UK", "project_id": None, "location": "London HQ – IT Store", "stock_after": 8},
    {"id": "INV009", "date": "2024-09-05", "item_code": "HW-MONITOR-27", "description": "Monitors issued to engineering team", "movement_type": "issue", "quantity": -6, "unit_cost": 349.00, "total_cost": 2094.00, "reference": "ISSUE-2024-009", "supplier": None, "project_id": None, "location": "London HQ – IT Store", "stock_after": 2},
    {"id": "INV010", "date": "2024-10-14", "item_code": "OFFICE-SUPPLIES-BOX", "description": "Office supplies – stationery bulk box", "movement_type": "purchase", "quantity": 20, "unit_cost": 24.99, "total_cost": 499.80, "reference": "PO-2024-055", "supplier": "Staples UK", "project_id": None, "location": "London HQ – Storage", "stock_after": 20},
    {"id": "INV011", "date": "2024-10-15", "item_code": "OFFICE-SUPPLIES-BOX", "description": "Monthly office supplies issue to staff", "movement_type": "issue", "quantity": -5, "unit_cost": 24.99, "total_cost": 124.95, "reference": "ISSUE-2024-OCT", "supplier": None, "project_id": None, "location": "London HQ – Storage", "stock_after": 15},
    {"id": "INV012", "date": "2024-11-20", "item_code": "HW-LAPTOP-MBP16", "description": "Laptop returned – damaged screen, written off", "movement_type": "write_off", "quantity": -1, "unit_cost": 2499.00, "total_cost": 2499.00, "reference": "WO-2024-003", "supplier": None, "project_id": None, "location": "London HQ – IT Store", "stock_after": 2},
    {"id": "INV013", "date": "2024-12-01", "item_code": "MERCH-NOTEBOOK-A5", "description": "TechFlow branded A5 notebooks", "movement_type": "purchase", "quantity": 200, "unit_cost": 3.20, "total_cost": 640.00, "reference": "PO-2024-078", "supplier": "Vistaprint UK", "project_id": None, "location": "London HQ – Storage", "stock_after": 200},
    {"id": "INV014", "date": "2024-12-10", "item_code": "MERCH-NOTEBOOK-A5", "description": "Notebooks sent to DataStream Analytics as onboarding gift", "movement_type": "issue", "quantity": -20, "unit_cost": 3.20, "total_cost": 64.00, "reference": "PROJ006-GIFT-001", "supplier": None, "project_id": "PROJ006", "location": "London HQ – Storage", "stock_after": 180},
    {"id": "INV015", "date": "2025-01-08", "item_code": "HW-MONITOR-27", "description": "Stock count adjustment – 1 unit missing", "movement_type": "adjustment", "quantity": -1, "unit_cost": 349.00, "total_cost": 349.00, "reference": "ADJ-2025-001", "supplier": None, "project_id": None, "location": "London HQ – IT Store", "stock_after": 1},
]


def parse_date(s):
    """Parse YYYY-MM-DD string to date."""
    if not s:
        return None
    return date(*map(int, s.split("-")))


def movement_type_map(mt):
    """Map JSON movement_type to StockMovement choices."""
    mapping = {
        "purchase": "in",
        "issue": "out",
        "write_off": "adjustment_minus",
        "adjustment": "adjustment_minus",  # quantity is negative
        "return": "in",
    }
    return mapping.get(mt, "in")


class Command(BaseCommand):
    help = "Seed TechFlow Solutions Ltd data: customers, projects, assets, inventory"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview without saving")

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.admin_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not self.admin_user:
            self.stderr.write(self.style.ERROR("No user found. Create admin user first."))
            return

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("TechFlow Solutions Ltd – Data Seeder"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

        try:
            with transaction.atomic():
                self.setup_chart_of_accounts()
                self.seed_vendors()
                self.seed_customers()
                self.seed_asset_categories()
                self.seed_projects()
                self.seed_fixed_assets()
                self.seed_inventory_items_and_warehouses()
                self.seed_stock_movements()

                if self.dry_run:
                    self.stdout.write(self.style.WARNING("\nDRY RUN – Rolling back"))
                    raise Exception("Dry run – rollback")
        except Exception as e:
            if "Dry run" not in str(e):
                self.stderr.write(self.style.ERROR(f"Error: {e}"))
                raise

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("TechFlow data seeding completed successfully"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

    def setup_chart_of_accounts(self):
        """Ensure required GL accounts exist."""
        self.stdout.write("\n📊 Setting up Chart of Accounts...")
        from apps.finance.models import Account, AccountType

        accounts_data = [
            ("1000", "Cash", AccountType.ASSET),
            ("1100", "Bank - ADCB", AccountType.ASSET),
            ("1200", "Accounts Receivable", AccountType.ASSET),
            ("1300", "VAT Recoverable", AccountType.ASSET),
            ("1400", "Fixed Assets - Furniture", AccountType.ASSET),
            ("1401", "Accumulated Depreciation - Furniture", AccountType.ASSET),
            ("1410", "Fixed Assets - IT Equipment", AccountType.ASSET),
            ("1411", "Accumulated Depreciation - IT Equipment", AccountType.ASSET),
            ("1500", "Inventory", AccountType.ASSET),
            ("2000", "Accounts Payable", AccountType.LIABILITY),
            ("2010", "GRN Clearing", AccountType.LIABILITY),
            ("3000", "Share Capital", AccountType.EQUITY),
            ("4000", "Sales Revenue", AccountType.INCOME),
            ("4500", "Gain on Asset Disposal", AccountType.INCOME),
            ("5000", "Cost of Goods Sold", AccountType.EXPENSE),
            ("5100", "COGS - Products", AccountType.EXPENSE),
            ("5200", "Stock Variance", AccountType.EXPENSE),
            ("5300", "Salary Expense", AccountType.EXPENSE),
            ("5500", "Depreciation Expense", AccountType.EXPENSE),
            ("6000", "Project Expenses", AccountType.EXPENSE),
            ("6500", "Loss on Asset Disposal", AccountType.EXPENSE),
        ]
        created = 0
        for code, name, acc_type in accounts_data:
            _, was_created = Account.objects.get_or_create(
                code=code, defaults={"name": name, "account_type": acc_type}
            )
            if was_created:
                created += 1
        self.stdout.write(f"  Accounts: {Account.objects.count()}")

    def seed_vendors(self):
        """Create vendors referenced by assets and inventory."""
        self.stdout.write("\n🏢 Seeding Vendors...")
        from apps.purchase.models import Vendor

        suppliers = set()
        for a in ASSETS_DATA:
            if a.get("supplier"):
                suppliers.add(a["supplier"])
        for m in INVENTORY_MOVEMENTS_DATA:
            if m.get("supplier"):
                suppliers.add(m["supplier"])

        created = 0
        for name in sorted(suppliers):
            _, was_created = Vendor.objects.get_or_create(
                name=name,
                defaults={
                    "address": f"{name}",
                    "payment_terms": "Net 30",
                    "status": "active",
                },
            )
            if was_created:
                created += 1
        self.stdout.write(f"  Created {created} vendors")

    def seed_customers(self):
        """Seed customers from JSON."""
        self.stdout.write("\n👥 Seeding Customers...")
        from apps.crm.models import Customer

        created = 0
        for c in CUSTOMERS_DATA:
            pt = c.get("payment_terms", 30)
            payment_terms = f"Net {pt}" if isinstance(pt, int) else str(pt)
            obj, was_created = Customer.objects.update_or_create(
                customer_number=c["id"],
                defaults={
                    "name": c["name"],
                    "email": c.get("email") or "",
                    "phone": c.get("phone") or "",
                    "country": c.get("country") or "UK",
                    "trn": c.get("vat_number") or "",
                    "payment_terms": payment_terms,
                    "credit_limit": Decimal(str(c.get("credit_limit", 0))),
                    "status": c.get("status", "active"),
                    "customer_type": "customer",
                },
            )
            if was_created:
                created += 1
        self.stdout.write(f"  Created {created} customers, Total: {Customer.objects.count()}")

    def seed_asset_categories(self):
        """Create asset categories for fixed assets."""
        self.stdout.write("\n📁 Seeding Asset Categories...")
        from apps.assets.models import AssetCategory
        from apps.finance.models import Account

        cat_map = {
            "IT Equipment": ("IT-EQ", 3, "1410", "1411"),
            "IT Infrastructure": ("IT-INF", 5, "1410", "1411"),
            "Leasehold Improvements": ("LEASE", 5, "1400", "1401"),
            "Intangible Asset": ("INTANG", 5, "1410", "1411"),
            "Office Furniture": ("FUR", 7, "1400", "1401"),
        }
        for cat_name, (code, life, asset_acc, accum_acc) in cat_map.items():
            asset_account = Account.objects.filter(code=asset_acc).first()
            accum_account = Account.objects.filter(code=accum_acc).first()
            dep_account = Account.objects.filter(code="5500").first()
            AssetCategory.objects.get_or_create(
                code=code,
                defaults={
                    "name": cat_name,
                    "useful_life_years": life,
                    "depreciation_method": "straight_line",
                    "asset_account": asset_account,
                    "depreciation_expense_account": dep_account,
                    "accumulated_depreciation_account": accum_account,
                },
            )
        self.stdout.write(f"  Categories: {AssetCategory.objects.count()}")

    def seed_projects(self):
        """Seed projects from JSON."""
        self.stdout.write("\n📋 Seeding Projects...")
        from apps.projects.models import Project
        from apps.crm.models import Customer

        customer_map = {c["id"]: Customer.objects.get(customer_number=c["id"]) for c in CUSTOMERS_DATA}
        created = 0
        for p in PROJECTS_DATA:
            customer = customer_map.get(p["customer_id"]) if p.get("customer_id") else None
            _, was_created = Project.objects.update_or_create(
                project_code=p["id"],
                defaults={
                    "name": p["name"],
                    "description": p.get("description") or "",
                    "customer": customer,
                    "manager": self.admin_user,
                    "status": p.get("status", "planning"),
                    "start_date": parse_date(p.get("start_date")),
                    "end_date": parse_date(p.get("end_date")),
                    "billing_type": "fixed" if p.get("type") == "billable" else "time_material",
                    "budget": Decimal(str(p.get("budget", 0))),
                    "contract_value": Decimal(str(p.get("budget", 0))),
                    "total_expenses": Decimal(str(p.get("actual_cost", 0))),
                    "total_billed": Decimal(str(p.get("billed_to_date", 0))),
                },
            )
            if was_created:
                created += 1
        self.stdout.write(f"  Created {created} projects, Total: {Project.objects.count()}")

    def seed_fixed_assets(self):
        """Seed fixed assets from JSON."""
        self.stdout.write("\n🏭 Seeding Fixed Assets...")
        from apps.assets.models import AssetCategory, FixedAsset
        from apps.purchase.models import Vendor

        cat_map = {
            "IT Equipment": "IT-EQ",
            "IT Infrastructure": "IT-INF",
            "Leasehold Improvements": "LEASE",
            "Intangible Asset": "INTANG",
            "Office Furniture": "FUR",
        }
        created = 0
        for a in ASSETS_DATA:
            cat_code = cat_map.get(a["category"], "IT-EQ")
            category = AssetCategory.objects.get(code=cat_code)
            vendor = None
            if a.get("supplier"):
                vendor = Vendor.objects.filter(name=a["supplier"]).first()

            _, was_created = FixedAsset.objects.update_or_create(
                asset_number=a["id"],
                defaults={
                    "name": a["name"],
                    "category": category,
                    "status": a.get("status", "active"),
                    "serial_number": a.get("serial_number") or "",
                    "location": a.get("location") or "",
                    "acquisition_date": parse_date(a["purchase_date"]),
                    "acquisition_cost": Decimal(str(a["purchase_price"])),
                    "vendor": vendor,
                    "depreciation_method": a.get("depreciation_method", "straight_line"),
                    "useful_life_years": a.get("useful_life_years", 5),
                    "accumulated_depreciation": Decimal(str(a.get("accumulated_depreciation", 0))),
                    "book_value": Decimal(str(a.get("net_book_value", 0))),
                },
            )
            if was_created:
                created += 1
        self.stdout.write(f"  Created {created} assets, Total: {FixedAsset.objects.count()}")

    def seed_inventory_items_and_warehouses(self):
        """Create items and warehouses for inventory movements."""
        self.stdout.write("\n📦 Seeding Items & Warehouses...")
        from apps.inventory.models import Item, Warehouse, Category

        # Warehouses from unique locations
        locs = set()
        for m in INVENTORY_MOVEMENTS_DATA:
            loc = m.get("location") or "London HQ – Storage"
            locs.add(loc)

        loc_to_code = {
            "London HQ – IT Store": "WH-IT",
            "London HQ – Storage": "WH-STORAGE",
            "Digital – Licence Portal": "WH-DIGITAL",
        }
        wh_map = {}
        for loc in sorted(locs):
            code = loc_to_code.get(loc, "WH-" + loc[:10].replace(" ", "-").replace("–", "-"))
            wh, _ = Warehouse.objects.get_or_create(
                code=code,
                defaults={"name": loc, "address": loc, "status": "active"},
            )
            wh_map[loc] = wh

        # Items from unique item_codes
        item_codes = set(m["item_code"] for m in INVENTORY_MOVEMENTS_DATA)
        item_descriptions = {m["item_code"]: m["description"] for m in INVENTORY_MOVEMENTS_DATA}
        cat, _ = Category.objects.get_or_create(code="GEN", defaults={"name": "General"})

        item_map = {}
        for code in item_codes:
            desc = item_descriptions.get(code, code)
            item, _ = Item.objects.get_or_create(
                item_code=code,
                defaults={
                    "name": desc,
                    "description": desc,
                    "category": cat,
                    "unit": "pcs",
                    "purchase_price": Decimal("0.00"),
                    "selling_price": Decimal("0.00"),
                },
            )
            item_map[code] = item

        self._wh_map = wh_map
        self._item_map = item_map
        self.stdout.write(f"  Warehouses: {len(wh_map)}, Items: {len(item_map)}")

    def seed_stock_movements(self):
        """Seed stock movements from JSON."""
        self.stdout.write("\n📈 Seeding Stock Movements...")
        from apps.inventory.models import StockMovement

        wh_map = getattr(self, "_wh_map", {})
        item_map = getattr(self, "_item_map", {})
        if not wh_map or not item_map:
            self.seed_inventory_items_and_warehouses()
            wh_map = self._wh_map
            item_map = self._item_map

        created = 0
        for m in INVENTORY_MOVEMENTS_DATA:
            item = item_map.get(m["item_code"])
            warehouse = wh_map.get(m.get("location", "London HQ – Storage"))
            if not item or not warehouse:
                continue

            mt = movement_type_map(m["movement_type"])
            raw_qty = Decimal(str(m["quantity"]))
            # StockMovement: 'in' adds qty, 'out'/'adjustment_minus' subtract qty. Always store positive magnitude.
            qty = abs(raw_qty)

            unit_cost = Decimal(str(m.get("unit_cost", 0)))
            total_cost = Decimal(str(m.get("total_cost", 0)))
            if total_cost == 0 and unit_cost > 0:
                total_cost = unit_cost * qty

            ref = m.get("reference", "")
            mov_date = parse_date(m["date"])
            sm, was_created = StockMovement.objects.get_or_create(
                reference=ref,
                item=item,
                warehouse=warehouse,
                movement_date=mov_date,
                defaults={
                    "movement_type": mt,
                    "quantity": qty,
                    "unit_cost": unit_cost,
                    "total_cost": total_cost,
                    "notes": m.get("description", ""),
                    "source": "manual",
                    "posted": False,
                },
            )
            if was_created:
                created += 1
                try:
                    sm.execute(user=self.admin_user)
                except Exception as ex:
                    self.stdout.write(self.style.WARNING(f"  Skip execute for {ref}: {ex}"))

        self.stdout.write(f"  Created {created} stock movements")
