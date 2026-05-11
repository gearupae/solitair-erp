"""
Management command: seed_advance_accounts

Creates the four Chart of Accounts entries required by the Advances module
ONLY IF they do not already exist.

Usage:
    python manage.py seed_advance_accounts
"""
from django.core.management.base import BaseCommand


ACCOUNTS_TO_SEED = [
    {
        'code': '1310',
        'name': 'Advance to Vendor',
        'account_type': 'asset',
        'account_category': 'other_current_assets',
        'description': 'Advance payments made to vendors before receiving goods/services.',
        'note': 'Using 1310 because 1300 is reserved for VAT Recoverable.',
    },
    {
        'code': '1360',
        'name': 'Vendor Security Deposit',
        'account_type': 'asset',
        'account_category': 'other_current_assets',
        'description': 'Security deposits placed with vendors in the form of cheques.',
    },
    {
        'code': '2300',
        'name': 'Customer Advance',
        'account_type': 'liability',
        'account_category': 'other_current_liabilities',
        'description': 'Advances received from customers before invoicing. Includes VAT component.',
    },
    {
        'code': '2360',
        'name': 'Security Cheques Payable',
        'account_type': 'liability',
        'account_category': 'other_current_liabilities',
        'description': 'Security cheques issued to vendors, outstanding until encashed or returned.',
    },
]


class Command(BaseCommand):
    help = (
        'Seeds the Chart of Accounts entries required by the Advances module '
        '(1300, 1360, 2300, 2360). Skips any that already exist.'
    )

    def handle(self, *args, **options):
        from apps.finance.models import Account

        created_count = 0
        skipped_count = 0

        for entry in ACCOUNTS_TO_SEED:
            code = entry['code']
            if Account.objects.filter(code=code).exists():
                existing = Account.objects.get(code=code)
                self.stdout.write(
                    self.style.WARNING(
                        f'  SKIP  {code} — already exists as "{existing.name}" '
                        f'({existing.get_account_type_display()})'
                    )
                )
                skipped_count += 1
            else:
                Account.objects.create(
                    code=code,
                    name=entry['name'],
                    account_type=entry['account_type'],
                    account_category=entry['account_category'],
                    description=entry.get('description', ''),
                    is_active=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  CREATED  {code} — {entry["name"]} ({entry["account_type"]})'
                    )
                )
                created_count += 1

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Created: {created_count}, Skipped: {skipped_count}.'
            )
        )

        if skipped_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    'NOTE: Skipped accounts already exist. '
                    'Verify their type/category in Finance → Chart of Accounts '
                    'to ensure they are compatible with Advances module.'
                )
            )
