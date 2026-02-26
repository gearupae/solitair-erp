"""
Management command to create FY 2025 Opening Balance Entry.

Creates an OpeningBalanceEntry with the following lines:
- 1101 Cash on Hand: 37,000 AED (Debit)
- 1102 Bank ADCB Current Account: 50,000 AED (Debit) 
- 1103 Bank ADCB Fixed Deposit: 48,000 AED (Debit)
- 3201 Retained Earnings: 135,000 AED (Credit)

Total: 135,000 AED balanced (Debit = Credit)

Usage:
    python manage.py seed_fy2025_opening_balance
    python manage.py seed_fy2025_opening_balance --dry-run
    python manage.py seed_fy2025_opening_balance --post  (creates and posts immediately)
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from datetime import date

from apps.finance.models import (
    Account, AccountType, FiscalYear, BankAccount,
    OpeningBalanceEntry, OpeningBalanceLine
)


class Command(BaseCommand):
    help = 'Create FY 2025 Opening Balance Entry (Cash, Bank & Retained Earnings)'

    # Opening Balance Lines
    OPENING_LINES = [
        {
            'line': 1,
            'account_code': '1101',
            'account_name': 'Cash on Hand',
            'bank_account_name': None,
            'ref_number': 'OB-2025-001',
            'ref_date': date(2025, 1, 1),
            'due_date': None,
            'debit': Decimal('37000.00'),
            'credit': Decimal('0.00'),
            'description': 'Opening Balance - Cash on Hand (Main Safe: 6,000 + Petty Cash: 4,000 + General Cash: 27,000)',
        },
        {
            'line': 2,
            'account_code': '1102',
            'account_name': 'Bank - ADCB Current Account',
            'bank_account_name': 'ADCB Bank - Current Account',
            'ref_number': 'OB-2025-002',
            'ref_date': date(2025, 1, 1),
            'due_date': None,
            'debit': Decimal('50000.00'),
            'credit': Decimal('0.00'),
            'description': 'Opening Balance - ADCB Current Account',
        },
        {
            'line': 3,
            'account_code': '1103',
            'account_name': 'Bank - ADCB Fixed Deposit',
            'bank_account_name': 'ADCB Bank - Fixed Deposit',
            'ref_number': 'OB-2025-003',
            'ref_date': date(2025, 1, 1),
            'due_date': None,
            'debit': Decimal('48000.00'),
            'credit': Decimal('0.00'),
            'description': 'Opening Balance - ADCB Fixed Deposit',
        },
        {
            'line': 4,
            'account_code': '3201',
            'account_name': 'Retained Earnings',
            'bank_account_name': None,
            'ref_number': 'OB-2025-004',
            'ref_date': date(2025, 1, 1),
            'due_date': None,
            'debit': Decimal('0.00'),
            'credit': Decimal('135000.00'),
            'description': 'Opening Balance - Retained Earnings (Accumulated profits from FY 2024)',
        },
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating'
        )
        parser.add_argument(
            '--post',
            action='store_true',
            help='Automatically post the entry after creation'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-creation even if an FY 2025 opening balance already exists'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        auto_post = options.get('post', False)
        force = options.get('force', False)

        self.stdout.write(self.style.WARNING('\n' + '=' * 60))
        self.stdout.write(self.style.WARNING('  FY 2025 OPENING BALANCE ENTRY'))
        self.stdout.write(self.style.WARNING('=' * 60 + '\n'))

        if dry_run:
            self.stdout.write(self.style.WARNING('** DRY RUN MODE - No changes will be made **\n'))

        try:
            with transaction.atomic():
                # Step 1: Get/verify FY 2025
                fiscal_year = self._get_fiscal_year()

                # Step 2: Check for existing entry
                self._check_existing(fiscal_year, force, dry_run)

                # Step 3: Verify accounts exist
                accounts = self._verify_accounts(dry_run)

                # Step 4: Verify bank accounts
                bank_accounts = self._verify_bank_accounts(dry_run)

                # Step 5: Create the entry
                entry = self._create_entry(fiscal_year, accounts, bank_accounts, dry_run)

                # Step 6: Validate balance
                if not dry_run:
                    self._validate_entry(entry)

                # Step 7: Post if requested
                if auto_post and not dry_run:
                    self._post_entry(entry)

                if dry_run:
                    self.stdout.write(self.style.WARNING('\n[DRY RUN] Rolling back...'))
                    raise Exception('Dry run - rolling back')

        except Exception as e:
            if 'Dry run' in str(e):
                self.stdout.write(self.style.SUCCESS('\n✓ Dry run completed successfully'))
            else:
                self.stdout.write(self.style.ERROR(f'\n✗ Error: {e}'))
                raise
            return

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 60))
        self.stdout.write(self.style.SUCCESS('✓ FY 2025 OPENING BALANCE CREATED SUCCESSFULLY'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(f'\n  Entry Number: {entry.entry_number}')
        self.stdout.write(f'  Entry Type:   {entry.get_entry_type_display()}')
        self.stdout.write(f'  Fiscal Year:  {entry.fiscal_year}')
        self.stdout.write(f'  Entry Date:   {entry.entry_date}')
        self.stdout.write(f'  Status:       {entry.status.upper()}')
        self.stdout.write(f'  Total Debit:  AED {entry.total_debit:,.2f}')
        self.stdout.write(f'  Total Credit: AED {entry.total_credit:,.2f}')
        self.stdout.write(f'  Balanced:     {"✅ YES" if entry.is_balanced else "❌ NO"}')
        
        if entry.status == 'posted':
            self.stdout.write(f'  Journal Entry: {entry.journal_entry.entry_number}')
        
        self.stdout.write(f'\n  → View at: /finance/opening-balances/{entry.pk}/\n')

    def _get_fiscal_year(self):
        """Get Fiscal Year 2025."""
        self.stdout.write(self.style.HTTP_INFO('1. Looking up Fiscal Year 2025...'))

        # Try to find FY 2025 by name or date range
        fy = FiscalYear.objects.filter(
            start_date__year=2025,
            is_active=True
        ).first()

        if not fy:
            fy = FiscalYear.objects.filter(
                name__icontains='2025',
                is_active=True
            ).first()

        if not fy:
            # Auto-create FY 2025
            self.stdout.write(self.style.WARNING(
                '   ⚠ FY 2025 not found. Creating automatically...'
            ))
            fy = FiscalYear.objects.create(
                name='FY 2025',
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                is_active=True,
                is_closed=False,
            )
            self.stdout.write(self.style.SUCCESS(
                f'   ✓ Created: {fy.name} ({fy.start_date} to {fy.end_date})'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'   ✓ Found: {fy.name} ({fy.start_date} to {fy.end_date})'
        ))
        return fy

    def _check_existing(self, fiscal_year, force, dry_run):
        """Check if an opening balance entry already exists for this FY."""
        self.stdout.write(self.style.HTTP_INFO('\n2. Checking for existing entries...'))

        existing = OpeningBalanceEntry.objects.filter(
            fiscal_year=fiscal_year,
            entry_type='gl'
        )

        if existing.exists():
            if force:
                self.stdout.write(self.style.WARNING(
                    f'   ⚠ Found {existing.count()} existing GL opening balance(s) for FY 2025'
                ))
                if not dry_run:
                    for entry in existing:
                        if entry.status == 'posted':
                            self.stdout.write(self.style.WARNING(
                                f'   Skipping posted entry: {entry.entry_number}'
                            ))
                            continue
                        self.stdout.write(f'   Deleting draft entry: {entry.entry_number}')
                        entry.delete()
            else:
                entry_list = ', '.join([e.entry_number for e in existing])
                raise Exception(
                    f'GL Opening Balance entry already exists for FY 2025: {entry_list}. '
                    f'Use --force to delete draft entries and recreate.'
                )
        else:
            self.stdout.write(self.style.SUCCESS('   ✓ No existing entries found'))

    # Account properties for proper COA setup
    ACCOUNT_PROPERTIES = {
        '1101': {'type': AccountType.ASSET, 'is_cash_account': True, 'is_fixed_deposit': False,
                 'category': 'cash_and_bank'},
        '1102': {'type': AccountType.ASSET, 'is_cash_account': True, 'is_fixed_deposit': False,
                 'category': 'cash_and_bank'},
        '1103': {'type': AccountType.ASSET, 'is_cash_account': False, 'is_fixed_deposit': True,
                 'category': 'cash_and_bank'},
        '1104': {'type': AccountType.ASSET, 'is_cash_account': True, 'is_fixed_deposit': False,
                 'category': 'cash_and_bank'},
        '1105': {'type': AccountType.ASSET, 'is_cash_account': True, 'is_fixed_deposit': False,
                 'category': 'cash_and_bank'},
        '1106': {'type': AccountType.ASSET, 'is_cash_account': True, 'is_fixed_deposit': False,
                 'category': 'cash_and_bank'},
        '3201': {'type': AccountType.EQUITY, 'is_cash_account': False, 'is_fixed_deposit': False,
                 'category': 'retained_earnings'},
    }

    def _verify_accounts(self, dry_run):
        """Verify all required GL accounts exist. Rename test accounts if needed."""
        self.stdout.write(self.style.HTTP_INFO('\n3. Verifying GL Accounts...'))

        accounts = {}
        required_codes = set(line['account_code'] for line in self.OPENING_LINES)

        for code in sorted(required_codes):
            line_data = next(l for l in self.OPENING_LINES if l['account_code'] == code)
            expected_name = line_data['account_name']
            props = self.ACCOUNT_PROPERTIES.get(code, {})
            
            account = Account.objects.filter(code=code, is_active=True).first()
            
            if account:
                # Account exists - check if name matches
                if account.name == expected_name:
                    accounts[code] = account
                    self.stdout.write(f'   ✓ {account.code} - {account.name}')
                else:
                    # Account exists with different name - update it
                    old_name = account.name
                    if not dry_run:
                        account.name = expected_name
                        account.account_type = props.get('type', account.account_type)
                        account.is_cash_account = props.get('is_cash_account', account.is_cash_account)
                        account.is_fixed_deposit = props.get('is_fixed_deposit', account.is_fixed_deposit)
                        account.save()
                        self.stdout.write(self.style.WARNING(
                            f'   ✓ {code} - Renamed: "{old_name}" → "{expected_name}"'
                        ))
                    else:
                        self.stdout.write(self.style.WARNING(
                            f'   [DRY RUN] Would rename: {code} "{old_name}" → "{expected_name}"'
                        ))
                    accounts[code] = account
            else:
                # Account does not exist - create it
                acc_type = props.get('type', AccountType.ASSET)
                is_cash = props.get('is_cash_account', False)
                is_fd = props.get('is_fixed_deposit', False)

                if not dry_run:
                    account = Account.objects.create(
                        code=code,
                        name=expected_name,
                        account_type=acc_type,
                        is_cash_account=is_cash,
                        is_fixed_deposit=is_fd,
                        is_system=True,
                    )
                    accounts[code] = account
                    self.stdout.write(self.style.SUCCESS(
                        f'   ✓ Created: {account.code} - {account.name}'
                    ))
                else:
                    self.stdout.write(
                        f'   [DRY RUN] Would create: {code} - {expected_name}'
                    )

        return accounts

    # Bank account definitions for auto-creation
    BANK_ACCOUNT_DEFS = {
        'ADCB Bank - Current Account': {
            'account_number': 'ADCB-CURR-001',
            'bank_name': 'Abu Dhabi Commercial Bank',
            'gl_account_code': '1102',
            'currency': 'AED',
        },
        'ADCB Bank - Fixed Deposit': {
            'account_number': 'ADCB-FD-001',
            'bank_name': 'Abu Dhabi Commercial Bank',
            'gl_account_code': '1103',
            'currency': 'AED',
        },
    }

    def _verify_bank_accounts(self, dry_run):
        """Verify bank accounts exist for bank lines. Auto-create if missing."""
        self.stdout.write(self.style.HTTP_INFO('\n4. Verifying Bank Accounts...'))

        bank_accounts = {}
        
        for line in self.OPENING_LINES:
            ba_name = line.get('bank_account_name')
            if not ba_name:
                continue
            
            # Try to find by exact name first (most reliable)
            ba = BankAccount.objects.filter(name=ba_name, is_active=True).first()
            
            if not ba:
                # Try exact iexact match
                ba = BankAccount.objects.filter(name__iexact=ba_name, is_active=True).first()

            if ba:
                bank_accounts[ba_name] = ba
                self.stdout.write(f'   ✓ {ba.name} (GL: {ba.gl_account.code})')
            else:
                # Auto-create bank account if definition exists
                ba_def = self.BANK_ACCOUNT_DEFS.get(ba_name)
                if ba_def:
                    gl_account = Account.objects.filter(
                        code=ba_def['gl_account_code'], is_active=True
                    ).first()
                    
                    if gl_account and not dry_run:
                        ba = BankAccount.objects.create(
                            name=ba_name,
                            account_number=ba_def['account_number'],
                            bank_name=ba_def['bank_name'],
                            gl_account=gl_account,
                            currency=ba_def['currency'],
                        )
                        bank_accounts[ba_name] = ba
                        self.stdout.write(self.style.SUCCESS(
                            f'   ✓ Created: {ba.name} (GL: {gl_account.code})'
                        ))
                    elif dry_run:
                        self.stdout.write(
                            f'   [DRY RUN] Would create: {ba_name} (GL: {ba_def["gl_account_code"]})'
                        )
                        bank_accounts[ba_name] = None
                    else:
                        self.stdout.write(self.style.WARNING(
                            f'   ⚠ Cannot create "{ba_name}" - GL account {ba_def["gl_account_code"]} not found'
                        ))
                        bank_accounts[ba_name] = None
                else:
                    self.stdout.write(self.style.WARNING(
                        f'   ⚠ Bank Account "{ba_name}" not found - line will be created without bank link'
                    ))
                    bank_accounts[ba_name] = None

        return bank_accounts

    def _create_entry(self, fiscal_year, accounts, bank_accounts, dry_run):
        """Create the OpeningBalanceEntry and its lines."""
        self.stdout.write(self.style.HTTP_INFO('\n5. Creating Opening Balance Entry...'))

        entry_date = date(2025, 1, 1)
        description = 'Opening Balance Entry - Beginning of Fiscal Year 2025'

        if dry_run:
            self.stdout.write(f'   [DRY RUN] Would create entry:')
            self.stdout.write(f'     Entry Type: General Ledger')
            self.stdout.write(f'     Fiscal Year: {fiscal_year.name}')
            self.stdout.write(f'     Entry Date: {entry_date}')
            self.stdout.write(f'     Description: {description}')
            self.stdout.write(f'')
            self.stdout.write(f'   Lines:')
            
            total_dr = Decimal('0.00')
            total_cr = Decimal('0.00')
            
            for line_data in self.OPENING_LINES:
                dr = line_data['debit']
                cr = line_data['credit']
                total_dr += dr
                total_cr += cr
                
                ba_str = f' | Bank: {line_data["bank_account_name"]}' if line_data.get('bank_account_name') else ''
                self.stdout.write(
                    f'     Line {line_data["line"]}: {line_data["account_code"]} '
                    f'Dr {dr:>12,.2f}  Cr {cr:>12,.2f}  '
                    f'Ref: {line_data["ref_number"]}{ba_str}'
                )
            
            self.stdout.write(f'')
            self.stdout.write(f'   {"Totals:":>20} Dr {total_dr:>12,.2f}  Cr {total_cr:>12,.2f}')
            self.stdout.write(f'   {"Difference:":>20} {abs(total_dr - total_cr):>12,.2f} '
                              f'{"✅" if abs(total_dr - total_cr) < Decimal("0.01") else "❌"}')
            return None

        # Create the entry
        entry = OpeningBalanceEntry(
            entry_type='gl',
            fiscal_year=fiscal_year,
            entry_date=entry_date,
            description=description,
            notes=(
                'FY 2025 Opening Balances:\n'
                '- Cash on Hand: 37,000 AED (Main Safe: 6,000 + Petty Cash: 4,000 + General Cash: 27,000)\n'
                '- ADCB Current Account: 50,000 AED\n'
                '- ADCB Fixed Deposit: 48,000 AED\n'
                '- Retained Earnings: 135,000 AED (Credit - accumulated profits from FY 2024)\n'
                '\nTotal Cash & Bank: 135,000 AED\n'
                'Entry Date: 01/01/2025 | Reference Date: 31/12/2024'
            ),
        )
        entry.save()
        self.stdout.write(f'   ✓ Created: {entry.entry_number}')

        # Create lines
        for line_data in self.OPENING_LINES:
            account = accounts.get(line_data['account_code'])
            if not account:
                self.stdout.write(self.style.ERROR(
                    f'   ✗ Skipping line {line_data["line"]}: Account {line_data["account_code"]} not found'
                ))
                continue

            ba = bank_accounts.get(line_data['bank_account_name']) if line_data.get('bank_account_name') else None

            ob_line = OpeningBalanceLine.objects.create(
                opening_balance_entry=entry,
                account=account,
                description=line_data['description'],
                bank_account=ba,
                debit=line_data['debit'],
                credit=line_data['credit'],
                reference_number=line_data['ref_number'],
                reference_date=line_data['ref_date'],
            )

            dr_cr = f'Dr {line_data["debit"]:,.2f}' if line_data['debit'] > 0 else f'Cr {line_data["credit"]:,.2f}'
            ba_str = f' | Bank: {ba.name}' if ba else ''
            self.stdout.write(
                f'   ✓ Line {line_data["line"]}: {account.code} - {account.name} | '
                f'{dr_cr} | Ref: {line_data["ref_number"]}{ba_str}'
            )

        # Calculate totals
        entry.calculate_totals()
        self.stdout.write(f'\n   Total Debit:  AED {entry.total_debit:,.2f}')
        self.stdout.write(f'   Total Credit: AED {entry.total_credit:,.2f}')

        return entry

    def _validate_entry(self, entry):
        """Validate the entry is balanced."""
        self.stdout.write(self.style.HTTP_INFO('\n6. Validating entry...'))

        if entry.is_balanced:
            self.stdout.write(self.style.SUCCESS(
                f'   ✓ Entry is BALANCED: Dr {entry.total_debit:,.2f} = Cr {entry.total_credit:,.2f}'
            ))
        else:
            diff = abs(entry.total_debit - entry.total_credit)
            self.stdout.write(self.style.ERROR(
                f'   ✗ Entry is NOT balanced! Difference: AED {diff:,.2f}'
            ))
            raise Exception(f'Entry is not balanced. Dr: {entry.total_debit}, Cr: {entry.total_credit}')

        line_count = entry.lines.count()
        self.stdout.write(f'   ✓ {line_count} lines created')

    def _post_entry(self, entry):
        """Post the entry to create journal entry."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        self.stdout.write(self.style.HTTP_INFO('\n7. Posting entry...'))

        # Get admin/superuser
        admin = User.objects.filter(is_superuser=True, is_active=True).first()
        if not admin:
            admin = User.objects.filter(is_active=True).first()

        if not admin:
            self.stdout.write(self.style.ERROR('   ✗ No active user found to post entry'))
            return

        try:
            journal = entry.post(admin)
            self.stdout.write(self.style.SUCCESS(
                f'   ✓ Posted! Journal Entry: {entry.journal_entry.entry_number}'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Failed to post: {e}'))

