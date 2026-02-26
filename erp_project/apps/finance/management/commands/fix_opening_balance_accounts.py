"""
Fix Opening Balance Lines with wrong account classification.

Corrects:
- OB-ADV-001: 2100 Employee Payable → 2150 Advance to Supplier (Asset)
- OB-ADV-002: 2200 Salary Payable → 2300 Customer Advance (Liability)

Usage:
    python manage.py fix_opening_balance_accounts
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.finance.models import Account, AccountType, OpeningBalanceLine


class Command(BaseCommand):
    help = "Fix opening balance lines with incorrect account classification"

    def handle(self, *args, **options):
        self.stdout.write("Fixing Opening Balance account classifications...")

        with transaction.atomic():
            # Ensure correct accounts exist
            acc_2150, _ = Account.objects.get_or_create(
                code="2150",
                defaults={"name": "Advance to Supplier", "account_type": AccountType.ASSET},
            )
            acc_2300, _ = Account.objects.get_or_create(
                code="2300",
                defaults={"name": "Customer Advance", "account_type": AccountType.LIABILITY},
            )

            fixed = 0

            # Fix OB-ADV-001: Advance to supplier (was wrongly on 2100 Employee Payable)
            lines_adv001 = OpeningBalanceLine.objects.filter(
                reference_number="OB-ADV-001",
                account__code="2100",
            )
            for line in lines_adv001:
                line.account = acc_2150
                line.description = "Advance paid to supplier - Tech Solutions FZC (Asset)"
                line.save()
                fixed += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  Fixed OB-ADV-001: 2100 Employee Payable → 2150 Advance to Supplier"
                ))

            # Fix OB-ADV-002: Customer advance (was wrongly on 2200 Salary Payable)
            lines_adv002 = OpeningBalanceLine.objects.filter(
                reference_number="OB-ADV-002",
                account__code="2200",
            )
            for line in lines_adv002:
                line.account = acc_2300
                line.description = "Advance received from customer - Blue Star Trading (Liability)"
                line.save()
                fixed += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  Fixed OB-ADV-002: 2200 Salary Payable → 2300 Customer Advance"
                ))

        if fixed > 0:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Fixed {fixed} opening balance line(s)"))
        else:
            self.stdout.write("  No lines needed fixing (already correct or not found)")
