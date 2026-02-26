"""
Seed operational data across all modules and post to accounting.
Creates: Invoices, Vendor Bills, Project Expenses, Payroll, Expense Claims,
Inventory movements, Fixed Assets, Property, Documents, HR data.
Does NOT touch finance module directly - uses each module's post_to_accounting().

Run: python manage.py seed_operational_data
Requires: seed_techflow_data (or customers, projects, vendors, items exist)
"""
from datetime import date, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = "Seed operational data (invoices, bills, payroll, etc.) and post to accounting"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview without saving")

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.admin_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not self.admin_user:
            self.stderr.write(self.style.ERROR("No user found. Create admin user first."))
            return

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Operational Data Seeder – All Modules"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

        try:
            with transaction.atomic():
                self.ensure_prerequisites()
                self.seed_sales_invoices()
                self.seed_vendor_bills()
                self.seed_project_expenses()
                self.seed_hr_and_payroll()
                self.seed_expense_claims()
                self.seed_inventory_postings()
                self.seed_asset_activations()
                self.seed_property_data()
                self.seed_documents()
                self.seed_leave_requests()

                if self.dry_run:
                    self.stdout.write(self.style.WARNING("\nDRY RUN – Rolling back"))
                    raise Exception("Dry run – rollback")
        except Exception as e:
            if "Dry run" not in str(e):
                self.stderr.write(self.style.ERROR(f"Error: {e}"))
                raise

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Operational data seeding completed"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

    def ensure_prerequisites(self):
        """Ensure chart of accounts, account mappings, bank account exist."""
        self.stdout.write("\n📋 Ensuring prerequisites...")
        from apps.finance.models import Account, AccountType, AccountMapping, BankAccount

        # Run setup_account_mappings to ensure all module mappings exist
        from django.core.management import call_command
        call_command("setup_account_mappings", verbosity=0)

        # Minimal chart of accounts if missing
        accounts_data = [
            ("1000", "Cash", AccountType.ASSET),
            ("1100", "Bank - Main", AccountType.ASSET),
            ("1200", "Accounts Receivable", AccountType.ASSET),
            ("1300", "VAT Recoverable", AccountType.ASSET),
            ("1400", "Fixed Assets", AccountType.ASSET),
            ("1401", "Accumulated Depreciation", AccountType.ASSET),
            ("1500", "Inventory", AccountType.ASSET),
            ("2000", "Accounts Payable", AccountType.LIABILITY),
            ("2010", "GRN Clearing", AccountType.LIABILITY),
            ("2100", "VAT Payable", AccountType.LIABILITY),
            ("2200", "Employee Payable", AccountType.LIABILITY),
            ("2300", "Salary Payable", AccountType.LIABILITY),
            ("4000", "Sales Revenue", AccountType.INCOME),
            ("4100", "Rental Income", AccountType.INCOME),
            ("5000", "Cost of Goods Sold", AccountType.EXPENSE),
            ("5100", "Salary Expense", AccountType.EXPENSE),
            ("5200", "Stock Variance", AccountType.EXPENSE),
            ("5300", "Depreciation Expense", AccountType.EXPENSE),
            ("6000", "Project Expenses", AccountType.EXPENSE),
        ]
        for code, name, acc_type in accounts_data:
            Account.objects.get_or_create(code=code, defaults={"name": name, "account_type": acc_type})

        # Account mappings for project_expense (needed for ProjectExpense posting)
        acc_6000 = Account.objects.filter(code="6000").first()
        acc_2000 = Account.objects.filter(code="2000").first()
        if acc_6000 and acc_2000:
            AccountMapping.objects.get_or_create(
                transaction_type="project_expense",
                defaults={"module": "project", "account": acc_6000},
            )
            AccountMapping.objects.get_or_create(
                transaction_type="project_expense_clearing",
                defaults={"module": "project", "account": acc_2000},
            )

        # Bank account for payroll
        bank_acc = Account.objects.filter(code="1100").first()
        if bank_acc and not BankAccount.objects.filter(is_active=True).exists():
            BankAccount.objects.create(
                name="Main Operating Account",
                account_number="ACC001",
                bank_name="TechFlow Bank",
                gl_account=bank_acc,
            )
        self.stdout.write("  Prerequisites OK")

    def seed_sales_invoices(self):
        """Create sales invoices and post to accounting."""
        self.stdout.write("\n💰 Seeding Sales Invoices...")
        from apps.sales.models import Invoice, InvoiceItem
        from apps.crm.models import Customer

        customers = list(Customer.objects.filter(status="active")[:5])
        if not customers:
            self.stdout.write(self.style.WARNING("  No customers – run seed_techflow_data first"))
            return

        invoices_data = [
            (date(2024, 11, 10), "Consulting Services – Q1", 5000, 1),
            (date(2024, 11, 12), "Software Licence – Annual", 12000, 1),
            (date(2024, 11, 15), "Platform Integration", 8500, 1),
            (date(2024, 11, 18), "Support Package", 2400, 1),
        ]
        created = 0
        for inv_date, desc, amount, qty in invoices_data:
            cust = customers[created % len(customers)]
            inv, was_created = Invoice.objects.get_or_create(
                customer=cust,
                invoice_date=inv_date,
                notes=desc,
                defaults={
                    "due_date": inv_date + timedelta(days=30),
                    "status": "draft",
                },
            )
            if was_created:
                InvoiceItem.objects.create(
                    invoice=inv,
                    description=desc,
                    quantity=Decimal(str(qty)),
                    unit_price=Decimal(str(amount)),
                )
                inv.calculate_totals()
                try:
                    inv.post_to_accounting(user=self.admin_user)
                    created += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Post failed: {e}"))
        self.stdout.write(f"  Created & posted {created} invoices")

    def seed_vendor_bills(self):
        """Create vendor bills and post to accounting."""
        self.stdout.write("\n📄 Seeding Vendor Bills...")
        from apps.purchase.models import Vendor, VendorBill, VendorBillItem

        vendors = list(Vendor.objects.filter(status="active")[:5])
        if not vendors:
            self.stdout.write(self.style.WARNING("  No vendors – run seed_techflow_data first"))
            return

        bills_data = [
            (date(2024, 11, 18), "VINV-101", "Office supplies – November", 450, 1),
            (date(2024, 11, 19), "VINV-102", "Cloud hosting – AWS", 1200, 1),
            (date(2024, 11, 20), "VINV-103", "Software subscription – Microsoft", 890, 1),
            (date(2024, 11, 21), "VINV-104", "Consulting fees", 3500, 1),
        ]
        created = 0
        for bill_date, vref, desc, amount, qty in bills_data:
            vendor = vendors[created % len(vendors)]
            bill, was_created = VendorBill.objects.get_or_create(
                vendor=vendor,
                vendor_invoice_number=vref,
                defaults={
                    "bill_date": bill_date,
                    "due_date": bill_date + timedelta(days=30),
                    "status": "draft",
                    "notes": desc,
                },
            )
            if was_created:
                VendorBillItem.objects.create(
                    bill=bill,
                    description=desc,
                    quantity=Decimal(str(qty)),
                    unit_price=Decimal(str(amount)),
                )
                bill.calculate_totals()
                try:
                    bill.post_to_accounting(user=self.admin_user)
                    created += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Post failed: {e}"))
        self.stdout.write(f"  Created & posted {created} vendor bills")

    def seed_project_expenses(self):
        """Create project expenses, approve, and post to accounting."""
        self.stdout.write("\n📋 Seeding Project Expenses...")
        from apps.projects.models import Project, ProjectExpense
        from apps.purchase.models import Vendor

        projects = list(Project.objects.all()[:4])
        vendors = list(Vendor.objects.filter(status="active")[:3])
        if not projects:
            self.stdout.write(self.style.WARNING("  No projects – run seed_techflow_data first"))
            return

        expenses_data = [
            ("Travel – client visit", 1200, "travel"),
            ("Software licence for project", 2500, "equipment"),
            ("Consultant fees", 4000, "subcontract"),
            ("Materials for demo", 850, "material"),
        ]
        created = 0
        for desc, amount, cat in expenses_data:
            proj = projects[created % len(projects)]
            vendor = vendors[created % len(vendors)] if vendors else None
            exp, was_created = ProjectExpense.objects.get_or_create(
                project=proj,
                expense_date=date(2024, 11, 10),
                description=desc,
                defaults={
                    "amount": Decimal(str(amount)),
                    "vat_amount": Decimal("0.00"),
                    "category": cat,
                    "vendor": vendor,
                    "status": "draft",
                },
            )
            if was_created:
                exp.status = "approved"
                exp.approved_by = self.admin_user
                exp.approved_date = timezone.now()
                exp.save(update_fields=["status", "approved_by", "approved_date"])
                try:
                    exp.post_to_accounting(user=self.admin_user)
                    created += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Post failed: {e}"))
        self.stdout.write(f"  Created & posted {created} project expenses")

    def seed_hr_and_payroll(self):
        """Create HR structure, employees, and payroll – post to accounting."""
        self.stdout.write("\n👥 Seeding HR & Payroll...")
        from apps.hr.models import Department, Designation, Employee, Payroll

        dept, _ = Department.objects.get_or_create(code="ENG", defaults={"name": "Engineering"})
        desig, _ = Designation.objects.get_or_create(
            name="Software Engineer", department=dept
        )
        desig_mgr, _ = Designation.objects.get_or_create(
            name="Project Manager", department=dept
        )

        employees_data = [
            ("Sarah", "Chen", "sarah.chen@techflow.io", 5500),
            ("James", "Okafor", "james.o@techflow.io", 5200),
            ("Priya", "Nair", "priya.n@techflow.io", 4800),
        ]
        created = 0
        for fn, ln, email, salary in employees_data:
            emp, was_created = Employee.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": fn,
                    "last_name": ln,
                    "department": dept,
                    "designation": desig_mgr if "Manager" in fn else desig,
                    "date_of_joining": date(2023, 6, 1),
                    "basic_salary": Decimal(str(salary)),
                    "status": "active",
                },
            )
            if was_created:
                payroll_month = date(2024, 11, 1)
                payroll, _ = Payroll.objects.get_or_create(
                    employee=emp,
                    month=payroll_month,
                    defaults={
                        "basic_salary": emp.basic_salary,
                        "allowances": Decimal("500.00"),
                        "deductions": Decimal("200.00"),
                        "status": "draft",
                    },
                )
                payroll.calculate_net()
                try:
                    payroll.post_to_accounting(user=self.admin_user)
                    created += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Payroll post failed: {e}"))
        self.stdout.write(f"  Created {len(employees_data)} employees, posted {created} payrolls")

    def seed_expense_claims(self):
        """Create expense claims, approve, and post to accounting."""
        self.stdout.write("\n📝 Seeding Expense Claims...")
        from apps.purchase.models import ExpenseClaim, ExpenseClaimItem

        claims_data = [
            (date(2024, 11, 5), "Client meeting – London", "meals", 85),
            (date(2024, 11, 8), "Train to Manchester", "transport", 120),
        ]
        created = 0
        for claim_date, desc, cat, amount in claims_data:
            claim, was_created = ExpenseClaim.objects.get_or_create(
                employee=self.admin_user,
                claim_date=claim_date,
                description=desc,
                defaults={"status": "submitted"},
            )
            if was_created:
                ExpenseClaimItem.objects.create(
                    expense_claim=claim,
                    date=claim_date,
                    category=cat,
                    description=desc,
                    amount=Decimal(str(amount)),
                    has_receipt=True,
                )
                claim.calculate_totals()
                claim.status = "approved"
                claim.approved_by = self.admin_user
                claim.approved_date = timezone.now()
                claim.save(update_fields=["status", "approved_by", "approved_date"])
                try:
                    claim.post_approval_journal(user=self.admin_user)
                    created += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Post failed: {e}"))
        self.stdout.write(f"  Created & posted {created} expense claims")

    def seed_inventory_postings(self):
        """Post inventory movements with cost to accounting."""
        self.stdout.write("\n📦 Posting Inventory Movements...")
        from apps.inventory.models import StockMovement

        movements = StockMovement.objects.filter(posted=False, total_cost__gt=0)[:5]
        posted = 0
        for m in movements:
            try:
                m.post_to_accounting(user=self.admin_user)
                posted += 1
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Skip {m.movement_number}: {e}"))
        self.stdout.write(f"  Posted {posted} stock movements")

    def seed_asset_activations(self):
        """Create draft assets and activate (posts acquisition to accounting)."""
        self.stdout.write("\n🏭 Seeding & Activating Fixed Assets...")
        from apps.assets.models import FixedAsset, AssetCategory
        from apps.purchase.models import Vendor

        cat = AssetCategory.objects.filter(code="IT-EQ").first() or AssetCategory.objects.first()
        vendor = Vendor.objects.first()
        if not cat:
            self.stdout.write(self.style.WARNING("  No asset category – run seed_techflow_data first"))
            return

        assets_data = [
            ("New Laptop – Dev", 1800, date(2024, 10, 1)),
            ("Conference Monitor", 450, date(2024, 9, 15)),
        ]
        activated = 0
        for name, cost, acq_date in assets_data:
            asset, created = FixedAsset.objects.get_or_create(
                name=name,
                acquisition_date=acq_date,
                defaults={
                    "category": cat,
                    "acquisition_cost": Decimal(str(cost)),
                    "vendor": vendor,
                    "depreciation_method": "straight_line",
                    "useful_life_years": 3,
                    "status": "draft",
                    "location": "London HQ",
                },
            )
            if asset.status == "draft":
                try:
                    asset.activate(user=self.admin_user)
                    activated += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Skip {asset.asset_number}: {e}"))
        self.stdout.write(f"  Activated {activated} assets")

    def seed_property_data(self):
        """Add property, units, tenants, leases (no accounting post for seed)."""
        self.stdout.write("\n🏢 Seeding Property Data...")
        try:
            from apps.property.models import Property, Unit, Tenant, Lease

            prop, _ = Property.objects.get_or_create(
                name="London HQ Building",
                defaults={
                    "address": "1 TechFlow Way, London",
                    "city": "London",
                    "property_type": "commercial",
                    "total_units": 10,
                },
            )
            unit, _ = Unit.objects.get_or_create(
                property=prop,
                unit_number="101",
                defaults={"floor": "1", "area_sqft": 1500, "unit_type": "office", "status": "available"},
            )
            tenant, _ = Tenant.objects.get_or_create(
                name="Zenith Digital Ltd",
                defaults={"email": "accounts@zenithdigital.co.uk", "phone": "+44 20 7946 0101"},
            )
            Lease.objects.get_or_create(
                unit=unit,
                tenant=tenant,
                defaults={
                    "start_date": date(2024, 1, 1),
                    "end_date": date(2025, 12, 31),
                    "annual_rent": Decimal("60000.00"),
                    "status": "active",
                },
            )
            self.stdout.write("  Property, unit, tenant, lease created")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Property: {e}"))

    def seed_documents(self):
        """Add document types and documents."""
        self.stdout.write("\n📎 Seeding Documents...")
        try:
            from apps.documents.models import DocumentType, Document

            dt, _ = DocumentType.objects.get_or_create(
                name="Trade Licence",
                defaults={"alert_days_before": 90},
            )
            Document.objects.get_or_create(
                document_type=dt,
                entity_type="company",
                entity_name="TechFlow Solutions Ltd",
                document_number="TL-2024-001",
                defaults={
                    "issue_date": date(2024, 1, 1),
                    "expiry_date": date(2025, 12, 31),
                    "notes": "Main trade licence",
                },
            )
            self.stdout.write("  Document types and documents created")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Documents: {e}"))

    def seed_leave_requests(self):
        """Add leave types and leave requests."""
        self.stdout.write("\n🏖️ Seeding Leave Data...")
        try:
            from apps.hr.models import LeaveType, LeaveRequest, Employee

            lt, _ = LeaveType.objects.get_or_create(
                code="ANNUAL",
                defaults={"name": "Annual Leave", "days_allowed": 30, "is_paid": True},
            )
            emp = Employee.objects.first()
            if emp:
                LeaveRequest.objects.get_or_create(
                    employee=emp,
                    leave_type=lt,
                    start_date=date(2024, 12, 23),
                    end_date=date(2024, 12, 27),
                    defaults={"reason": "Year-end holiday", "status": "approved"},
                )
                self.stdout.write("  Leave type and request created")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Leave: {e}"))
