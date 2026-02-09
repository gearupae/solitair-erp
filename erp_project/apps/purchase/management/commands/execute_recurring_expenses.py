"""
Management command to execute recurring expenses.
Should be run daily via cron job or task scheduler.

Usage:
    python manage.py execute_recurring_expenses

Behavior:
- Checks all active recurring expenses
- Executes those where next_run_date <= today
- Respects fiscal year and period locking
- Logs all executions (success/failure)
- Skips locked periods
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date
from apps.purchase.models import RecurringExpense


class Command(BaseCommand):
    help = 'Execute all due recurring expenses and post journal entries.'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be executed without actually executing.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force execution even if not due (use with caution).',
        )
    
    def handle(self, *args, **options):
        today = date.today()
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        
        self.stdout.write(self.style.NOTICE(f'Checking recurring expenses for {today}...'))
        
        # Get all active recurring expenses
        if force:
            expenses = RecurringExpense.objects.filter(is_active=True, status='active')
        else:
            expenses = RecurringExpense.objects.filter(
                is_active=True, 
                status='active',
                next_run_date__lte=today
            )
        
        if not expenses.exists():
            self.stdout.write(self.style.SUCCESS('No recurring expenses due for execution.'))
            return
        
        self.stdout.write(f'Found {expenses.count()} recurring expense(s) due for execution.')
        
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for expense in expenses:
            self.stdout.write(f'\nProcessing: {expense.name} (Vendor: {expense.vendor.name})')
            self.stdout.write(f'  Amount: AED {expense.total_amount}')
            self.stdout.write(f'  Next Run Date: {expense.next_run_date}')
            
            if dry_run:
                self.stdout.write(self.style.WARNING('  [DRY RUN] Would execute this expense.'))
                continue
            
            try:
                log = expense.execute()
                
                if log is None:
                    self.stdout.write(self.style.WARNING('  SKIPPED: Not due or completed.'))
                    skipped_count += 1
                elif log.status == 'success':
                    self.stdout.write(self.style.SUCCESS(f'  SUCCESS: Journal {log.journal_entry.entry_number if log.journal_entry else "N/A"}'))
                    success_count += 1
                else:
                    self.stdout.write(self.style.ERROR(f'  FAILED: {log.error_message}'))
                    failed_count += 1
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ERROR: {str(e)}'))
                failed_count += 1
        
        # Summary
        self.stdout.write('\n' + '='*50)
        self.stdout.write(self.style.NOTICE('SUMMARY:'))
        self.stdout.write(f'  Total processed: {expenses.count()}')
        self.stdout.write(self.style.SUCCESS(f'  Successful: {success_count}'))
        self.stdout.write(self.style.ERROR(f'  Failed: {failed_count}'))
        self.stdout.write(self.style.WARNING(f'  Skipped: {skipped_count}'))
        
        if failed_count > 0:
            self.stdout.write(self.style.ERROR('\nSome recurring expenses failed. Please check the logs.'))
        else:
            self.stdout.write(self.style.SUCCESS('\nAll recurring expenses processed successfully.'))




