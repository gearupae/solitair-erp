"""
Fix Duplicate Opening Balance Entries

This command identifies and removes duplicate opening balance entries
that cause issues with Cash Flow Statement and Trial Balance.

ACCOUNTING RULE: Each account should have only ONE opening balance entry per fiscal year.
"""

from django.core.management.base import BaseCommand
from apps.finance.models import JournalEntry, JournalEntryLine, Account
from django.db.models import Count
from decimal import Decimal


class Command(BaseCommand):
    help = 'Fix duplicate opening balance entries in journals'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.NOTICE('=' * 60))
        self.stdout.write(self.style.NOTICE('CHECKING FOR DUPLICATE OPENING BALANCE ENTRIES'))
        self.stdout.write(self.style.NOTICE('=' * 60))
        
        # Find journals that look like opening balance entries
        opening_journals = JournalEntry.objects.filter(
            status='posted'
        ).filter(
            models.Q(reference__icontains='OPENING BALANCE') |
            models.Q(reference__istartswith='OB-') |
            models.Q(entry_type='opening') |
            models.Q(description__icontains='Opening Balance') |
            models.Q(source_module='opening_balance') |
            models.Q(source_module='system_opening')
        ).order_by('date', 'created_at')
        
        self.stdout.write(f"\nFound {opening_journals.count()} opening balance journal(s)")
        
        # Group by date to find duplicates
        date_groups = {}
        for journal in opening_journals:
            date_key = journal.date.isoformat()
            if date_key not in date_groups:
                date_groups[date_key] = []
            date_groups[date_key].append(journal)
        
        duplicates_found = 0
        journals_to_delete = []
        
        for date_key, journals in date_groups.items():
            if len(journals) > 1:
                duplicates_found += len(journals) - 1
                self.stdout.write(self.style.WARNING(
                    f"\n⚠️  DUPLICATE on {date_key}: {len(journals)} opening balance entries found"
                ))
                
                # Keep the first one (usually the correctly numbered one like OB-2024-001)
                # Delete the others
                keep = journals[0]
                for journal in journals:
                    lines_info = journal.lines.aggregate(
                        total_dr=models.Sum('debit'),
                        total_cr=models.Sum('credit')
                    )
                    self.stdout.write(
                        f"   • {journal.entry_number} | Ref: {journal.reference} | "
                        f"Dr: {lines_info['total_dr'] or 0} | Cr: {lines_info['total_cr'] or 0}"
                    )
                    
                    # Determine which to keep (prefer OB-YYYY-XXX format)
                    if journal.reference and journal.reference.startswith('OB-'):
                        keep = journal
                
                self.stdout.write(self.style.SUCCESS(f"   → KEEP: {keep.entry_number} ({keep.reference})"))
                
                for journal in journals:
                    if journal.pk != keep.pk:
                        journals_to_delete.append(journal)
                        self.stdout.write(self.style.ERROR(f"   → DELETE: {journal.entry_number} ({journal.reference})"))
        
        # Check for duplicate lines within opening balance journals (same account hit twice)
        self.stdout.write(self.style.NOTICE('\n' + '=' * 60))
        self.stdout.write(self.style.NOTICE('CHECKING FOR DUPLICATE ACCOUNT ENTRIES WITHIN JOURNALS'))
        self.stdout.write(self.style.NOTICE('=' * 60))
        
        for journal in opening_journals:
            # Group lines by account
            account_counts = journal.lines.values('account').annotate(
                count=Count('id'),
                total_debit=models.Sum('debit'),
                total_credit=models.Sum('credit')
            ).filter(count__gt=1)
            
            if account_counts.exists():
                self.stdout.write(self.style.WARNING(
                    f"\n⚠️  Duplicate account entries in {journal.entry_number}:"
                ))
                for acc_data in account_counts:
                    account = Account.objects.get(pk=acc_data['account'])
                    self.stdout.write(
                        f"   • {account.code} - {account.name}: "
                        f"{acc_data['count']} entries, "
                        f"Dr: {acc_data['total_debit']}, Cr: {acc_data['total_credit']}"
                    )
        
        # Summary
        self.stdout.write(self.style.NOTICE('\n' + '=' * 60))
        self.stdout.write(self.style.NOTICE('SUMMARY'))
        self.stdout.write(self.style.NOTICE('=' * 60))
        self.stdout.write(f"Total opening balance journals: {opening_journals.count()}")
        self.stdout.write(f"Duplicate journals found: {duplicates_found}")
        self.stdout.write(f"Journals to delete: {len(journals_to_delete)}")
        
        if journals_to_delete:
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    "\n🔍 DRY RUN - No changes made. Run without --dry-run to apply fixes."
                ))
            else:
                confirm = input("\n⚠️  Delete duplicate journals? (yes/no): ")
                if confirm.lower() == 'yes':
                    for journal in journals_to_delete:
                        self.stdout.write(f"Deleting {journal.entry_number}...")
                        # First delete lines
                        journal.lines.all().delete()
                        # Then delete journal
                        journal.delete()
                    self.stdout.write(self.style.SUCCESS(
                        f"\n✅ Deleted {len(journals_to_delete)} duplicate journal(s)"
                    ))
                else:
                    self.stdout.write(self.style.NOTICE("No changes made."))
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ No duplicate opening balance entries found!"))
        
        self.stdout.write(self.style.NOTICE('\n' + '=' * 60))


# Import models
from django.db import models



