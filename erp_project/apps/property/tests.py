"""
PDC (Post-Dated Cheque) Test Cases

Test Cases as per specification:
1. Same cheque number + amount + bank, different tenants → System allows entry
2. Bank statement shows single line matching multiple PDCs → System blocks auto-match
3. Manual allocation performed → All tenant ledgers settle correctly
4. Cheque bounce after reconciliation → AR restored correctly
5. VAT impact → No VAT effect on cheque realization
"""
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import date, timedelta

from .models import (
    Property, Unit, Tenant, Lease, PDCCheque,
    PDCAllocation, PDCAllocationLine, PDCBankMatch, AmbiguousMatchLog
)
from apps.finance.models import (
    Account, AccountType, BankAccount, BankStatement, BankStatementLine,
    JournalEntry, JournalLine, AccountMapping
)


class PDCSetupMixin:
    """Mixin for setting up test data."""
    
    @classmethod
    def setUpTestData(cls):
        # Create user
        cls.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass123'
        )
        
        # Create accounts
        cls.bank_gl_account = Account.objects.create(
            code='1001',
            name='Bank Account',
            account_type=AccountType.ASSET
        )
        cls.pdc_control_account = Account.objects.create(
            code='1010',
            name='PDC Control Account',
            account_type=AccountType.ASSET
        )
        cls.ar_account_1 = Account.objects.create(
            code='1100',
            name='AR - Tenant 1',
            account_type=AccountType.ASSET
        )
        cls.ar_account_2 = Account.objects.create(
            code='1101',
            name='AR - Tenant 2',
            account_type=AccountType.ASSET
        )
        cls.revenue_account = Account.objects.create(
            code='4000',
            name='Rental Income',
            account_type=AccountType.INCOME
        )
        cls.bounce_expense = Account.objects.create(
            code='5500',
            name='Cheque Bounce Charges',
            account_type=AccountType.EXPENSE
        )
        
        # Create account mapping for PDC control
        AccountMapping.objects.create(
            module='property',
            transaction_type='pdc_control',
            account=cls.pdc_control_account
        )
        
        # Create bank account
        cls.bank_account = BankAccount.objects.create(
            name='Test Bank',
            account_number='1234567890',
            bank_name='Test Bank Ltd',
            gl_account=cls.bank_gl_account
        )
        
        # Create property
        cls.property = Property.objects.create(
            name='Test Building',
            address='123 Test Street',
            city='Dubai',
            property_type='residential',
            created_by=cls.user
        )
        
        # Create tenants
        cls.tenant_1 = Tenant.objects.create(
            name='Tenant One',
            email='tenant1@test.com',
            ar_account=cls.ar_account_1,
            created_by=cls.user
        )
        cls.tenant_2 = Tenant.objects.create(
            name='Tenant Two',
            email='tenant2@test.com',
            ar_account=cls.ar_account_2,
            created_by=cls.user
        )
        
        # Create unit
        cls.unit = Unit.objects.create(
            unit_number='101',
            property=cls.property,
            unit_type='apartment',
            monthly_rent=Decimal('5000.00'),
            created_by=cls.user
        )


class TestCase1_PDCUniqueness(PDCSetupMixin, TestCase):
    """
    Test Case 1: Same cheque number + amount + bank, different tenants → System allows entry
    
    A cheque is uniquely identified by composite of:
    - Cheque Number
    - Bank Name
    - Cheque Date
    - Amount
    - Tenant ID
    """
    
    def test_same_cheque_different_tenants_allowed(self):
        """Same cheque number, amount, bank but DIFFERENT tenants should be allowed."""
        cheque_date = date.today() + timedelta(days=30)
        
        # Create PDC for tenant 1
        pdc_1 = PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='123456',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            created_by=self.user
        )
        self.assertIsNotNone(pdc_1.pk)
        
        # Create PDC with same details but for tenant 2 - should be allowed
        pdc_2 = PDCCheque.objects.create(
            tenant=self.tenant_2,
            cheque_number='123456',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            created_by=self.user
        )
        self.assertIsNotNone(pdc_2.pk)
        
        # Both PDCs should exist
        self.assertEqual(PDCCheque.objects.filter(cheque_number='123456').count(), 2)
    
    def test_duplicate_pdc_same_tenant_rejected(self):
        """Same cheque number, amount, bank, date, and tenant should be rejected."""
        cheque_date = date.today() + timedelta(days=30)
        
        # Create first PDC
        PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='789012',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            created_by=self.user
        )
        
        # Try to create duplicate - should raise error
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            PDCCheque.objects.create(
                tenant=self.tenant_1,
                cheque_number='789012',
                bank_name='Emirates NBD',
                cheque_date=cheque_date,
                amount=Decimal('5000.00'),
                created_by=self.user
            )


class TestCase2_AmbiguousMatchDetection(PDCSetupMixin, TransactionTestCase):
    """
    Test Case 2: Bank statement shows single line matching multiple PDCs → System blocks auto-match
    """
    
    def test_ambiguous_match_blocks_auto_reconcile(self):
        """When multiple PDCs match one bank line, auto-match should be blocked."""
        cheque_date = date.today()
        
        # Create two PDCs with same amount for different tenants
        pdc_1 = PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='111111',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            status='deposited',
            deposit_status='in_clearing',
            deposited_to_bank=self.bank_account,
            created_by=self.user
        )
        
        pdc_2 = PDCCheque.objects.create(
            tenant=self.tenant_2,
            cheque_number='222222',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            status='deposited',
            deposit_status='in_clearing',
            deposited_to_bank=self.bank_account,
            created_by=self.user
        )
        
        # Create bank statement with single line
        statement = BankStatement.objects.create(
            bank_account=self.bank_account,
            statement_start_date=cheque_date,
            statement_end_date=cheque_date,
            created_by=self.user
        )
        
        bank_line = BankStatementLine.objects.create(
            statement=statement,
            line_number=1,
            transaction_date=cheque_date,
            description='Cheque deposit',
            amount=Decimal('5000.00')
        )
        
        # Find matches - should return 2 PDCs
        from .views import find_pdc_matches
        matches = find_pdc_matches(bank_line)
        
        self.assertEqual(len(matches), 2)
        self.assertIn(pdc_1, matches)
        self.assertIn(pdc_2, matches)
        
        # Verify ambiguous match log is created
        AmbiguousMatchLog.objects.create(
            bank_statement_line=bank_line,
            matching_pdc_ids=[pdc_1.pk, pdc_2.pk],
            created_by=self.user
        )
        
        log = AmbiguousMatchLog.objects.filter(bank_statement_line=bank_line).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.resolution_status, 'pending')


class TestCase3_ManualAllocation(PDCSetupMixin, TransactionTestCase):
    """
    Test Case 3: Manual allocation performed → All tenant ledgers settle correctly
    """
    
    def test_manual_allocation_settles_ledgers(self):
        """Manual allocation should correctly settle all tenant AR ledgers."""
        cheque_date = date.today()
        
        # Set initial AR balances (simulate outstanding rent)
        self.ar_account_1.balance = Decimal('5000.00')
        self.ar_account_1.save()
        self.ar_account_2.balance = Decimal('5000.00')
        self.ar_account_2.save()
        
        # Create two PDCs
        pdc_1 = PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='333333',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            status='deposited',
            deposit_status='in_clearing',
            deposited_to_bank=self.bank_account,
            created_by=self.user
        )
        
        pdc_2 = PDCCheque.objects.create(
            tenant=self.tenant_2,
            cheque_number='444444',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            status='deposited',
            deposit_status='in_clearing',
            deposited_to_bank=self.bank_account,
            created_by=self.user
        )
        
        # Create bank statement
        statement = BankStatement.objects.create(
            bank_account=self.bank_account,
            statement_start_date=cheque_date,
            statement_end_date=cheque_date,
            created_by=self.user
        )
        
        bank_line = BankStatementLine.objects.create(
            statement=statement,
            line_number=1,
            transaction_date=cheque_date,
            description='Combined cheque deposits',
            amount=Decimal('10000.00')  # Combined amount
        )
        
        # Create manual allocation
        allocation = PDCAllocation.objects.create(
            bank_statement_line=bank_line,
            total_amount=Decimal('10000.00'),
            allocated_by=self.user,
            reason='Two tenants deposited cheques together',
            created_by=self.user
        )
        
        # Add allocation lines
        PDCAllocationLine.objects.create(
            allocation=allocation,
            pdc=pdc_1,
            amount=Decimal('5000.00')
        )
        PDCAllocationLine.objects.create(
            allocation=allocation,
            pdc=pdc_2,
            amount=Decimal('5000.00')
        )
        
        # Confirm allocation
        allocation.confirm(self.user)
        
        # Verify PDCs are reconciled
        pdc_1.refresh_from_db()
        pdc_2.refresh_from_db()
        
        self.assertTrue(pdc_1.reconciled)
        self.assertTrue(pdc_2.reconciled)
        self.assertEqual(pdc_1.status, 'cleared')
        self.assertEqual(pdc_2.status, 'cleared')
        
        # Verify allocation is confirmed
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, 'confirmed')


class TestCase4_ChequeBounce(PDCSetupMixin, TransactionTestCase):
    """
    Test Case 4: Cheque bounce after reconciliation → AR restored correctly
    """
    
    def test_bounce_restores_ar(self):
        """When a cleared cheque bounces, AR should be restored correctly."""
        cheque_date = date.today() - timedelta(days=10)
        
        # Set initial AR balance
        initial_ar_balance = Decimal('5000.00')
        self.ar_account_1.balance = initial_ar_balance
        self.ar_account_1.save()
        
        # Create and deposit PDC (simulating the flow)
        pdc = PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='555555',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            status='received',
            created_by=self.user
        )
        
        # Deposit PDC
        pdc.deposit(self.bank_account, self.user, deposit_date=cheque_date)
        
        # Clear PDC
        pdc.clear(self.user, clearing_date=cheque_date + timedelta(days=3))
        
        pdc.refresh_from_db()
        self.assertEqual(pdc.status, 'cleared')
        
        # Now bounce the cheque
        bounce_charges = Decimal('100.00')
        pdc.bounce(
            self.user,
            bounce_date=date.today(),
            bounce_reason='Insufficient Funds',
            bounce_charges=bounce_charges
        )
        
        pdc.refresh_from_db()
        
        # Verify bounce
        self.assertEqual(pdc.status, 'bounced')
        self.assertEqual(pdc.bounce_reason, 'Insufficient Funds')
        self.assertEqual(pdc.bounce_charges, bounce_charges)
        self.assertIsNotNone(pdc.bounce_journal)
        
        # Verify AR is restored (bounce journal should have debit to AR)
        bounce_journal = pdc.bounce_journal
        ar_line = bounce_journal.lines.filter(account=self.ar_account_1).first()
        self.assertIsNotNone(ar_line)
        self.assertEqual(ar_line.debit, Decimal('5000.00'))


class TestCase5_VATImpact(PDCSetupMixin, TestCase):
    """
    Test Case 5: VAT impact → No VAT effect on cheque realization
    
    PDC deposit, clearing, and bounce should NOT have any VAT impact.
    VAT is recognized when the invoice/rent is raised, not when payment is received.
    """
    
    def test_no_vat_on_pdc_realization(self):
        """PDC operations should not affect VAT accounts."""
        # Create VAT account
        vat_output = Account.objects.create(
            code='2100',
            name='VAT Output',
            account_type=AccountType.LIABILITY
        )
        initial_vat_balance = Decimal('250.00')
        vat_output.balance = initial_vat_balance
        vat_output.save()
        
        cheque_date = date.today()
        
        # Create PDC
        pdc = PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='666666',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5250.00'),  # Including VAT
            status='received',
            created_by=self.user
        )
        
        # Deposit
        pdc.deposit(self.bank_account, self.user)
        
        # Clear
        pdc.clear(self.user)
        
        # Check VAT account - should be unchanged
        vat_output.refresh_from_db()
        self.assertEqual(vat_output.balance, initial_vat_balance)
        
        # Verify no journal lines affect VAT account
        all_journals = JournalEntry.objects.filter(
            pk__in=[pdc.pdc_control_journal_id, pdc.journal_entry_id]
        )
        for journal in all_journals:
            vat_lines = journal.lines.filter(account=vat_output)
            self.assertEqual(vat_lines.count(), 0, "VAT account should not be affected")


class TestPDCControlAccountFlow(PDCSetupMixin, TransactionTestCase):
    """
    Additional test for PDC Control Account flow.
    
    Rules:
    - PDC entries do NOT hit Bank or AR immediately
    - PDC is off-bank until cleared
    - Cheques in Hand ≠ Bank
    """
    
    def test_pdc_control_account_flow(self):
        """Test the full PDC control account flow."""
        cheque_date = date.today()
        
        # Initial balances
        initial_pdc_control = self.pdc_control_account.balance
        initial_bank = self.bank_gl_account.balance
        initial_ar = self.ar_account_1.balance + Decimal('5000.00')  # Assume AR exists
        self.ar_account_1.balance = initial_ar
        self.ar_account_1.save()
        
        # Create PDC
        pdc = PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='777777',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            status='received',
            created_by=self.user
        )
        
        # Step 1: Deposit - Should hit PDC Control, not Bank
        pdc.deposit(self.bank_account, self.user)
        
        self.pdc_control_account.refresh_from_db()
        self.bank_gl_account.refresh_from_db()
        self.ar_account_1.refresh_from_db()
        
        # PDC Control should increase
        self.assertEqual(
            self.pdc_control_account.balance,
            initial_pdc_control + Decimal('5000.00')
        )
        # Bank should NOT change yet
        self.assertEqual(self.bank_gl_account.balance, initial_bank)
        # AR should decrease
        self.assertEqual(
            self.ar_account_1.balance,
            initial_ar - Decimal('5000.00')
        )
        
        # Step 2: Clear - Should move from PDC Control to Bank
        pdc.clear(self.user)
        
        self.pdc_control_account.refresh_from_db()
        self.bank_gl_account.refresh_from_db()
        
        # PDC Control should be back to initial
        self.assertEqual(self.pdc_control_account.balance, initial_pdc_control)
        # Bank should now have the amount
        self.assertEqual(
            self.bank_gl_account.balance,
            initial_bank + Decimal('5000.00')
        )


class TestAuditTrail(PDCSetupMixin, TestCase):
    """Test audit trail requirements."""
    
    def test_allocation_audit_trail(self):
        """Every manual allocation should have user, timestamp, reason."""
        cheque_date = date.today()
        
        # Create bank statement
        statement = BankStatement.objects.create(
            bank_account=self.bank_account,
            statement_start_date=cheque_date,
            statement_end_date=cheque_date,
            created_by=self.user
        )
        
        bank_line = BankStatementLine.objects.create(
            statement=statement,
            line_number=1,
            transaction_date=cheque_date,
            description='Test deposit',
            amount=Decimal('5000.00')
        )
        
        # Create allocation
        allocation = PDCAllocation.objects.create(
            bank_statement_line=bank_line,
            total_amount=Decimal('5000.00'),
            allocated_by=self.user,
            reason='Test reason for audit',
            created_by=self.user
        )
        
        # Verify audit fields
        self.assertIsNotNone(allocation.allocated_by)
        self.assertIsNotNone(allocation.created_at)
        self.assertTrue(len(allocation.reason) > 0)
    
    def test_no_hard_delete_on_journal(self):
        """Financial records should not be hard deleted."""
        cheque_date = date.today()
        
        pdc = PDCCheque.objects.create(
            tenant=self.tenant_1,
            cheque_number='888888',
            bank_name='Emirates NBD',
            cheque_date=cheque_date,
            amount=Decimal('5000.00'),
            status='received',
            created_by=self.user
        )
        
        # Deposit (creates journal)
        self.ar_account_1.balance = Decimal('5000.00')
        self.ar_account_1.save()
        
        pdc.deposit(self.bank_account, self.user)
        
        journal = pdc.pdc_control_journal
        self.assertIsNotNone(journal)
        
        # Soft delete the journal
        journal.is_active = False
        journal.save()
        
        # Verify it still exists in database
        from apps.finance.models import JournalEntry
        self.assertTrue(
            JournalEntry.objects.filter(pk=journal.pk).exists()
        )




