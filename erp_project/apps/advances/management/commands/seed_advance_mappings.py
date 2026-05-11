"""
Management command: seed_advance_mappings

Creates AccountMapping entries for the Advances module.
Skips entries that already exist.

Usage:
    python manage.py seed_advance_mappings
"""
from django.core.management.base import BaseCommand


MAPPINGS = [
    {
        'transaction_type': 'customer_advance_liability',
        'account_code': '2300',
        'module': 'sales',
        'description': 'Customer Advance — Liability account credited on advance receipt',
    },
    {
        'transaction_type': 'vendor_advance_asset',
        'account_code': '1310',
        'module': 'purchase',
        'description': 'Advance to Vendor — Asset account debited on advance payment',
    },
    {
        'transaction_type': 'vendor_security_deposit',
        'account_code': '1360',
        'module': 'purchase',
        'description': 'Vendor Security Deposit — debited when security cheque is issued',
    },
    {
        'transaction_type': 'security_cheques_payable',
        'account_code': '2360',
        'module': 'purchase',
        'description': 'Security Cheques Payable — credited when security cheque is issued',
    },
]


class Command(BaseCommand):
    help = (
        'Seeds AccountMapping entries for the Advances module. '
        'Run after seed_advance_accounts.'
    )

    def handle(self, *args, **options):
        from apps.finance.models import Account, AccountMapping

        for mapping in MAPPINGS:
            code = mapping['account_code']
            ttype = mapping['transaction_type']

            try:
                account = Account.objects.get(code=code, is_active=True)
            except Account.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f'  ERROR  Account {code} not found. '
                        f'Run seed_advance_accounts first.'
                    )
                )
                continue

            if AccountMapping.objects.filter(transaction_type=ttype).exists():
                existing = AccountMapping.objects.get(transaction_type=ttype)
                self.stdout.write(
                    self.style.WARNING(
                        f'  SKIP  {ttype} — already mapped to {existing.account.code}'
                    )
                )
            else:
                AccountMapping.objects.create(
                    transaction_type=ttype,
                    account=account,
                    module=mapping['module'],
                    description=mapping['description'],
                    is_mandatory=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  CREATED  {ttype} → {code} ({account.name})'
                    )
                )

        self.stdout.write(self.style.SUCCESS('Done.'))
