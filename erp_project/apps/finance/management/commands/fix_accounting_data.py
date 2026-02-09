# -*- coding: utf-8 -*-
"""
Management command to fix accounting data issues:
1. Delete test payroll entries (123M+ transactions)
2. Fix opening balance signs for liabilities and equity
3. Balance opening balances by adjusting Retained Earnings
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Sum
from decimal import Decimal


class Command(BaseCommand):
    help = 'Fixes accounting data issues: test data, opening balance signs, and balance imbalance'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--delete-test-data',
            action='store_true',
            help='Delete test payroll entries with 100M+ amounts',
        )
        parser.add_argument(
            '--fix-opening-signs',
            action='store_true',
            help='Fix negative opening balances for liabilities and equity',
        )
        parser.add_argument(
            '--balance-opening',
            action='store_true',
            help='Balance opening balances by adjusting Retained Earnings',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Run all fixes',
        )

    def handle(self, *args, **options):
        from apps.finance.models import Account, JournalEntry, JournalEntryLine, AccountType

        dry_run = options['dry_run']
        run_all = options['all']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n🔍 DRY RUN MODE - No changes will be made\n'))

        # ============================================================
        # STEP 1: Delete Test Data (123M+ payroll entries)
        # ============================================================
        if run_all or options['delete_test_data']:
            self.stdout.write(self.style.SUCCESS('\n' + '=' * 80))
            self.stdout.write(self.style.SUCCESS('STEP 1: Delete Test Payroll Data (123M+ transactions)'))
            self.stdout.write(self.style.SUCCESS('=' * 80))

            # Find journal entries with lines > 100M
            large_entries = JournalEntry.objects.filter(
                lines__debit__gte=100000000
            ).distinct()

            for entry in large_entries:
                total_debit = entry.lines.aggregate(total=Sum('debit'))['total'] or Decimal('0')
                self.stdout.write(f'  Found: {entry.entry_number} | {entry.date} | Debit: {total_debit:,.2f}')
                self.stdout.write(f'    Description: {entry.description}')

            if large_entries.exists():
                if not dry_run:
                    with transaction.atomic():
                        entry_ids = list(large_entries.values_list('id', flat=True))
                        
                        with connection.cursor() as cursor:
                            # Clear foreign key references
                            cursor.execute(
                                'UPDATE hr_payroll SET journal_entry_id = NULL WHERE journal_entry_id IN (%s)' % 
                                ','.join(str(i) for i in entry_ids)
                            )
                            cursor.execute(
                                'UPDATE hr_payroll SET payment_journal_entry_id = NULL WHERE payment_journal_entry_id IN (%s)' % 
                                ','.join(str(i) for i in entry_ids)
                            )
                            
                            # Delete lines
                            cursor.execute(
                                'DELETE FROM finance_journalentryline WHERE journal_entry_id IN (%s)' % 
                                ','.join(str(i) for i in entry_ids)
                            )
                            lines_deleted = cursor.rowcount
                            
                            # Delete entries
                            cursor.execute(
                                'DELETE FROM finance_journalentry WHERE id IN (%s)' % 
                                ','.join(str(i) for i in entry_ids)
                            )
                            entries_deleted = cursor.rowcount

                        self.stdout.write(self.style.SUCCESS(f'  ✅ Deleted {entries_deleted} entries, {lines_deleted} lines'))
                else:
                    self.stdout.write(self.style.NOTICE('  Would delete these entries'))
            else:
                self.stdout.write('  No test data found')

        # ============================================================
        # STEP 2: Fix Opening Balance Signs
        # ============================================================
        if run_all or options['fix_opening_signs']:
            self.stdout.write(self.style.SUCCESS('\n' + '=' * 80))
            self.stdout.write(self.style.SUCCESS('STEP 2: Fix Opening Balance Signs (Liabilities & Equity)'))
            self.stdout.write(self.style.SUCCESS('=' * 80))

            # Fix liability accounts with negative opening balances
            negative_liabilities = Account.objects.filter(
                is_active=True,
                account_type=AccountType.LIABILITY,
                opening_balance__lt=0
            )

            for acc in negative_liabilities:
                old_val = acc.opening_balance
                new_val = abs(old_val)
                self.stdout.write(f'  {acc.code}: {acc.name} | {old_val:,.2f} → {new_val:,.2f}')
                if not dry_run:
                    acc.opening_balance = new_val
                    acc.save(update_fields=['opening_balance'])

            # Fix equity accounts with negative opening balances
            negative_equity = Account.objects.filter(
                is_active=True,
                account_type=AccountType.EQUITY,
                opening_balance__lt=0
            )

            for acc in negative_equity:
                old_val = acc.opening_balance
                new_val = abs(old_val)
                self.stdout.write(f'  {acc.code}: {acc.name} | {old_val:,.2f} → {new_val:,.2f}')
                if not dry_run:
                    acc.opening_balance = new_val
                    acc.save(update_fields=['opening_balance'])

            total_fixed = negative_liabilities.count() + negative_equity.count()
            if total_fixed > 0:
                self.stdout.write(self.style.SUCCESS(f'  ✅ Fixed {total_fixed} accounts'))
            else:
                self.stdout.write('  No accounts need fixing')

        # ============================================================
        # STEP 3: Balance Opening Balances
        # ============================================================
        if run_all or options['balance_opening']:
            self.stdout.write(self.style.SUCCESS('\n' + '=' * 80))
            self.stdout.write(self.style.SUCCESS('STEP 3: Balance Opening Balances'))
            self.stdout.write(self.style.SUCCESS('=' * 80))

            # Calculate totals
            asset_opening = Decimal('0')
            liability_opening = Decimal('0')
            equity_opening = Decimal('0')

            for acc in Account.objects.filter(is_active=True):
                opening = acc.opening_balance or Decimal('0')
                if acc.account_type == AccountType.ASSET:
                    asset_opening += opening
                elif acc.account_type == AccountType.LIABILITY:
                    liability_opening += opening
                elif acc.account_type == AccountType.EQUITY:
                    equity_opening += opening

            self.stdout.write(f'  Asset Opening:     {asset_opening:>15,.2f}')
            self.stdout.write(f'  Liability Opening: {liability_opening:>15,.2f}')
            self.stdout.write(f'  Equity Opening:    {equity_opening:>15,.2f}')
            self.stdout.write(f'  L + E:             {liability_opening + equity_opening:>15,.2f}')

            imbalance = asset_opening - (liability_opening + equity_opening)
            self.stdout.write(f'  Imbalance:         {imbalance:>15,.2f}')

            if abs(imbalance) > Decimal('0.01'):
                # Adjust Retained Earnings
                retained_earnings = Account.objects.filter(
                    code='3200',
                    account_type=AccountType.EQUITY
                ).first()

                if not retained_earnings:
                    # Try to find any Retained Earnings account
                    retained_earnings = Account.objects.filter(
                        name__icontains='retained earnings',
                        account_type=AccountType.EQUITY
                    ).first()

                if retained_earnings:
                    old_val = retained_earnings.opening_balance or Decimal('0')
                    new_val = old_val + imbalance
                    self.stdout.write(f'\n  Adjusting {retained_earnings.code}: {retained_earnings.name}')
                    self.stdout.write(f'  {old_val:,.2f} → {new_val:,.2f}')
                    
                    if not dry_run:
                        retained_earnings.opening_balance = new_val
                        retained_earnings.save(update_fields=['opening_balance'])
                        self.stdout.write(self.style.SUCCESS('  ✅ Opening balances are now balanced'))
                else:
                    self.stdout.write(self.style.ERROR('  ❌ Retained Earnings account not found'))
            else:
                self.stdout.write(self.style.SUCCESS('  ✅ Opening balances are already balanced'))

        # ============================================================
        # FINAL VERIFICATION
        # ============================================================
        self.stdout.write(self.style.SUCCESS('\n' + '=' * 80))
        self.stdout.write(self.style.SUCCESS('FINAL VERIFICATION'))
        self.stdout.write(self.style.SUCCESS('=' * 80))

        from datetime import date
        end_date = date.today()

        total_assets = Decimal('0')
        for acc in Account.objects.filter(is_active=True, account_type=AccountType.ASSET):
            bal = acc.opening_balance or Decimal('0')
            lines = JournalEntryLine.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__lte=end_date
            ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
            bal += (lines['debit'] or Decimal('0')) - (lines['credit'] or Decimal('0'))
            total_assets += bal

        total_liabilities = Decimal('0')
        for acc in Account.objects.filter(is_active=True, account_type=AccountType.LIABILITY):
            bal = acc.opening_balance or Decimal('0')
            lines = JournalEntryLine.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__lte=end_date
            ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
            bal += (lines['credit'] or Decimal('0')) - (lines['debit'] or Decimal('0'))
            total_liabilities += bal

        total_equity = Decimal('0')
        for acc in Account.objects.filter(is_active=True, account_type=AccountType.EQUITY):
            bal = acc.opening_balance or Decimal('0')
            lines = JournalEntryLine.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__lte=end_date
            ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
            bal += (lines['credit'] or Decimal('0')) - (lines['debit'] or Decimal('0'))
            total_equity += bal

        # Income - Expenses
        total_income = Decimal('0')
        for acc in Account.objects.filter(is_active=True, account_type=AccountType.INCOME):
            lines = JournalEntryLine.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__lte=end_date
            ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
            total_income += (lines['credit'] or Decimal('0')) - (lines['debit'] or Decimal('0'))

        total_expenses = Decimal('0')
        for acc in Account.objects.filter(is_active=True, account_type=AccountType.EXPENSE):
            lines = JournalEntryLine.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__lte=end_date
            ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
            total_expenses += (lines['debit'] or Decimal('0')) - (lines['credit'] or Decimal('0'))

        current_profit = total_income - total_expenses

        self.stdout.write(f'\n  Total Assets:      {total_assets:>15,.2f}')
        self.stdout.write(f'  Total Liabilities: {total_liabilities:>15,.2f}')
        self.stdout.write(f'  Total Equity:      {total_equity:>15,.2f}')
        self.stdout.write(f'  Current Profit:    {current_profit:>15,.2f}')
        self.stdout.write(f'  L + E + Profit:    {total_liabilities + total_equity + current_profit:>15,.2f}')

        difference = total_assets - (total_liabilities + total_equity + current_profit)

        if abs(difference) < Decimal('0.01'):
            self.stdout.write(self.style.SUCCESS('\n  ✅ BALANCE SHEET IS BALANCED!'))
        else:
            self.stdout.write(self.style.ERROR(f'\n  ❌ Difference: {difference:,.2f}'))

        self.stdout.write('\n')



