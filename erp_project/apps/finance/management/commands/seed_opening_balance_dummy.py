"""
Seed dummy Opening Balance Lines for testing.

Creates 6 test records covering:
- Customer receivable opening balance
- Vendor payable opening balance
- Bank opening balance
- Cash opening balance
- Advance to supplier
- Advance from customer

Validation: Total Debit = Total Credit (balancing line added to Retained Earnings)

Usage:
    python manage.py seed_opening_balance_dummy
    python manage.py seed_opening_balance_dummy --dry-run
    python manage.py seed_opening_balance_dummy --post
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from datetime import date

from apps.finance.models import (
    Account, AccountType, FiscalYear, BankAccount,
    OpeningBalanceEntry, OpeningBalanceLine
)
from apps.crm.models import Customer
from apps.purchase.models import Vendor


# Ref date: 01/01/2026 (dd/mm/yyyy = 2026-01-01)
REF_DATE = date(2026, 1, 1)

OPENING_LINES = [
    {
        "account_code": "1200",
        "account_name": "Accounts Receivable",
        "customer_name": "ABC Trading LLC",
        "vendor_name": None,
        "bank_account_name": None,
        "ref_number": "OB-REC-001",
        "ref_date": REF_DATE,
        "due_date": date(2026, 1, 31),
        "debit": Decimal("25000.00"),
        "credit": Decimal("0.00"),
        "description": "Customer receivable opening balance - ABC Trading LLC",
    },
    {
        "account_code": "2000",
        "account_name": "Accounts Payable",
        "customer_name": None,
        "vendor_name": "Gulf Supplies LLC",
        "bank_account_name": None,
        "ref_number": "OB-PAY-001",
        "ref_date": REF_DATE,
        "due_date": date(2026, 1, 15),
        "debit": Decimal("0.00"),
        "credit": Decimal("18000.00"),
        "description": "Vendor payable opening balance - Gulf Supplies LLC",
    },
    {
        "account_code": "100001",
        "account_name": "ADCB Bank - Current Account",
        "customer_name": None,
        "vendor_name": None,
        "bank_account_name": "ADCB Current",
        "ref_number": "OB-BANK-001",
        "ref_date": REF_DATE,
        "due_date": REF_DATE,
        "debit": Decimal("150000.00"),
        "credit": Decimal("0.00"),
        "description": "Bank opening balance - ADCB Current",
    },
    {
        "account_code": "1000",
        "account_name": "Cash",
        "customer_name": None,
        "vendor_name": None,
        "bank_account_name": None,
        "ref_number": "OB-CASH-001",
        "ref_date": REF_DATE,
        "due_date": REF_DATE,
        "debit": Decimal("20000.00"),
        "credit": Decimal("0.00"),
        "description": "Cash in hand opening balance",
    },
    {
        "account_code": "2150",
        "account_name": "Advance to Supplier",
        "customer_name": None,
        "vendor_name": "Tech Solutions FZC",
        "bank_account_name": None,
        "ref_number": "OB-ADV-001",
        "ref_date": REF_DATE,
        "due_date": date(2026, 1, 15),
        "debit": Decimal("10000.00"),
        "credit": Decimal("0.00"),
        "description": "Advance paid to supplier - Tech Solutions FZC (Asset)",
    },
    {
        "account_code": "2300",
        "account_name": "Customer Advance",
        "customer_name": "Blue Star Trading",
        "vendor_name": None,
        "bank_account_name": None,
        "ref_number": "OB-ADV-002",
        "ref_date": REF_DATE,
        "due_date": date(2026, 1, 31),
        "debit": Decimal("0.00"),
        "credit": Decimal("12000.00"),
        "description": "Advance received from customer - Blue Star Trading (Liability)",
    },
]


class Command(BaseCommand):
    help = "Seed dummy Opening Balance Lines (6 records + balancing line)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
        parser.add_argument("--post", action="store_true", help="Post entry after creation")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        auto_post = options.get("post", False)

        self.stdout.write(self.style.WARNING("\n" + "=" * 60))
        self.stdout.write(self.style.WARNING("  OPENING BALANCE DUMMY DATA SEEDER"))
        self.stdout.write(self.style.WARNING("=" * 60 + "\n"))

        if dry_run:
            self.stdout.write(self.style.WARNING("** DRY RUN - No changes will be made **\n"))

        try:
            with transaction.atomic():
                fy = self._get_fiscal_year(dry_run)
                accounts, customers, vendors, bank_accounts = self._ensure_entities(dry_run)
                entry = self._create_entry(fy, accounts, customers, vendors, bank_accounts, dry_run)

                if entry and not dry_run:
                    if not entry.is_balanced:
                        raise Exception(
                            f"Entry not balanced! Dr: {entry.total_debit}, Cr: {entry.total_credit}"
                        )
                    if auto_post:
                        admin = self._get_admin_user()
                        if admin:
                            entry.post(admin)
                            self.stdout.write(self.style.SUCCESS(f"  Posted. Journal: {entry.journal_entry.entry_number}"))

                if dry_run:
                    raise Exception("Dry run - rollback")
        except Exception as e:
            if "Dry run" in str(e):
                self.stdout.write(self.style.SUCCESS("\n✓ Dry run completed"))
            else:
                self.stderr.write(self.style.ERROR(f"\n✗ Error: {e}"))
                raise
            return

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("✓ Opening Balance dummy data created"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"  Entry: {entry.entry_number} | Dr: {entry.total_debit:,.2f} = Cr: {entry.total_credit:,.2f}\n")

    def _get_fiscal_year(self, dry_run):
        """Get or create FY 2026."""
        fy = FiscalYear.objects.filter(start_date__year=2026, is_active=True).first()
        if not fy:
            fy = FiscalYear.objects.filter(name__icontains="2026").first()
        if not fy and not dry_run:
            fy = FiscalYear.objects.create(
                name="FY 2026",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                is_active=True,
                is_closed=False,
            )
        return fy

    def _ensure_entities(self, dry_run):
        """Ensure accounts, customers, vendors, bank account exist."""
        from apps.finance.models import AccountType

        # Accounts (IFRS-compliant classification)
        # 2100=Employee Payable, 2200=Salary Payable - do NOT use for advances
        # 2150=Advance to Supplier (Asset), 2300=Customer Advance (Liability)
        accounts_data = [
            ("1000", "Cash", AccountType.ASSET),
            ("1200", "Accounts Receivable", AccountType.ASSET),
            ("2000", "Accounts Payable", AccountType.LIABILITY),
            ("2150", "Advance to Supplier", AccountType.ASSET),
            ("2300", "Customer Advance", AccountType.LIABILITY),
            ("100001", "ADCB Bank - Current Account", AccountType.ASSET),
            ("3100", "Retained Earnings", AccountType.EQUITY),
        ]
        accounts = {}
        for code, name, acc_type in accounts_data:
            acc, _ = Account.objects.get_or_create(code=code, defaults={"name": name, "account_type": acc_type})
            accounts[code] = acc

        # Customers
        customers = {}
        for name in ["ABC Trading LLC", "Blue Star Trading"]:
            c, _ = Customer.objects.get_or_create(
                name=name,
                defaults={"email": f"{name.lower().replace(' ', '.')}@example.com", "status": "active", "customer_type": "customer"},
            )
            customers[name] = c

        # Vendors
        vendors = {}
        for name in ["Gulf Supplies LLC", "Tech Solutions FZC"]:
            v, _ = Vendor.objects.get_or_create(
                name=name,
                defaults={"status": "active"},
            )
            vendors[name] = v

        # Bank account
        bank_acc_gl = accounts.get("100001")
        bank_accounts = {}
        if bank_acc_gl and not dry_run:
            ba, _ = BankAccount.objects.get_or_create(
                name="ADCB Current",
                defaults={
                    "account_number": "100001",
                    "bank_name": "ADCB",
                    "gl_account": bank_acc_gl,
                },
            )
            bank_accounts["ADCB Current"] = ba

        return accounts, customers, vendors, bank_accounts

    def _get_admin_user(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(is_superuser=True, is_active=True).first() or User.objects.filter(is_active=True).first()

    def _create_entry(self, fy, accounts, customers, vendors, bank_accounts, dry_run):
        """Create OpeningBalanceEntry with 6 lines + balancing line."""
        total_dr = sum(d["debit"] for d in OPENING_LINES)
        total_cr = sum(d["credit"] for d in OPENING_LINES)
        diff = total_dr - total_cr

        if dry_run:
            self.stdout.write("  Lines to create:")
            for d in OPENING_LINES:
                self.stdout.write(
                    f"    {d['account_code']} | {d.get('customer_name') or d.get('vendor_name') or '-'} | "
                    f"Dr {d['debit']:>10,.2f} Cr {d['credit']:>10,.2f} | {d['ref_number']}"
                )
            self.stdout.write(f"    --- Balancing: 3100 Retained Earnings | Cr {diff:,.2f}")
            self.stdout.write(f"  Total Dr: {total_dr + 0:,.2f} = Total Cr: {total_cr + diff:,.2f}")
            return None

        entry = OpeningBalanceEntry.objects.create(
            entry_type="gl",
            fiscal_year=fy,
            entry_date=REF_DATE,
            description="Opening Balance Dummy Data - AR, AP, Bank, Cash, Advances",
            notes="Test data for Opening Balance functionality. Ref Date: 01/01/2026.",
        )

        for d in OPENING_LINES:
            account = accounts.get(d["account_code"])
            if not account:
                self.stdout.write(self.style.WARNING(f"  Skip: Account {d['account_code']} not found"))
                continue

            customer = customers.get(d["customer_name"]) if d.get("customer_name") else None
            vendor = vendors.get(d["vendor_name"]) if d.get("vendor_name") else None
            bank_acc = bank_accounts.get(d["bank_account_name"]) if d.get("bank_account_name") else None

            OpeningBalanceLine.objects.create(
                opening_balance_entry=entry,
                account=account,
                description=d["description"],
                customer=customer,
                vendor=vendor,
                bank_account=bank_acc,
                debit=d["debit"],
                credit=d["credit"],
                reference_number=d["ref_number"],
                reference_date=d["ref_date"],
                due_date=d.get("due_date"),
            )

        # Balancing line
        if abs(diff) >= Decimal("0.01"):
            ret_earn = accounts.get("3100")
            if ret_earn:
                if diff > 0:
                    OpeningBalanceLine.objects.create(
                        opening_balance_entry=entry,
                        account=ret_earn,
                        description="Balancing entry - Retained Earnings",
                        debit=Decimal("0.00"),
                        credit=diff,
                        reference_number="OB-BAL-001",
                        reference_date=REF_DATE,
                    )
                else:
                    OpeningBalanceLine.objects.create(
                        opening_balance_entry=entry,
                        account=ret_earn,
                        description="Balancing entry - Retained Earnings",
                        debit=abs(diff),
                        credit=Decimal("0.00"),
                        reference_number="OB-BAL-001",
                        reference_date=REF_DATE,
                    )

        entry.calculate_totals()
        self.stdout.write(f"  Created {entry.entry_number}: {entry.lines.count()} lines | Dr {entry.total_debit:,.2f} = Cr {entry.total_credit:,.2f}")
        return entry
