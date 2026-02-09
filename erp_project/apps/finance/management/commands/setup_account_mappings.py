"""
Setup Default Account Mappings
SAP/Oracle-style Account Determination

This command sets up default account mappings based on existing chart of accounts.
Run this ONCE after migrating to the new account mapping system.
"""
from django.core.management.base import BaseCommand
from apps.finance.models import Account, AccountType, AccountMapping, AccountingSettings


class Command(BaseCommand):
    help = 'Setup default account mappings for SAP/Oracle-style posting'
    
    # Default account code mappings (code -> transaction types)
    DEFAULT_MAPPINGS = {
        # Sales Mappings
        '1200': ['sales_invoice_receivable', 'customer_receipt_ar_clear'],
        '4000': ['sales_invoice_revenue'],
        '2100': ['sales_invoice_vat'],
        
        # Purchase Mappings
        '2000': ['vendor_bill_payable', 'vendor_payment_ap_clear'],
        '5000': ['vendor_bill_expense', 'expense_claim_expense'],
        '1300': ['vendor_bill_vat', 'expense_claim_vat'],
        
        # Expense Claim Mappings (Employee Payable - may use different code)
        '2200': ['expense_claim_payable'],  # If 2200 doesn't exist, try 2100
        
        # Payroll Mappings
        '6000': ['payroll_salary_expense'],
        '2300': ['payroll_salary_payable'],
        '6100': ['payroll_gratuity_expense'],
        '2400': ['payroll_gratuity_payable'],
        
        # Banking Mappings
        '7000': ['bank_charges'],
        '4100': ['bank_interest_income'],
        '7100': ['bank_interest_expense'],
        
        # General Mappings
        '8000': ['fx_gain'],
        '8100': ['fx_loss'],
        '3000': ['retained_earnings'],
        '3100': ['opening_balance_equity'],
        '9000': ['suspense'],
        '9100': ['rounding'],
    }
    
    # Alternative account codes to try if primary not found
    ALTERNATIVES = {
        '2200': ['2100'],  # Employee Payable -> Other Payables
        '6000': ['5100', '5000'],  # Salary Expense -> General Expense
        '2300': ['2000'],  # Salary Payable -> AP
        '6100': ['5100', '5000'],  # Gratuity Expense -> General Expense
        '2400': ['2000'],  # Gratuity Payable -> AP
        '7000': ['5200', '5000'],  # Bank Charges -> General Expense
        '4100': ['4000'],  # Interest Income -> Other Income
        '7100': ['5300', '5000'],  # Interest Expense -> General Expense
        '8000': ['4200', '4000'],  # FX Gain -> Other Income
        '8100': ['5400', '5000'],  # FX Loss -> Other Expense
        '3000': ['3100'],  # Retained Earnings
        '3100': ['3000'],  # Opening Balance Equity
        '9000': ['1900', '2900'],  # Suspense
        '9100': ['5900', '5000'],  # Rounding
    }
    
    # Determine module from transaction type
    MODULE_MAP = {
        'sales': ['sales_invoice_receivable', 'sales_invoice_revenue', 'sales_invoice_vat', 
                  'sales_invoice_discount', 'customer_receipt', 'customer_receipt_ar_clear'],
        'purchase': ['vendor_bill_payable', 'vendor_bill_expense', 'vendor_bill_vat',
                     'vendor_payment', 'vendor_payment_ap_clear'],
        'expense_claim': ['expense_claim_expense', 'expense_claim_vat', 'expense_claim_payable',
                         'expense_claim_payment', 'expense_claim_clear'],
        'payroll': ['payroll_salary_expense', 'payroll_salary_payable', 'payroll_gratuity_expense',
                   'payroll_gratuity_payable', 'payroll_pension_expense', 'payroll_pension_payable',
                   'payroll_wps_deduction', 'payroll_payment', 'payroll_payment_clear'],
        'banking': ['bank_charges', 'bank_interest_income', 'bank_interest_expense', 'bank_transfer'],
        'general': ['fx_gain', 'fx_loss', 'retained_earnings', 'opening_balance_equity', 'suspense', 'rounding'],
    }
    
    def get_module(self, transaction_type):
        """Determine module from transaction type."""
        for module, types in self.MODULE_MAP.items():
            if transaction_type in types:
                return module
        return 'general'
    
    def find_account(self, code):
        """Find account by code, trying alternatives if not found."""
        # Try primary code
        account = Account.objects.filter(code=code, is_active=True).first()
        if account:
            return account
        
        # Try alternatives
        alternatives = self.ALTERNATIVES.get(code, [])
        for alt_code in alternatives:
            account = Account.objects.filter(code=alt_code, is_active=True).first()
            if account:
                return account
        
        # Try partial match
        account = Account.objects.filter(code__startswith=code[:2], is_active=True).first()
        return account
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Setting up default account mappings...'))
        
        created_count = 0
        skipped_count = 0
        failed_count = 0
        
        for code, transaction_types in self.DEFAULT_MAPPINGS.items():
            account = self.find_account(code)
            
            if not account:
                self.stdout.write(self.style.WARNING(
                    f'Account {code} not found. Skipping: {", ".join(transaction_types)}'
                ))
                failed_count += len(transaction_types)
                continue
            
            for trans_type in transaction_types:
                # Check if mapping already exists
                existing = AccountMapping.objects.filter(transaction_type=trans_type).first()
                if existing:
                    self.stdout.write(self.style.WARNING(
                        f'Mapping for {trans_type} already exists -> {existing.account.code}'
                    ))
                    skipped_count += 1
                    continue
                
                # Create mapping
                module = self.get_module(trans_type)
                mapping = AccountMapping.objects.create(
                    module=module,
                    transaction_type=trans_type,
                    account=account,
                )
                self.stdout.write(self.style.SUCCESS(
                    f'Created: {trans_type} -> {account.code} ({account.name})'
                ))
                created_count += 1
        
        # Ensure AccountingSettings exists
        settings = AccountingSettings.get_settings()
        self.stdout.write(self.style.SUCCESS(f'Accounting settings initialized.'))
        
        self.stdout.write(self.style.SUCCESS(
            f'\nSummary: {created_count} created, {skipped_count} skipped, {failed_count} failed'
        ))
        
        # Check module configuration status
        for module_code, module_name in AccountMapping.MODULE_CHOICES:
            is_configured = AccountMapping.is_fully_configured(module_code)
            status = '✓' if is_configured else '✗'
            self.stdout.write(
                f'{status} {module_name}: {"Configured" if is_configured else "Incomplete"}'
            )




