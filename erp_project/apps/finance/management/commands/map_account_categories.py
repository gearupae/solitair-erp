"""
Management command to map existing accounts to their categories.
Used for Trial Balance & Financial Statement grouping.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.finance.models import Account, AccountCategory


class Command(BaseCommand):
    help = 'Map existing accounts to their categories for Trial Balance grouping'
    
    # Account name patterns to category mapping
    CATEGORY_MAPPINGS = {
        # ========== ASSETS ==========
        # Cash & Bank
        AccountCategory.CASH_BANK: [
            'bank', 'cash in hand', 'petty cash', 'main safe',
            'current account', 'savings account', 'fixed deposit',
        ],
        
        # Trade Receivables
        AccountCategory.TRADE_RECEIVABLES: [
            'accounts receivable', 'trade debtors', 'receivable',
            'pdc receivable', 'customer', 'debtor',
        ],
        
        # Tax Receivables
        AccountCategory.TAX_RECEIVABLES: [
            'vat recoverable', 'vat receivable', 'input vat',
            'tax recoverable', 'withholding tax receivable',
        ],
        
        # Inventory
        AccountCategory.INVENTORY: [
            'inventory', 'stock', 'raw material', 'finished goods',
            'work in progress', 'merchandise',
        ],
        
        # Fixed Assets - Furniture
        AccountCategory.FIXED_ASSETS_FURNITURE: [
            'furniture', 'fixtures', 'office equipment',
        ],
        
        # Fixed Assets - IT
        AccountCategory.FIXED_ASSETS_IT: [
            'computer', 'it equipment', 'software', 'hardware',
            'laptop', 'desktop', 'server',
        ],
        
        # Fixed Assets - Vehicles
        AccountCategory.FIXED_ASSETS_VEHICLES: [
            'vehicle', 'car', 'truck', 'motor',
        ],
        
        # Accumulated Depreciation (Contra Asset)
        AccountCategory.ACCUMULATED_DEPRECIATION: [
            'accumulated depreciation', 'accum depreciation',
            'acc depreciation', 'provision for depreciation',
        ],
        
        # ========== LIABILITIES ==========
        # Trade Payables
        AccountCategory.TRADE_PAYABLES: [
            'accounts payable', 'trade creditors', 'creditor',
            'payable', 'supplier', 'vendor',
        ],
        
        # Tax Payables
        AccountCategory.TAX_PAYABLES: [
            'vat payable', 'vat output', 'output vat',
            'tax payable', 'corporate tax', 'withholding tax payable',
        ],
        
        # Accrued Liabilities
        AccountCategory.ACCRUED_LIABILITIES: [
            'accrued', 'provision', 'liability',
        ],
        
        # ========== EQUITY ==========
        # Capital Accounts
        AccountCategory.CAPITAL: [
            'capital', 'owner', 'partner', 'share capital',
            'paid-in capital', 'contributed capital',
        ],
        
        # Retained Earnings
        AccountCategory.RETAINED_EARNINGS: [
            'retained earnings', 'accumulated profit',
            'profit and loss', 'opening balance',
        ],
        
        # Reserves
        AccountCategory.RESERVES: [
            'reserve', 'surplus', 'general reserve',
        ],
        
        # ========== INCOME ==========
        # Operating Revenue
        AccountCategory.OPERATING_REVENUE: [
            'sales', 'revenue', 'service income', 'rental income',
            'consulting income', 'fee income',
        ],
        
        # Other Income
        AccountCategory.OTHER_INCOME: [
            'interest income', 'dividend income', 'gain on',
            'other income', 'miscellaneous income',
        ],
        
        # ========== EXPENSES ==========
        # Cost of Sales
        AccountCategory.COST_OF_SALES: [
            'cost of goods', 'cogs', 'cost of sales',
            'direct cost', 'purchase',
        ],
        
        # Rent Expenses
        AccountCategory.RENT_EXPENSE: [
            'rent', 'lease expense',
        ],
        
        # Salary & Staff Costs
        AccountCategory.SALARY_EXPENSE: [
            'salary', 'wage', 'payroll', 'staff',
            'employee', 'commission', 'bonus',
            'end of service', 'gratuity', 'pension',
        ],
        
        # Banking Expenses
        AccountCategory.BANKING_EXPENSE: [
            'bank charge', 'bank fee', 'transaction fee',
            'wire transfer', 'cheque', 'atm',
        ],
        
        # Bad Debts
        AccountCategory.BAD_DEBTS: [
            'bad debt', 'doubtful debt', 'write off',
            'allowance for doubtful',
        ],
        
        # Depreciation Expense
        AccountCategory.DEPRECIATION_EXPENSE: [
            'depreciation expense', 'amortization',
        ],
        
        # Utilities
        AccountCategory.UTILITIES: [
            'utility', 'electricity', 'water', 'telephone',
            'internet', 'communication',
        ],
        
        # Project Costs
        AccountCategory.PROJECT_COSTS: [
            'project expense', 'project cost',
        ],
        
        # Marketing
        AccountCategory.MARKETING: [
            'marketing', 'advertising', 'promotion',
        ],
        
        # Administrative Expenses
        AccountCategory.ADMIN_EXPENSE: [
            'office supplies', 'stationery', 'printing',
            'professional fee', 'legal fee', 'audit fee',
            'consulting fee', 'travel', 'training',
            'subscription', 'license', 'insurance',
        ],
    }
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without actually updating'
        )
    
    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        self.stdout.write(self.style.WARNING('\n' + '='*60))
        self.stdout.write(self.style.WARNING('MAPPING ACCOUNTS TO CATEGORIES'))
        self.stdout.write(self.style.WARNING('='*60 + '\n'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made\n'))
        
        accounts = Account.objects.filter(is_active=True)
        updated_count = 0
        unmapped_count = 0
        
        with transaction.atomic():
            for account in accounts:
                name_lower = account.name.lower()
                matched_category = None
                is_contra = False
                
                # Check for accumulated depreciation (contra asset)
                if any(pattern in name_lower for pattern in ['accumulated depreciation', 'accum depreciation']):
                    matched_category = AccountCategory.ACCUMULATED_DEPRECIATION
                    is_contra = True
                else:
                    # Find matching category
                    for category, patterns in self.CATEGORY_MAPPINGS.items():
                        for pattern in patterns:
                            if pattern in name_lower:
                                matched_category = category
                                break
                        if matched_category:
                            break
                
                # Fallback based on account type if no match
                if not matched_category:
                    if account.account_type == 'asset':
                        matched_category = AccountCategory.OTHER_CURRENT_ASSETS
                    elif account.account_type == 'liability':
                        matched_category = AccountCategory.OTHER_CURRENT_LIABILITIES
                    elif account.account_type == 'equity':
                        matched_category = AccountCategory.RESERVES
                    elif account.account_type == 'income':
                        matched_category = AccountCategory.OTHER_INCOME
                    elif account.account_type == 'expense':
                        matched_category = AccountCategory.OTHER_EXPENSE
                
                if matched_category:
                    if not dry_run:
                        account.account_category = matched_category
                        account.is_contra_account = is_contra
                        account.save(update_fields=['account_category', 'is_contra_account'])
                    
                    status = 'CONTRA' if is_contra else 'MAPPED'
                    self.stdout.write(
                        f'[{status}] {account.code} - {account.name} → {matched_category}'
                    )
                    updated_count += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(f'[UNMAPPED] {account.code} - {account.name}')
                    )
                    unmapped_count += 1
            
            if dry_run:
                self.stdout.write(self.style.WARNING('\n[DRY RUN] Rolling back changes...'))
                raise Exception('Dry run complete')
        
        self.stdout.write(self.style.SUCCESS(f'\n✓ {updated_count} accounts mapped'))
        if unmapped_count:
            self.stdout.write(self.style.WARNING(f'! {unmapped_count} accounts unmapped'))



