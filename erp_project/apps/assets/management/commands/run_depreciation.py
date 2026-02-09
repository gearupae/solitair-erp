"""
Management command to run monthly depreciation for all active fixed assets.
Should be scheduled as a monthly cron job.

Example cron entry (runs on 1st of each month at 1 AM):
0 1 1 * * cd /path/to/project && python manage.py run_depreciation
"""
from datetime import date
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.assets.models import FixedAsset


class Command(BaseCommand):
    help = 'Run monthly depreciation for all active fixed assets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Depreciation date (YYYY-MM-DD). Defaults to last day of previous month.'
        )
        parser.add_argument(
            '--asset',
            type=str,
            help='Specific asset number to depreciate. If not specified, all active assets.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without actually posting to accounting'
        )

    def handle(self, *args, **options):
        # Determine depreciation date
        if options['date']:
            try:
                depreciation_date = date.fromisoformat(options['date'])
            except ValueError:
                self.stderr.write(self.style.ERROR('Invalid date format. Use YYYY-MM-DD'))
                return
        else:
            # Default to last day of previous month
            today = date.today()
            first_of_month = today.replace(day=1)
            depreciation_date = first_of_month - timedelta(days=1)
        
        self.stdout.write(f'Depreciation date: {depreciation_date}')
        
        # Get assets to depreciate
        if options['asset']:
            assets = FixedAsset.objects.filter(
                asset_number=options['asset'],
                status='active',
                is_active=True
            )
        else:
            assets = FixedAsset.objects.filter(
                status='active',
                is_active=True
            )
        
        if not assets.exists():
            self.stdout.write(self.style.WARNING('No active assets found to depreciate.'))
            return
        
        self.stdout.write(f'Found {assets.count()} active assets')
        
        success_count = 0
        skip_count = 0
        error_count = 0
        
        for asset in assets:
            try:
                # Check if already depreciated for this month
                if asset.last_depreciation_date and \
                   asset.last_depreciation_date.year == depreciation_date.year and \
                   asset.last_depreciation_date.month == depreciation_date.month:
                    self.stdout.write(f'  SKIP: {asset.asset_number} - Already depreciated for {depreciation_date.strftime("%B %Y")}')
                    skip_count += 1
                    continue
                
                # Check if fully depreciated
                if asset.book_value <= asset.salvage_value:
                    self.stdout.write(f'  SKIP: {asset.asset_number} - Fully depreciated')
                    skip_count += 1
                    continue
                
                # Calculate depreciation
                depreciation_amount = asset.monthly_depreciation
                
                if depreciation_amount <= 0:
                    self.stdout.write(f'  SKIP: {asset.asset_number} - No depreciation amount')
                    skip_count += 1
                    continue
                
                if options['dry_run']:
                    self.stdout.write(
                        f'  DRY RUN: {asset.asset_number} - Would depreciate AED {depreciation_amount:,.2f}'
                    )
                    success_count += 1
                else:
                    with transaction.atomic():
                        journal = asset.run_depreciation(depreciation_date)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  OK: {asset.asset_number} - Depreciated AED {depreciation_amount:,.2f} (Journal: {journal.entry_number})'
                            )
                        )
                        success_count += 1
                        
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f'  ERROR: {asset.asset_number} - {str(e)}')
                )
                error_count += 1
        
        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 50)
        self.stdout.write(f'Total Assets: {assets.count()}')
        self.stdout.write(f'  Depreciated: {success_count}')
        self.stdout.write(f'  Skipped: {skip_count}')
        self.stdout.write(f'  Errors: {error_count}')
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes were made'))
        else:
            self.stdout.write(self.style.SUCCESS('\nDepreciation run completed'))


from datetime import timedelta




