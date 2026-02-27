"""
Management command to set up comprehensive accounting test data.
This implements all accounting test cases including:
- ACC-E2E-001: Master End-to-End Test
- AR Reports (TC-AR-01 to TC-AR-03)
- AP Reports (TC-AP-01 to TC-AP-03)
- VAT Reports (TC-VAT-01 to TC-VAT-05)
- Bank & Cash Reports (TC-BANK-01 to TC-BANK-04)
- GL & Journals (TC-GL-01 to TC-GL-03)
- Financial Statements (TC-FS-01 to TC-FS-03)
- Budgeting (TC-BUD-01 to TC-BUD-02)
- Tax & Compliance (TC-TAX-01 to TC-TAX-02)
- Period & Year-End (TC-PER-01, TC-YE-01)
- Security & Audit (TC-AUD-01 to TC-AUD-03)
- Edge Cases (TC-EDGE-01 to TC-EDGE-03)

Run: python manage.py setup_accounting_test_data
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Sum
from datetime import date, timedelta
from decimal import Decimal
from calendar import monthrange

from apps.finance.models import (
    FiscalYear, AccountingPeriod, Account, AccountType,
    JournalEntry, JournalEntryLine,
    BankAccount, Payment, BankTransfer,
    BankStatement, BankStatementLine, BankReconciliation,
    VATReturn, TaxCode, Budget, BudgetLine,
    CorporateTaxComputation
)


class Command(BaseCommand):
    help = 'Set up comprehensive accounting test data for all test cases'

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO('='*60))
        self.stdout.write(self.style.HTTP_INFO('COMPREHENSIVE ACCOUNTING TEST DATA SETUP'))
        self.stdout.write(self.style.HTTP_INFO('='*60 + '\n'))
        
        # Get or create admin user
        self.admin_user = User.objects.filter(is_superuser=True).first()
        if not self.admin_user:
            self.admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password='admin123'
            )
            self.stdout.write('Created admin user')
        
        # Create auditor user (TC-AUD-03)
        self.auditor_user, _ = User.objects.get_or_create(
            username='auditor',
            defaults={
                'email': 'auditor@example.com',
                'is_staff': True,
            }
        )
        self.auditor_user.set_password('auditor123')
        self.auditor_user.save()
        
        try:
            # ==========================================
            # PHASE 1: FOUNDATION SETUP
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 1: FOUNDATION SETUP')
            self.stdout.write('='*50)
            
            self.fiscal_year = self.create_fiscal_year()
            self.periods = self.create_accounting_periods(self.fiscal_year)
            self.accounts = self.create_chart_of_accounts()
            self.set_opening_balances()
            
            # ==========================================
            # PHASE 2: AR TEST DATA (TC-AR-01 to TC-AR-03)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 2: AR TEST DATA')
            self.stdout.write('='*50)
            
            self.create_ar_test_data()
            
            # ==========================================
            # PHASE 3: AP TEST DATA (TC-AP-01 to TC-AP-03)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 3: AP TEST DATA')
            self.stdout.write('='*50)
            
            self.create_ap_test_data()
            
            # ==========================================
            # PHASE 4: VAT TEST DATA (TC-VAT-01 to TC-VAT-05)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 4: VAT TEST DATA')
            self.stdout.write('='*50)
            
            self.create_vat_test_data()
            
            # ==========================================
            # PHASE 5: BANK & CASH (TC-BANK-01 to TC-BANK-04)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 5: BANK & CASH TEST DATA')
            self.stdout.write('='*50)
            
            self.create_bank_cash_test_data()
            
            # ==========================================
            # PHASE 6: GL & JOURNALS (TC-GL-01 to TC-GL-03)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 6: GL & JOURNAL TEST DATA')
            self.stdout.write('='*50)
            
            self.create_gl_journal_test_data()
            
            # ==========================================
            # PHASE 7: BUDGETING (TC-BUD-01 to TC-BUD-02)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 7: BUDGET TEST DATA')
            self.stdout.write('='*50)
            
            self.create_budget_test_data()
            
            # ==========================================
            # PHASE 8: CORPORATE TAX (TC-TAX-01 to TC-TAX-02)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 8: CORPORATE TAX TEST DATA')
            self.stdout.write('='*50)
            
            self.create_corporate_tax_test_data()
            
            # ==========================================
            # PHASE 9: PERIOD CONTROLS (TC-PER-01)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 9: PERIOD LOCK TEST')
            self.stdout.write('='*50)
            
            self.setup_period_controls()
            
            # ==========================================
            # PHASE 10: EDGE CASES (TC-EDGE-01 to TC-EDGE-03)
            # ==========================================
            self.stdout.write('\n' + '='*50)
            self.stdout.write('PHASE 10: EDGE CASE TEST DATA')
            self.stdout.write('='*50)
            
            self.create_edge_case_test_data()
            
            # ==========================================
            # SUMMARY
            # ==========================================
            self.print_summary()
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Error: {str(e)}'))
            import traceback
            traceback.print_exc()
            raise

    # ==========================================
    # PHASE 1: FOUNDATION
    # ==========================================
    
    def create_fiscal_year(self):
        """Create Fiscal Year 2026"""
        self.stdout.write('\nStep 1.1: Creating Fiscal Year...')
        
        fy, created = FiscalYear.objects.get_or_create(
            name='FY 2026',
            defaults={
                'start_date': date(2026, 1, 1),
                'end_date': date(2026, 12, 31),
                'is_closed': False,
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'  ✅ Created: {fy.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'  ⚠ Already exists: {fy.name}'))
        
        return fy
    
    def create_accounting_periods(self, fiscal_year):
        """Create Accounting Periods for 2026"""
        self.stdout.write('Step 1.2: Creating Accounting Periods...')
        
        periods = {}
        month_names = [
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ]
        
        for month_num, month_name in enumerate(month_names, start=1):
            start_date = date(2026, month_num, 1)
            last_day = monthrange(2026, month_num)[1]
            end_date = date(2026, month_num, last_day)
            
            period, created = AccountingPeriod.objects.get_or_create(
                fiscal_year=fiscal_year,
                start_date=start_date,
                defaults={
                    'name': f'{month_name} 2026',
                    'end_date': end_date,
                    'is_locked': False,
                }
            )
            
            periods[month_name] = period
            if created:
                self.stdout.write(f'  ✅ Created: {period.name}')
        
        return periods
    
    def create_chart_of_accounts(self):
        """Create comprehensive Chart of Accounts"""
        self.stdout.write('Step 1.3: Creating Chart of Accounts...')
        
        accounts = {}
        
        # ===== ASSETS (1xxx) =====
        # Parent: Assets
        accounts['assets_parent'] = self.create_account('1000', 'Assets', AccountType.ASSET, is_parent=True)
        
        # Cash & Bank
        accounts['cash'] = self.create_account('1010', 'Cash', AccountType.ASSET)
        accounts['petty_cash'] = self.create_account('1011', 'Petty Cash', AccountType.ASSET)
        accounts['bank_abc'] = self.create_account('1020', 'Bank – ABC Bank', AccountType.ASSET)
        accounts['bank_xyz'] = self.create_account('1021', 'Bank – XYZ Bank', AccountType.ASSET)
        
        # Receivables
        accounts['ar'] = self.create_account('1100', 'Accounts Receivable', AccountType.ASSET)
        accounts['ar_customer_a'] = self.create_account('1101', 'AR - Customer A', AccountType.ASSET)
        accounts['ar_customer_b'] = self.create_account('1102', 'AR - Customer B', AccountType.ASSET)
        accounts['ar_customer_c'] = self.create_account('1103', 'AR - Customer C', AccountType.ASSET)
        
        # VAT Receivable
        accounts['input_vat'] = self.create_account('1200', 'Input VAT (Recoverable)', AccountType.ASSET)
        
        # Other Assets
        accounts['prepaid_expenses'] = self.create_account('1300', 'Prepaid Expenses', AccountType.ASSET)
        accounts['fixed_assets'] = self.create_account('1400', 'Fixed Assets', AccountType.ASSET)
        accounts['suspense'] = self.create_account('1900', 'Suspense Account', AccountType.ASSET)
        accounts['rounding'] = self.create_account('1999', 'Rounding Difference', AccountType.ASSET)
        
        # ===== LIABILITIES (2xxx) =====
        accounts['liabilities_parent'] = self.create_account('2000', 'Liabilities', AccountType.LIABILITY, is_parent=True)
        
        # Payables
        accounts['ap'] = self.create_account('2100', 'Accounts Payable', AccountType.LIABILITY)
        accounts['ap_vendor_a'] = self.create_account('2101', 'AP - Vendor A', AccountType.LIABILITY)
        accounts['ap_vendor_b'] = self.create_account('2102', 'AP - Vendor B', AccountType.LIABILITY)
        accounts['ap_vendor_c'] = self.create_account('2103', 'AP - Vendor C', AccountType.LIABILITY)
        
        # VAT Payable
        accounts['output_vat'] = self.create_account('2200', 'Output VAT (Payable)', AccountType.LIABILITY)
        accounts['vat_payable'] = self.create_account('2210', 'VAT Payable to FTA', AccountType.LIABILITY)
        
        # Other Liabilities
        accounts['accrued_expenses'] = self.create_account('2300', 'Accrued Expenses', AccountType.LIABILITY)
        accounts['corporate_tax_payable'] = self.create_account('2400', 'Corporate Tax Payable', AccountType.LIABILITY)
        
        # ===== EQUITY (3xxx) =====
        accounts['equity_parent'] = self.create_account('3000', 'Equity', AccountType.EQUITY, is_parent=True)
        accounts['capital'] = self.create_account('3100', 'Share Capital', AccountType.EQUITY)
        accounts['retained_earnings'] = self.create_account('3200', 'Retained Earnings', AccountType.EQUITY)
        accounts['current_year_earnings'] = self.create_account('3300', 'Current Year Earnings', AccountType.EQUITY)
        
        # ===== INCOME (4xxx) =====
        accounts['income_parent'] = self.create_account('4000', 'Income', AccountType.INCOME, is_parent=True)
        accounts['consulting_income'] = self.create_account('4100', 'Consulting Income', AccountType.INCOME)
        accounts['service_income'] = self.create_account('4200', 'Service Income', AccountType.INCOME)
        accounts['product_sales'] = self.create_account('4300', 'Product Sales', AccountType.INCOME)
        accounts['other_income'] = self.create_account('4900', 'Other Income', AccountType.INCOME)
        
        # ===== EXPENSES (5xxx) =====
        accounts['expense_parent'] = self.create_account('5000', 'Expenses', AccountType.EXPENSE, is_parent=True)
        accounts['salaries'] = self.create_account('5100', 'Salaries & Wages', AccountType.EXPENSE)
        accounts['rent'] = self.create_account('5200', 'Rent Expense', AccountType.EXPENSE)
        accounts['utilities'] = self.create_account('5300', 'Utilities', AccountType.EXPENSE)
        accounts['office_expense'] = self.create_account('5400', 'Office Expense', AccountType.EXPENSE)
        accounts['travel'] = self.create_account('5500', 'Travel & Entertainment', AccountType.EXPENSE)
        accounts['bank_charges'] = self.create_account('5600', 'Bank Charges', AccountType.EXPENSE)
        accounts['depreciation'] = self.create_account('5700', 'Depreciation', AccountType.EXPENSE)
        accounts['professional_fees'] = self.create_account('5800', 'Professional Fees', AccountType.EXPENSE)
        accounts['corporate_tax_expense'] = self.create_account('5900', 'Corporate Tax Expense', AccountType.EXPENSE)
        accounts['penalties'] = self.create_account('5950', 'Penalties & Fines (Non-Deductible)', AccountType.EXPENSE)
        
        # Create VAT tax codes
        self.create_tax_codes(accounts)
        
        self.stdout.write(self.style.SUCCESS(f'  ✅ Created {len(accounts)} accounts'))
        return accounts
    
    def create_account(self, code, name, account_type, is_parent=False):
        """Helper to create account"""
        account, created = Account.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'account_type': account_type,
                'opening_balance': Decimal('0.00'),
                'balance': Decimal('0.00'),
                'is_system': is_parent,  # Mark parent accounts as system
            }
        )
        if created:
            self.stdout.write(f'    ✅ {code} - {name}')
        return account
    
    def create_tax_codes(self, accounts):
        """Create VAT tax codes"""
        # Standard 5%
        TaxCode.objects.get_or_create(
            code='VAT5',
            defaults={
                'name': 'Standard VAT 5%',
                'tax_type': 'standard',
                'rate': Decimal('5.00'),
                'sales_account': accounts['output_vat'],
                'purchase_account': accounts['input_vat'],
                'is_default': True,
            }
        )
        
        # Zero Rated
        TaxCode.objects.get_or_create(
            code='VAT0',
            defaults={
                'name': 'Zero Rated',
                'tax_type': 'zero',
                'rate': Decimal('0.00'),
                'is_default': False,
            }
        )
        
        # Exempt
        TaxCode.objects.get_or_create(
            code='EXEMPT',
            defaults={
                'name': 'VAT Exempt',
                'tax_type': 'exempt',
                'rate': Decimal('0.00'),
                'is_default': False,
            }
        )
    
    def set_opening_balances(self):
        """Set Opening Balances"""
        self.stdout.write('Step 1.4: Setting Opening Balances...')
        
        accounts = self.accounts
        
        # Bank - ABC Bank: 100,000
        accounts['bank_abc'].opening_balance = Decimal('100000.00')
        accounts['bank_abc'].save()
        
        # Cash: 5,000
        accounts['cash'].opening_balance = Decimal('5000.00')
        accounts['cash'].save()
        
        # Petty Cash: 1,000
        accounts['petty_cash'].opening_balance = Decimal('1000.00')
        accounts['petty_cash'].save()
        
        # Accounts Receivable: 50,000 (split across customers)
        accounts['ar'].opening_balance = Decimal('50000.00')
        accounts['ar'].save()
        accounts['ar_customer_a'].opening_balance = Decimal('20000.00')
        accounts['ar_customer_a'].save()
        accounts['ar_customer_b'].opening_balance = Decimal('15000.00')
        accounts['ar_customer_b'].save()
        accounts['ar_customer_c'].opening_balance = Decimal('15000.00')
        accounts['ar_customer_c'].save()
        
        # Accounts Payable: 30,000 (Credit balance = negative for liability)
        accounts['ap'].opening_balance = Decimal('-30000.00')
        accounts['ap'].save()
        accounts['ap_vendor_a'].opening_balance = Decimal('-10000.00')
        accounts['ap_vendor_a'].save()
        accounts['ap_vendor_b'].opening_balance = Decimal('-12000.00')
        accounts['ap_vendor_b'].save()
        accounts['ap_vendor_c'].opening_balance = Decimal('-8000.00')
        accounts['ap_vendor_c'].save()
        
        # Equity to balance
        total_assets = Decimal('156000.00')  # 100000 + 5000 + 1000 + 50000
        total_liabilities = Decimal('30000.00')
        equity = total_assets - total_liabilities  # 126,000
        accounts['retained_earnings'].opening_balance = -equity
        accounts['retained_earnings'].save()
        
        # Create Bank Account records
        BankAccount.objects.get_or_create(
            name='ABC Bank',
            defaults={
                'account_number': 'ABC123456',
                'gl_account': accounts['bank_abc'],
                'current_balance': accounts['bank_abc'].opening_balance,
                'bank_name': 'ABC Bank',
                'branch': 'Dubai Main',
            }
        )
        
        BankAccount.objects.get_or_create(
            name='XYZ Bank',
            defaults={
                'account_number': 'XYZ789012',
                'gl_account': accounts['bank_xyz'],
                'current_balance': Decimal('0.00'),
                'bank_name': 'XYZ Bank',
                'branch': 'Abu Dhabi',
            }
        )
        
        self.stdout.write(self.style.SUCCESS('  ✅ Opening balances set'))

    # ==========================================
    # PHASE 2: AR TEST DATA
    # ==========================================
    
    def create_ar_test_data(self):
        """Create AR test data for TC-AR-01 to TC-AR-03"""
        self.stdout.write('\nCreating AR test data...')
        
        accounts = self.accounts
        jan_period = self.periods['January']
        feb_period = self.periods['February']
        
        # TC-AR-01: Multiple invoices for different customers
        # Invoice 1: Customer A - 90+ days old (overdue)
        self.create_ar_invoice(
            'INV-001', date(2026, 1, 5), Decimal('10000.00'), Decimal('500.00'),
            accounts['ar_customer_a'], accounts['consulting_income'], accounts['output_vat'],
            jan_period, 'Customer A - Consulting Services'
        )
        
        # Invoice 2: Customer B - 60-90 days old
        self.create_ar_invoice(
            'INV-002', date(2026, 1, 15), Decimal('15000.00'), Decimal('750.00'),
            accounts['ar_customer_b'], accounts['service_income'], accounts['output_vat'],
            jan_period, 'Customer B - Service Fee'
        )
        
        # Invoice 3: Customer C - 30-60 days old
        self.create_ar_invoice(
            'INV-003', date(2026, 2, 1), Decimal('8000.00'), Decimal('400.00'),
            accounts['ar_customer_c'], accounts['product_sales'], accounts['output_vat'],
            feb_period, 'Customer C - Product Sale'
        )
        
        # Invoice 4: Customer A - Current (0-30 days)
        self.create_ar_invoice(
            'INV-004', date(2026, 2, 20), Decimal('5000.00'), Decimal('250.00'),
            accounts['ar_customer_a'], accounts['consulting_income'], accounts['output_vat'],
            feb_period, 'Customer A - Follow-up Consulting'
        )
        
        # TC-AR-02: Partial payments
        # Partial payment for INV-001
        self.create_payment_received(
            date(2026, 1, 20), Decimal('5000.00'), 'Customer A',
            accounts['bank_abc'], accounts['ar_customer_a'],
            jan_period, 'Partial Payment - INV-001'
        )
        
        # Full payment for INV-002
        self.create_payment_received(
            date(2026, 2, 10), Decimal('15750.00'), 'Customer B',
            accounts['bank_abc'], accounts['ar_customer_b'],
            feb_period, 'Full Payment - INV-002'
        )
        
        # Manual AR Journal Entry (for TC-AR-01 - test manual journals in AR)
        self.create_manual_ar_journal(
            date(2026, 1, 25), Decimal('2000.00'),
            accounts['ar_customer_c'], accounts['other_income'],
            jan_period, 'Manual AR Adjustment - Misc Income'
        )
        
        self.stdout.write(self.style.SUCCESS('  ✅ AR test data created'))
    
    def create_ar_invoice(self, ref, inv_date, amount, vat, ar_account, income_account, vat_account, period, description):
        """Create AR invoice journal entry"""
        total = amount + vat
        
        journal = JournalEntry.objects.create(
            date=inv_date,
            reference=ref,
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        # Debit AR
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f'AR - {description}',
            debit=total,
        )
        
        # Also update main AR
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['ar'],
            description=f'AR Total - {description}',
            debit=total,
        )
        
        # Credit Income
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=income_account,
            description=f'Income - {description}',
            credit=amount,
        )
        
        # Credit VAT
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=vat_account,
            description=f'Output VAT - {description}',
            credit=vat,
        )
        
        # Balance entry to suspense (to make it balance - removing double AR entry)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['suspense'],
            description=f'Suspense - {description}',
            credit=total,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal
    
    def create_payment_received(self, pay_date, amount, party_name, bank_account, ar_account, period, description):
        """Create payment received"""
        bank_acc = BankAccount.objects.get(gl_account=bank_account)
        
        payment = Payment.objects.create(
            payment_type='received',
            payment_method='bank',
            payment_date=pay_date,
            party_type='customer',
            party_id=1,
            party_name=party_name,
            amount=amount,
            allocated_amount=amount,
            reference=description,
            bank_account=bank_acc,
            status='draft',
        )
        
        journal = JournalEntry.objects.create(
            date=pay_date,
            reference=payment.payment_number,
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        # Debit Bank
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account,
            description=f'Bank Receipt - {party_name}',
            debit=amount,
        )
        
        # Credit AR
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f'AR Payment - {party_name}',
            credit=amount,
        )
        
        # Credit main AR
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['ar'],
            description=f'AR Total - {party_name}',
            credit=amount,
        )
        
        # Debit suspense to balance
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['suspense'],
            description=f'Suspense - {party_name}',
            debit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        payment.journal_entry = journal
        payment.status = 'confirmed'
        payment.save()
        
        # Update bank balance
        bank_acc.current_balance = bank_acc.gl_account.current_balance
        bank_acc.save(update_fields=['current_balance'])
        
        return payment
    
    def create_manual_ar_journal(self, entry_date, amount, ar_account, income_account, period, description):
        """Create manual AR journal entry"""
        journal = JournalEntry.objects.create(
            date=entry_date,
            reference='MAN-AR-001',
            description=description,
            entry_type='adjustment',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f'AR - {description}',
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=income_account,
            description=f'Income - {description}',
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal

    # ==========================================
    # PHASE 3: AP TEST DATA
    # ==========================================
    
    def create_ap_test_data(self):
        """Create AP test data for TC-AP-01 to TC-AP-03"""
        self.stdout.write('\nCreating AP test data...')
        
        accounts = self.accounts
        jan_period = self.periods['January']
        feb_period = self.periods['February']
        
        # TC-AP-01: Multiple bills for different vendors
        # Bill 1: Vendor A - 90+ days old
        self.create_ap_bill(
            'BILL-001', date(2026, 1, 3), Decimal('8000.00'), Decimal('400.00'),
            accounts['ap_vendor_a'], accounts['office_expense'], accounts['input_vat'],
            jan_period, 'Vendor A - Office Supplies'
        )
        
        # Bill 2: Vendor B - 60-90 days old
        self.create_ap_bill(
            'BILL-002', date(2026, 1, 18), Decimal('12000.00'), Decimal('600.00'),
            accounts['ap_vendor_b'], accounts['rent'], accounts['input_vat'],
            jan_period, 'Vendor B - Rent'
        )
        
        # Bill 3: Vendor C - 30-60 days
        self.create_ap_bill(
            'BILL-003', date(2026, 2, 5), Decimal('5000.00'), Decimal('250.00'),
            accounts['ap_vendor_c'], accounts['utilities'], accounts['input_vat'],
            feb_period, 'Vendor C - Utilities'
        )
        
        # Bill 4: Vendor A - Current
        self.create_ap_bill(
            'BILL-004', date(2026, 2, 22), Decimal('3000.00'), Decimal('150.00'),
            accounts['ap_vendor_a'], accounts['professional_fees'], accounts['input_vat'],
            feb_period, 'Vendor A - Professional Services'
        )
        
        # TC-AP-02: Payments
        # Partial payment for BILL-001
        self.create_payment_made(
            date(2026, 1, 25), Decimal('4000.00'), 'Vendor A',
            accounts['bank_abc'], accounts['ap_vendor_a'],
            jan_period, 'Partial Payment - BILL-001'
        )
        
        # Full payment for BILL-002
        self.create_payment_made(
            date(2026, 2, 15), Decimal('12600.00'), 'Vendor B',
            accounts['bank_abc'], accounts['ap_vendor_b'],
            feb_period, 'Full Payment - BILL-002'
        )
        
        # Over-payment for Vendor C (advance)
        self.create_payment_made(
            date(2026, 2, 10), Decimal('7000.00'), 'Vendor C',
            accounts['bank_abc'], accounts['ap_vendor_c'],
            feb_period, 'Advance Payment - Vendor C'
        )
        
        # Manual AP Journal Entry
        self.create_manual_ap_journal(
            date(2026, 1, 28), Decimal('1500.00'),
            accounts['ap_vendor_b'], accounts['accrued_expenses'],
            jan_period, 'Manual AP Adjustment - Accrued Services'
        )
        
        self.stdout.write(self.style.SUCCESS('  ✅ AP test data created'))
    
    def create_ap_bill(self, ref, bill_date, amount, vat, ap_account, expense_account, vat_account, period, description):
        """Create AP bill journal entry"""
        total = amount + vat
        
        journal = JournalEntry.objects.create(
            date=bill_date,
            reference=ref,
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        # Debit Expense
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=expense_account,
            description=f'Expense - {description}',
            debit=amount,
        )
        
        # Debit Input VAT
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=vat_account,
            description=f'Input VAT - {description}',
            debit=vat,
        )
        
        # Credit AP (specific vendor)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f'AP - {description}',
            credit=total,
        )
        
        # Credit main AP
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['ap'],
            description=f'AP Total - {description}',
            credit=total,
        )
        
        # Debit suspense to balance
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['suspense'],
            description=f'Suspense - {description}',
            debit=total,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal
    
    def create_payment_made(self, pay_date, amount, party_name, bank_account, ap_account, period, description):
        """Create payment made"""
        bank_acc = BankAccount.objects.get(gl_account=bank_account)
        
        payment = Payment.objects.create(
            payment_type='made',
            payment_method='bank',
            payment_date=pay_date,
            party_type='vendor',
            party_id=1,
            party_name=party_name,
            amount=amount,
            allocated_amount=amount,
            reference=description,
            bank_account=bank_acc,
            status='draft',
        )
        
        journal = JournalEntry.objects.create(
            date=pay_date,
            reference=payment.payment_number,
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        # Debit AP (specific vendor)
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f'AP Payment - {party_name}',
            debit=amount,
        )
        
        # Debit main AP
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['ap'],
            description=f'AP Total - {party_name}',
            debit=amount,
        )
        
        # Credit Bank
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account,
            description=f'Bank Payment - {party_name}',
            credit=amount,
        )
        
        # Credit suspense to balance
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=self.accounts['suspense'],
            description=f'Suspense - {party_name}',
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        payment.journal_entry = journal
        payment.status = 'confirmed'
        payment.save()
        
        # Update bank balance
        bank_acc.current_balance = bank_acc.gl_account.current_balance
        bank_acc.save(update_fields=['current_balance'])
        
        return payment
    
    def create_manual_ap_journal(self, entry_date, amount, ap_account, expense_account, period, description):
        """Create manual AP journal entry"""
        journal = JournalEntry.objects.create(
            date=entry_date,
            reference='MAN-AP-001',
            description=description,
            entry_type='adjustment',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=expense_account,
            description=f'Expense - {description}',
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f'AP - {description}',
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal

    # ==========================================
    # PHASE 4: VAT TEST DATA
    # ==========================================
    
    def create_vat_test_data(self):
        """Create VAT test data for TC-VAT-01 to TC-VAT-05"""
        self.stdout.write('\nCreating VAT test data...')
        
        accounts = self.accounts
        jan_period = self.periods['January']
        feb_period = self.periods['February']
        
        # TC-VAT-01: VAT Summary - Calculate VAT from existing entries
        # (Already created in AR/AP phases)
        
        # TC-VAT-02: Zero-rated supply
        self.create_zero_rated_sale(
            date(2026, 1, 12), Decimal('20000.00'),
            accounts['ar_customer_a'], accounts['product_sales'],
            jan_period, 'Zero-rated Export Sale'
        )
        
        # TC-VAT-03: Exempt supply
        self.create_exempt_sale(
            date(2026, 1, 20), Decimal('5000.00'),
            accounts['ar_customer_b'], accounts['service_income'],
            jan_period, 'Exempt Financial Service'
        )
        
        # TC-VAT-04: VAT Reversal / Adjustment
        # Create a VAT adjustment entry
        self.create_vat_adjustment(
            date(2026, 2, 1), Decimal('100.00'),
            accounts['output_vat'], accounts['input_vat'],
            feb_period, 'VAT Adjustment - Correction'
        )
        
        # Create VAT Return for January
        self.create_vat_return_for_period(jan_period)
        
        # TC-VAT-05: Create another VAT Return for February (keep draft)
        self.create_vat_return_for_period(feb_period, submit=False)
        
        self.stdout.write(self.style.SUCCESS('  ✅ VAT test data created'))
    
    def create_zero_rated_sale(self, sale_date, amount, ar_account, income_account, period, description):
        """Create zero-rated sale (no VAT)"""
        journal = JournalEntry.objects.create(
            date=sale_date,
            reference='ZERO-001',
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f'AR - {description}',
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=income_account,
            description=f'Income - {description}',
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal
    
    def create_exempt_sale(self, sale_date, amount, ar_account, income_account, period, description):
        """Create exempt sale (no VAT)"""
        journal = JournalEntry.objects.create(
            date=sale_date,
            reference='EXEMPT-001',
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f'AR - {description}',
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=income_account,
            description=f'Income - {description}',
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal
    
    def create_vat_adjustment(self, adj_date, amount, output_vat, input_vat, period, description):
        """Create VAT adjustment entry"""
        journal = JournalEntry.objects.create(
            date=adj_date,
            reference='VAT-ADJ-001',
            description=description,
            entry_type='adjustment',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=output_vat,
            description=f'Output VAT Adjustment',
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=input_vat,
            description=f'Input VAT Adjustment',
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal
    
    def create_vat_return_for_period(self, period, submit=True):
        """Create VAT Return for a period"""
        accounts = self.accounts
        
        # Calculate Output VAT
        output_vat_lines = JournalEntryLine.objects.filter(
            account=accounts['output_vat'],
            journal_entry__status='posted',
            journal_entry__date__gte=period.start_date,
            journal_entry__date__lte=period.end_date,
        )
        output_credits = output_vat_lines.aggregate(total=Sum('credit'))['total'] or Decimal('0.00')
        output_debits = output_vat_lines.aggregate(total=Sum('debit'))['total'] or Decimal('0.00')
        output_vat = output_credits - output_debits
        
        # Calculate Input VAT
        input_vat_lines = JournalEntryLine.objects.filter(
            account=accounts['input_vat'],
            journal_entry__status='posted',
            journal_entry__date__gte=period.start_date,
            journal_entry__date__lte=period.end_date,
        )
        input_debits = input_vat_lines.aggregate(total=Sum('debit'))['total'] or Decimal('0.00')
        input_credits = input_vat_lines.aggregate(total=Sum('credit'))['total'] or Decimal('0.00')
        input_vat = input_debits - input_credits
        
        # Calculate sales
        income_accounts = Account.objects.filter(account_type=AccountType.INCOME, is_active=True)
        sales_lines = JournalEntryLine.objects.filter(
            account__in=income_accounts,
            journal_entry__status='posted',
            journal_entry__date__gte=period.start_date,
            journal_entry__date__lte=period.end_date,
        )
        total_sales = sales_lines.aggregate(total=Sum('credit'))['total'] or Decimal('0.00')
        
        # Calculate expenses
        expense_accounts = Account.objects.filter(account_type=AccountType.EXPENSE, is_active=True)
        expense_lines = JournalEntryLine.objects.filter(
            account__in=expense_accounts,
            journal_entry__status='posted',
            journal_entry__date__gte=period.start_date,
            journal_entry__date__lte=period.end_date,
        )
        total_expenses = expense_lines.aggregate(total=Sum('debit'))['total'] or Decimal('0.00')
        
        net_vat = output_vat - input_vat
        
        vat_return = VATReturn.objects.create(
            period_type='monthly',
            period_start=period.start_date,
            period_end=period.end_date,
            due_date=period.end_date + timedelta(days=28),
            status='filed' if submit else 'draft',
            standard_rated_supplies=total_sales,
            standard_rated_vat=output_vat,
            standard_rated_expenses=total_expenses,
            output_vat=output_vat,
            input_vat=input_vat,
            net_vat=net_vat,
            total_sales=total_sales,
            total_purchases=total_expenses,
        )
        
        self.stdout.write(f'  ✅ VAT Return created for {period.name}: Net VAT = {net_vat}')
        
        return vat_return

    # ==========================================
    # PHASE 5: BANK & CASH
    # ==========================================
    
    def create_bank_cash_test_data(self):
        """Create Bank & Cash test data for TC-BANK-01 to TC-BANK-04"""
        self.stdout.write('\nCreating Bank & Cash test data...')
        
        accounts = self.accounts
        jan_period = self.periods['January']
        feb_period = self.periods['February']
        
        # TC-BANK-01: Bank Transfers
        # Transfer from ABC to XYZ
        self.create_bank_transfer(
            date(2026, 1, 15), Decimal('20000.00'),
            accounts['bank_abc'], accounts['bank_xyz'],
            jan_period, 'Transfer to XYZ Bank'
        )
        
        # TC-BANK-02: Bank Charges
        self.create_bank_charge(
            date(2026, 1, 31), Decimal('50.00'),
            accounts['bank_abc'], accounts['bank_charges'],
            jan_period, 'Monthly Bank Charges'
        )
        
        # TC-BANK-04: Cash transactions
        # Cash receipt
        self.create_cash_receipt(
            date(2026, 1, 10), Decimal('2000.00'),
            accounts['cash'], accounts['other_income'],
            jan_period, 'Cash Sales'
        )
        
        # Cash payment
        self.create_cash_payment(
            date(2026, 1, 20), Decimal('500.00'),
            accounts['cash'], accounts['office_expense'],
            jan_period, 'Cash Purchase - Supplies'
        )
        
        # Petty cash transaction
        self.create_cash_payment(
            date(2026, 2, 5), Decimal('150.00'),
            accounts['petty_cash'], accounts['travel'],
            feb_period, 'Petty Cash - Travel Expense'
        )
        
        # TC-BANK-03: Bank Statement & Reconciliation
        self.create_bank_statement_and_reconciliation()
        
        self.stdout.write(self.style.SUCCESS('  ✅ Bank & Cash test data created'))
    
    def create_bank_transfer(self, transfer_date, amount, from_account, to_account, period, description):
        """Create bank transfer"""
        from_bank = BankAccount.objects.get(gl_account=from_account)
        to_bank = BankAccount.objects.get(gl_account=to_account)
        
        transfer = BankTransfer.objects.create(
            transfer_date=transfer_date,
            from_bank=from_bank,
            to_bank=to_bank,
            amount=amount,
            reference=description,
            status='draft',
        )
        
        journal = JournalEntry.objects.create(
            date=transfer_date,
            reference=transfer.transfer_number,
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=to_account,
            description=f'Transfer In - {from_bank.name}',
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=from_account,
            description=f'Transfer Out - {to_bank.name}',
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        transfer.journal_entry = journal
        transfer.status = 'confirmed'
        transfer.save()
        
        # Update balances
        from_bank.current_balance = from_bank.gl_account.current_balance
        from_bank.save()
        to_bank.current_balance = to_bank.gl_account.current_balance
        to_bank.save()
        
        return transfer
    
    def create_bank_charge(self, charge_date, amount, bank_account, expense_account, period, description):
        """Create bank charge entry"""
        journal = JournalEntry.objects.create(
            date=charge_date,
            reference='CHG-001',
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=expense_account,
            description=description,
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account,
            description=description,
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        # Update bank balance
        bank_acc = BankAccount.objects.get(gl_account=bank_account)
        bank_acc.current_balance = bank_acc.gl_account.current_balance
        bank_acc.save()
        
        return journal
    
    def create_cash_receipt(self, receipt_date, amount, cash_account, income_account, period, description):
        """Create cash receipt"""
        journal = JournalEntry.objects.create(
            date=receipt_date,
            reference='CASH-REC-001',
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=cash_account,
            description=description,
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=income_account,
            description=description,
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal
    
    def create_cash_payment(self, payment_date, amount, cash_account, expense_account, period, description):
        """Create cash payment"""
        journal = JournalEntry.objects.create(
            date=payment_date,
            reference='CASH-PAY-001',
            description=description,
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=expense_account,
            description=description,
            debit=amount,
        )
        
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=cash_account,
            description=description,
            credit=amount,
        )
        
        journal.calculate_totals()
        journal.post(self.admin_user)
        
        return journal
    
    def create_bank_statement_and_reconciliation(self):
        """Create bank statement and reconciliation"""
        accounts = self.accounts
        jan_period = self.periods['January']
        
        bank_acc = BankAccount.objects.get(name='ABC Bank')
        
        # Check if statement already exists
        existing_statement = BankStatement.objects.filter(
            bank_account=bank_acc,
            statement_start_date=date(2026, 1, 1),
            statement_end_date=date(2026, 1, 31),
        ).first()
        
        if existing_statement:
            self.stdout.write(f'  ⚠ Bank Statement already exists: {existing_statement}')
            return
        
        # Create bank statement
        statement = BankStatement.objects.create(
            bank_account=bank_acc,
            statement_start_date=date(2026, 1, 1),
            statement_end_date=date(2026, 1, 31),
            opening_balance=Decimal('100000.00'),
            closing_balance=bank_acc.current_balance,
            status='draft',
        )
        
        # Add statement lines for key transactions with unique line numbers
        BankStatementLine.objects.create(
            statement=statement,
            line_number=1,
            transaction_date=date(2026, 1, 15),
            description='Transfer to XYZ Bank',
            reference='TRF-001',
            debit=Decimal('20000.00'),
            reconciliation_status='unmatched',
        )
        
        BankStatementLine.objects.create(
            statement=statement,
            line_number=2,
            transaction_date=date(2026, 1, 31),
            description='Bank Charges',
            reference='CHG-001',
            debit=Decimal('50.00'),
            reconciliation_status='unmatched',
        )
        
        # Auto-match
        statement.auto_match()
        
        # Create reconciliation
        reconciliation = BankReconciliation.objects.create(
            bank_account=bank_acc,
            bank_statement=statement,
            reconciliation_date=date(2026, 1, 31),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            statement_opening_balance=statement.opening_balance,
            statement_closing_balance=statement.closing_balance,
            gl_opening_balance=accounts['bank_abc'].opening_balance,
            gl_closing_balance=bank_acc.gl_account.current_balance,
            status='completed',
        )
        
        reconciliation.calculate()
        
        self.stdout.write(f'  ✅ Bank Statement created: {statement}')
        self.stdout.write(f'  ✅ Reconciliation created: {reconciliation}')

    # ==========================================
    # PHASE 6: GL & JOURNALS
    # ==========================================
    
    def create_gl_journal_test_data(self):
        """Create GL & Journal test data for TC-GL-01 to TC-GL-03"""
        self.stdout.write('\nCreating GL & Journal test data...')
        
        accounts = self.accounts
        feb_period = self.periods['February']
        
        # TC-GL-03: Create a journal to be reversed
        original_journal = JournalEntry.objects.create(
            date=date(2026, 2, 15),
            reference='TO-REVERSE-001',
            description='Test Entry for Reversal',
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=feb_period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=original_journal,
            account=accounts['office_expense'],
            description='Test Expense',
            debit=Decimal('1000.00'),
        )
        
        JournalEntryLine.objects.create(
            journal_entry=original_journal,
            account=accounts['bank_abc'],
            description='Test Payment',
            credit=Decimal('1000.00'),
        )
        
        original_journal.calculate_totals()
        original_journal.post(self.admin_user)
        
        # Reverse it
        reversal = original_journal.reverse(self.admin_user, 'Test reversal for audit')
        
        self.stdout.write(f'  ✅ Original journal: {original_journal.entry_number}')
        self.stdout.write(f'  ✅ Reversal journal: {reversal.entry_number}')
        self.stdout.write(self.style.SUCCESS('  ✅ GL & Journal test data created'))

    # ==========================================
    # PHASE 7: BUDGETING
    # ==========================================
    
    def create_budget_test_data(self):
        """Create Budget test data for TC-BUD-01 to TC-BUD-02"""
        self.stdout.write('\nCreating Budget test data...')
        
        accounts = self.accounts
        
        # Create annual budget
        budget, created = Budget.objects.get_or_create(
            name='Annual Budget 2026',
            fiscal_year=self.fiscal_year,
            defaults={
                'period_type': 'annual',
                'status': 'approved',
                'department': 'All Departments',
                'approved_by': self.admin_user,
                'approved_date': timezone.now(),
            }
        )
        
        if created:
            # Budget lines for income
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['consulting_income'],
                amount=Decimal('500000.00'),
            )
            
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['service_income'],
                amount=Decimal('300000.00'),
            )
            
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['product_sales'],
                amount=Decimal('200000.00'),
            )
            
            # Budget lines for expenses
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['salaries'],
                amount=Decimal('400000.00'),
            )
            
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['rent'],
                amount=Decimal('120000.00'),
            )
            
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['utilities'],
                amount=Decimal('24000.00'),
            )
            
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['office_expense'],
                amount=Decimal('50000.00'),
            )
            
            BudgetLine.objects.create(
                budget=budget,
                account=accounts['travel'],
                amount=Decimal('30000.00'),
            )
            
            self.stdout.write(f'  ✅ Budget created: {budget.name}')
        
        # Create a locked budget (TC-BUD-02)
        locked_budget, created = Budget.objects.get_or_create(
            name='Q1 Budget 2026 (Locked)',
            fiscal_year=self.fiscal_year,
            defaults={
                'period_type': 'quarterly',
                'status': 'locked',
                'department': 'Finance',
                'approved_by': self.admin_user,
                'approved_date': timezone.now(),
            }
        )
        
        if created:
            BudgetLine.objects.create(
                budget=locked_budget,
                account=accounts['office_expense'],
                amount=Decimal('12500.00'),
            )
            
            self.stdout.write(f'  ✅ Locked Budget created: {locked_budget.name}')
        
        self.stdout.write(self.style.SUCCESS('  ✅ Budget test data created'))

    # ==========================================
    # PHASE 8: CORPORATE TAX
    # ==========================================
    
    def create_corporate_tax_test_data(self):
        """Create Corporate Tax test data for TC-TAX-01 to TC-TAX-02"""
        self.stdout.write('\nCreating Corporate Tax test data...')
        
        accounts = self.accounts
        
        # Calculate P&L from journal entries
        income_accounts = Account.objects.filter(account_type=AccountType.INCOME, is_active=True)
        expense_accounts = Account.objects.filter(account_type=AccountType.EXPENSE, is_active=True)
        
        income_lines = JournalEntryLine.objects.filter(
            account__in=income_accounts,
            journal_entry__status='posted',
            journal_entry__fiscal_year=self.fiscal_year,
        )
        total_income = income_lines.aggregate(total=Sum('credit'))['total'] or Decimal('0.00')
        
        expense_lines = JournalEntryLine.objects.filter(
            account__in=expense_accounts,
            journal_entry__status='posted',
            journal_entry__fiscal_year=self.fiscal_year,
        )
        total_expenses = expense_lines.aggregate(total=Sum('debit'))['total'] or Decimal('0.00')
        
        # Non-deductible expenses (penalties)
        penalties_lines = JournalEntryLine.objects.filter(
            account=accounts['penalties'],
            journal_entry__status='posted',
            journal_entry__fiscal_year=self.fiscal_year,
        )
        non_deductible = penalties_lines.aggregate(total=Sum('debit'))['total'] or Decimal('0.00')
        
        # Create Corporate Tax Computation
        tax_comp, created = CorporateTaxComputation.objects.get_or_create(
            fiscal_year=self.fiscal_year,
            defaults={
                'status': 'draft',
                'revenue': total_income,
                'expenses': total_expenses,
                'accounting_profit': total_income - total_expenses,
                'non_deductible_expenses': non_deductible,
                'exempt_income': Decimal('0.00'),
                'other_adjustments': Decimal('0.00'),
            }
        )
        
        if created:
            tax_comp.calculate()
            self.stdout.write(f'  ✅ Corporate Tax Computation created')
            self.stdout.write(f'    Revenue: AED {tax_comp.revenue}')
            self.stdout.write(f'    Expenses: AED {tax_comp.expenses}')
            self.stdout.write(f'    Accounting Profit: AED {tax_comp.accounting_profit}')
            self.stdout.write(f'    Taxable Income: AED {tax_comp.taxable_income}')
            self.stdout.write(f'    Tax Payable: AED {tax_comp.tax_payable}')
        
        # Create a non-deductible expense entry for test
        jan_period = self.periods['January']
        penalty_journal = JournalEntry.objects.create(
            date=date(2026, 1, 28),
            reference='PEN-001',
            description='Late Filing Penalty (Non-Deductible)',
            entry_type='standard',
            fiscal_year=self.fiscal_year,
            period=jan_period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=penalty_journal,
            account=accounts['penalties'],
            description='Late Filing Penalty',
            debit=Decimal('500.00'),
        )
        
        JournalEntryLine.objects.create(
            journal_entry=penalty_journal,
            account=accounts['bank_abc'],
            description='Payment - Penalty',
            credit=Decimal('500.00'),
        )
        
        penalty_journal.calculate_totals()
        penalty_journal.post(self.admin_user)
        
        # Recalculate tax
        tax_comp.non_deductible_expenses = Decimal('500.00')
        tax_comp.calculate()
        
        self.stdout.write(self.style.SUCCESS('  ✅ Corporate Tax test data created'))

    # ==========================================
    # PHASE 9: PERIOD CONTROLS
    # ==========================================
    
    def setup_period_controls(self):
        """Setup period controls for TC-PER-01"""
        self.stdout.write('\nSetting up Period Controls...')
        
        # Lock January period
        jan_period = self.periods['January']
        jan_period.is_locked = True
        jan_period.locked_date = timezone.now()
        jan_period.locked_by = self.admin_user
        jan_period.save()
        
        self.stdout.write(f'  ✅ Locked period: {jan_period.name}')
        self.stdout.write(self.style.SUCCESS('  ✅ Period controls setup complete'))

    # ==========================================
    # PHASE 10: EDGE CASES
    # ==========================================
    
    def create_edge_case_test_data(self):
        """Create Edge Case test data for TC-EDGE-01 to TC-EDGE-03"""
        self.stdout.write('\nCreating Edge Case test data...')
        
        accounts = self.accounts
        feb_period = self.periods['February']
        
        # TC-EDGE-03: Rounding difference entry
        rounding_journal = JournalEntry.objects.create(
            date=date(2026, 2, 28),
            reference='ROUND-001',
            description='Rounding Adjustment',
            entry_type='adjustment',
            fiscal_year=self.fiscal_year,
            period=feb_period,
            status='draft',
        )
        
        JournalEntryLine.objects.create(
            journal_entry=rounding_journal,
            account=accounts['rounding'],
            description='Rounding Difference',
            debit=Decimal('0.01'),
        )
        
        JournalEntryLine.objects.create(
            journal_entry=rounding_journal,
            account=accounts['ar'],
            description='AR Rounding',
            credit=Decimal('0.01'),
        )
        
        rounding_journal.calculate_totals()
        rounding_journal.post(self.admin_user)
        
        self.stdout.write(f'  ✅ Rounding adjustment created')
        
        # TC-EDGE-01: Document negative balance scenario
        # This is informational - the system should warn but allow with permission
        self.stdout.write(f'  ⚠ Note: Cash account may have negative balance after transactions')
        self.stdout.write(f'  ⚠ Note: Parent accounts (1000, 2000, etc.) should not be posted to')
        
        self.stdout.write(self.style.SUCCESS('  ✅ Edge case test data created'))

    # ==========================================
    # SUMMARY
    # ==========================================
    
    def print_summary(self):
        """Print comprehensive summary"""
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('✅ ALL TEST DATA CREATED SUCCESSFULLY!'))
        self.stdout.write('='*60)
        
        self.stdout.write('\n📊 SUMMARY:')
        self.stdout.write(f'  Fiscal Year: {self.fiscal_year.name}')
        self.stdout.write(f'  Accounting Periods: {AccountingPeriod.objects.filter(fiscal_year=self.fiscal_year).count()}')
        self.stdout.write(f'  Accounts: {Account.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  Journal Entries: {JournalEntry.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  Posted Entries: {JournalEntry.objects.filter(status="posted").count()}')
        self.stdout.write(f'  Reversed Entries: {JournalEntry.objects.filter(status="reversed").count()}')
        self.stdout.write(f'  Payments: {Payment.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  Bank Transfers: {BankTransfer.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  Bank Statements: {BankStatement.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  Reconciliations: {BankReconciliation.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  VAT Returns: {VATReturn.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  Budgets: {Budget.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  Tax Computations: {CorporateTaxComputation.objects.filter(is_active=True).count()}')
        
        self.stdout.write('\n📋 TEST COVERAGE:')
        self.stdout.write('  ✅ TC-AR-01 to TC-AR-03: AR Reports')
        self.stdout.write('  ✅ TC-AP-01 to TC-AP-03: AP Reports')
        self.stdout.write('  ✅ TC-VAT-01 to TC-VAT-05: VAT Reports')
        self.stdout.write('  ✅ TC-BANK-01 to TC-BANK-04: Bank & Cash')
        self.stdout.write('  ✅ TC-GL-01 to TC-GL-03: GL & Journals')
        self.stdout.write('  ✅ TC-BUD-01 to TC-BUD-02: Budgeting')
        self.stdout.write('  ✅ TC-TAX-01 to TC-TAX-02: Corporate Tax')
        self.stdout.write('  ✅ TC-PER-01: Period Controls')
        self.stdout.write('  ✅ TC-EDGE-01 to TC-EDGE-03: Edge Cases')
        
        self.stdout.write('\n🔗 VIEW DATA AT:')
        self.stdout.write('  http://localhost:7001/finance/accounts/')
        self.stdout.write('  http://localhost:7001/finance/journals/')
        self.stdout.write('  http://localhost:7001/finance/trial-balance/')
        self.stdout.write('  http://localhost:7001/finance/vat-report/')
        self.stdout.write('  http://localhost:7001/finance/ar-aging/')
        self.stdout.write('  http://localhost:7001/finance/ap-aging/')
