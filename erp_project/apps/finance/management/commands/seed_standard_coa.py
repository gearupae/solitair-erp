"""
Create the standard Al Najah chart of accounts and core account mappings.

Idempotent: safe to re-run (updates accounts by code, mappings by transaction_type).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.finance.models import Account, AccountCategory, AccountMapping, AccountType


# (code, name, account_type, account_category, extra kwargs)
CHART_OF_ACCOUNTS = [
    # ASSETS
    ('1010', 'Cash in Hand', AccountType.ASSET, AccountCategory.CASH_BANK, {'is_cash_account': True}),
    ('1020', 'Cash at Bank', AccountType.ASSET, AccountCategory.CASH_BANK, {'is_cash_account': True, 'overdraft_allowed': True}),
    ('1100', 'Accounts Receivable', AccountType.ASSET, AccountCategory.TRADE_RECEIVABLES, {}),
    ('1200', 'Inventory Asset', AccountType.ASSET, AccountCategory.INVENTORY, {}),
    ('1300', 'Prepaid Expenses', AccountType.ASSET, AccountCategory.PREPAID, {}),
    ('1310', 'VAT Receivable', AccountType.ASSET, AccountCategory.TAX_RECEIVABLES, {}),
    ('1400', 'Fixed Assets', AccountType.ASSET, AccountCategory.FIXED_ASSETS_OTHER, {}),
    ('1490', 'Accumulated Depreciation', AccountType.ASSET, AccountCategory.ACCUMULATED_DEPRECIATION, {'is_contra_account': True}),
    # LIABILITIES
    ('2100', 'Accounts Payable', AccountType.LIABILITY, AccountCategory.TRADE_PAYABLES, {}),
    ('2200', 'VAT Payable', AccountType.LIABILITY, AccountCategory.TAX_PAYABLES, {}),
    ('2300', 'Accrued Expenses', AccountType.LIABILITY, AccountCategory.ACCRUED_LIABILITIES, {}),
    ('2400', 'Short-Term Loans', AccountType.LIABILITY, AccountCategory.OTHER_CURRENT_LIABILITIES, {}),
    ('2500', 'Long-Term Loans', AccountType.LIABILITY, AccountCategory.LONG_TERM_LIABILITIES, {}),
    # EQUITY
    ('3100', "Owner's Capital", AccountType.EQUITY, AccountCategory.CAPITAL, {}),
    ('3200', 'Retained Earnings', AccountType.EQUITY, AccountCategory.RETAINED_EARNINGS, {}),
    ('3300', 'Drawings', AccountType.EQUITY, AccountCategory.CAPITAL, {'is_contra_account': True}),
    # REVENUE
    ('4100', 'Sales Revenue', AccountType.INCOME, AccountCategory.OPERATING_REVENUE, {}),
    ('4200', 'Service Revenue', AccountType.INCOME, AccountCategory.OPERATING_REVENUE, {}),
    ('4900', 'Other Income', AccountType.INCOME, AccountCategory.OTHER_INCOME, {}),
    # EXPENSES
    ('5100', 'Cost of Goods Sold', AccountType.EXPENSE, AccountCategory.COST_OF_SALES, {}),
    ('5200', 'Salaries & Wages', AccountType.EXPENSE, AccountCategory.SALARY_EXPENSE, {}),
    ('5300', 'Rent Expense', AccountType.EXPENSE, AccountCategory.RENT_EXPENSE, {}),
    ('5400', 'Utilities Expense', AccountType.EXPENSE, AccountCategory.UTILITIES, {}),
    ('5500', 'Marketing & Advertising', AccountType.EXPENSE, AccountCategory.MARKETING, {}),
    ('5600', 'Depreciation Expense', AccountType.EXPENSE, AccountCategory.DEPRECIATION_EXPENSE, {}),
    ('5700', 'Bank Charges', AccountType.EXPENSE, AccountCategory.BANKING_EXPENSE, {}),
    ('5800', 'General & Administrative Expenses', AccountType.EXPENSE, AccountCategory.ADMIN_EXPENSE, {}),
]

# transaction_type -> account code, module
ACCOUNT_MAPPINGS = [
    ('inventory_asset', '1200', 'inventory'),
    ('inventory_cogs', '5100', 'inventory'),
    ('sales_invoice_revenue', '4100', 'sales'),
    ('sales_invoice_receivable', '1100', 'sales'),
    ('customer_receipt_ar_clear', '1100', 'sales'),
    ('vendor_bill_payable', '2100', 'purchase'),
    ('vendor_payment_ap_clear', '2100', 'purchase'),
    ('vat_output', '2200', 'general'),
    ('sales_invoice_vat', '2200', 'sales'),
    ('vat_input', '1310', 'general'),
    ('vendor_bill_vat', '1310', 'purchase'),
    ('customer_receipt', '1020', 'sales'),
    ('vendor_payment', '1020', 'purchase'),
    ('expense_claim_payment', '1020', 'expense_claim'),
    ('payroll_payment', '1020', 'payroll'),
    ('retained_earnings', '3200', 'general'),
    ('bank_charges', '5700', 'banking'),
    ('depreciation_expense', '5600', 'general'),
    ('accumulated_depreciation', '1490', 'general'),
]


class Command(BaseCommand):
    help = 'Create standard chart of accounts and configure core account mappings.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report actions without saving',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        accounts_created = 0
        accounts_updated = 0
        mappings_created = 0
        mappings_updated = 0

        @transaction.atomic
        def run():
            nonlocal accounts_created, accounts_updated, mappings_created, mappings_updated
            account_by_code: dict[str, Account] = {}

            for code, name, acct_type, category, extras in CHART_OF_ACCOUNTS:
                defaults = {
                    'name': name,
                    'account_type': acct_type,
                    'account_category': category,
                    'is_active': True,
                    **extras,
                }
                if dry_run:
                    existing = Account.objects.filter(code=code).first()
                    if existing:
                        accounts_updated += 1
                        account_by_code[code] = existing
                    else:
                        accounts_created += 1
                    continue

                account, created = Account.objects.update_or_create(
                    code=code,
                    defaults=defaults,
                )
                account_by_code[code] = account
                if created:
                    accounts_created += 1
                else:
                    accounts_updated += 1

            for trans_type, acct_code, module in ACCOUNT_MAPPINGS:
                if dry_run:
                    if AccountMapping.objects.filter(transaction_type=trans_type).exists():
                        mappings_updated += 1
                    else:
                        mappings_created += 1
                    continue

                account = account_by_code.get(acct_code)
                if not account:
                    account = Account.objects.get(code=acct_code, is_active=True)

                _, created = AccountMapping.objects.update_or_create(
                    transaction_type=trans_type,
                    defaults={
                        'module': module,
                        'account': account,
                        'is_mandatory': True,
                    },
                )
                if created:
                    mappings_created += 1
                else:
                    mappings_updated += 1

            if dry_run:
                transaction.set_rollback(True)

        run()

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Chart of Accounts: {accounts_created} created, {accounts_updated} updated.'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Account mappings: {mappings_created} created, {mappings_updated} updated.'
        ))
