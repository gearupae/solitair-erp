"""
Advances — Customer Advance, Vendor Advance, Security Cheque Outward

All models post journal entries using existing JournalEntry + JournalEntryLine
and AccountMapping exactly as other modules do.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel
from apps.core.utils import generate_number


# ---------------------------------------------------------------------------
# MODULE 1 — Customer Advance
# ---------------------------------------------------------------------------

class CustomerAdvance(BaseModel):
    """
    Advance received from a customer before invoicing.

    On POST:
        Dr Bank                   (total_amount)
        Cr VAT Payable            (vat_amount)
        Cr Customer Advance 2300  (amount)

    On Apply to Invoice:
        Dr Customer Advance 2300  (amount_applied)
        Cr Accounts Receivable    (amount_applied)
    """

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ]

    advance_number = models.CharField(max_length=60, unique=True, editable=False)
    customer = models.ForeignKey(
        'crm.Customer',
        on_delete=models.PROTECT,
        related_name='customer_advances',
    )
    date = models.DateField()
    reference = models.CharField(max_length=200, blank=True)
    bank_account = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.PROTECT,
        related_name='customer_advances',
    )

    # Amounts
    amount = models.DecimalField(max_digits=15, decimal_places=2, help_text='Amount excluding VAT')
    vat_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal('0.00'),
        help_text='VAT 5% — auto-calculated but editable',
    )
    total_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal('0.00'),
        help_text='amount + vat_amount (calculated)',
    )
    applied_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal('0.00'),
        help_text='Total applied to invoices so far',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)

    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='customer_advance_receipts',
    )

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Customer Advance'
        verbose_name_plural = 'Customer Advances'

    def __str__(self):
        return f'{self.advance_number} — {self.customer.name}'

    @property
    def balance(self):
        """Unapplied amount (on Customer Advance account 2300)."""
        return (self.amount - self.applied_amount).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        if not self.advance_number:
            self.advance_number = generate_number('CUSTOMER_ADVANCE', CustomerAdvance, 'advance_number')
        self.total_amount = (self.amount + self.vat_amount).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)

    def post_to_accounting(self, user=None):
        """
        Post receipt journal:
            Dr Bank               → total_amount
            Cr VAT Payable        → vat_amount
            Cr Customer Advance   → amount  (2300)
        """
        from apps.finance.models import (
            JournalEntry, JournalEntryLine, AccountMapping, FiscalYear,
        )

        if self.status != 'draft':
            raise ValidationError('Only draft advances can be posted.')
        if self.total_amount <= 0:
            raise ValidationError('Amount must be greater than zero.')
        if not self.bank_account.gl_account:
            raise ValidationError('Bank account has no linked GL account. Configure in Finance → Bank Accounts.')

        FiscalYear.validate_posting_allowed(self.date)

        bank_gl = self.bank_account.gl_account
        adv_account = AccountMapping.get_account_or_default('customer_advance_liability', '2300')
        vat_account = AccountMapping.get_account_or_default('sales_invoice_vat', '2100')

        if not adv_account:
            raise ValidationError(
                'Customer Advance (2300) account not found. '
                'Please seed it via management command or Finance → Chart of Accounts.'
            )

        journal = JournalEntry.objects.create(
            date=self.date,
            reference=self.advance_number,
            description=f'Customer Advance Receipt: {self.advance_number} — {self.customer.name}',
            entry_type='standard',
            source_module='sales',
            source_id=self.pk,
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_gl,
            description=f'Advance from {self.customer.name}',
            debit=self.total_amount,
            credit=Decimal('0.00'),
        )
        if self.vat_amount > 0 and vat_account:
            JournalEntryLine.objects.create(
                journal_entry=journal,
                account=vat_account,
                description=f'Output VAT — {self.advance_number}',
                debit=Decimal('0.00'),
                credit=self.vat_amount,
            )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=adv_account,
            description=f'Customer Advance — {self.customer.name}',
            debit=Decimal('0.00'),
            credit=self.amount,
        )

        journal.calculate_totals()
        journal.post(user)

        self.journal_entry = journal
        self.status = 'posted'
        self.save(update_fields=['journal_entry', 'status'])
        return journal


class CustomerAdvanceApplication(BaseModel):
    """
    Application of a customer advance against a posted invoice.

    Journal:
        Dr Customer Advance 2300  → amount_applied
        Cr Accounts Receivable    → amount_applied
    """
    advance = models.ForeignKey(
        CustomerAdvance,
        on_delete=models.PROTECT,
        related_name='applications',
    )
    invoice = models.ForeignKey(
        'sales.Invoice',
        on_delete=models.PROTECT,
        related_name='advance_applications',
    )
    date = models.DateField()
    amount_applied = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.TextField(blank=True)
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='customer_advance_applications',
    )

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Customer Advance Application'

    def __str__(self):
        return f'{self.advance.advance_number} → {self.invoice.invoice_number}'

    def apply(self, user=None):
        from apps.finance.models import (
            JournalEntry, JournalEntryLine, AccountMapping, FiscalYear,
        )

        if self.advance.status != 'posted':
            raise ValidationError('Advance must be posted before applying.')
        if self.invoice.status not in ('posted', 'sent', 'partial', 'overdue'):
            raise ValidationError('Invoice must be posted before applying advance.')
        if self.amount_applied <= 0:
            raise ValidationError('Amount to apply must be greater than zero.')
        if self.amount_applied > self.advance.balance:
            raise ValidationError(
                f'Amount exceeds advance balance (AED {self.advance.balance:,.2f}).'
            )

        inv_balance = self.invoice.total_amount - self.invoice.paid_amount
        if self.amount_applied > inv_balance:
            raise ValidationError(
                f'Amount exceeds invoice balance due (AED {inv_balance:,.2f}).'
            )

        FiscalYear.validate_posting_allowed(self.date)

        adv_account = AccountMapping.get_account_or_default('customer_advance_liability', '2300')
        ar_account = AccountMapping.get_account_or_default('sales_invoice_receivable', '1200')

        if not adv_account:
            raise ValidationError('Customer Advance (2300) account not configured.')
        if not ar_account:
            raise ValidationError('Accounts Receivable (1200) account not configured.')

        journal = JournalEntry.objects.create(
            date=self.date,
            reference=f'CA-APP-{self.advance.advance_number}',
            description=(
                f'Advance Application: {self.advance.advance_number} → '
                f'{self.invoice.invoice_number} — {self.advance.customer.name}'
            ),
            entry_type='standard',
            source_module='sales',
            source_id=self.advance.pk,
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=adv_account,
            description=f'Apply advance {self.advance.advance_number}',
            debit=self.amount_applied,
            credit=Decimal('0.00'),
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ar_account,
            description=f'AR clearing — {self.invoice.invoice_number}',
            debit=Decimal('0.00'),
            credit=self.amount_applied,
        )

        journal.calculate_totals()
        journal.post(user)

        self.journal_entry = journal
        self.save(update_fields=['journal_entry'])

        # Update advance applied amount
        self.advance.applied_amount += self.amount_applied
        self.advance.save(update_fields=['applied_amount'])

        # Update invoice paid amount
        self.invoice.paid_amount += self.amount_applied
        if self.invoice.paid_amount >= self.invoice.total_amount:
            self.invoice.status = 'paid'
        else:
            self.invoice.status = 'partial'
        self.invoice.save(update_fields=['paid_amount', 'status'])

        return journal


# ---------------------------------------------------------------------------
# MODULE 2 — Vendor Advance
# ---------------------------------------------------------------------------

class VendorAdvance(BaseModel):
    """
    Advance paid to a vendor before goods/services are billed.

    On POST:
        Dr Advance to Vendor 1300  → amount
        Cr Bank                    → amount
        (NO VAT)

    On Apply to Bill:
        Dr Accounts Payable 2000   → amount_applied
        Cr Advance to Vendor 1300  → amount_applied
    """

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ]

    advance_number = models.CharField(max_length=60, unique=True, editable=False)
    vendor = models.ForeignKey(
        'purchase.Vendor',
        on_delete=models.PROTECT,
        related_name='vendor_advances',
    )
    date = models.DateField()
    reference = models.CharField(max_length=200, blank=True)
    bank_account = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.PROTECT,
        related_name='vendor_advances',
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    applied_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal('0.00'),
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)

    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='vendor_advance_payments',
    )

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Vendor Advance'
        verbose_name_plural = 'Vendor Advances'

    def __str__(self):
        return f'{self.advance_number} — {self.vendor.name}'

    @property
    def balance(self):
        return (self.amount - self.applied_amount).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        if not self.advance_number:
            self.advance_number = generate_number('VENDOR_ADVANCE', VendorAdvance, 'advance_number')
        super().save(*args, **kwargs)

    def post_to_accounting(self, user=None):
        """
        Dr Advance to Vendor 1300  → amount
        Cr Bank                    → amount
        """
        from apps.finance.models import (
            JournalEntry, JournalEntryLine, AccountMapping, FiscalYear,
        )

        if self.status != 'draft':
            raise ValidationError('Only draft advances can be posted.')
        if self.amount <= 0:
            raise ValidationError('Amount must be greater than zero.')
        if not self.bank_account.gl_account:
            raise ValidationError('Bank account has no linked GL account.')

        FiscalYear.validate_posting_allowed(self.date)

        bank_gl = self.bank_account.gl_account
        adv_account = AccountMapping.get_account_or_default('vendor_advance_asset', '1310')

        if not adv_account:
            raise ValidationError(
                'Advance to Vendor (1310) account not found. '
                'Run: python manage.py seed_advance_accounts && seed_advance_mappings'
            )

        journal = JournalEntry.objects.create(
            date=self.date,
            reference=self.advance_number,
            description=f'Vendor Advance Payment: {self.advance_number} — {self.vendor.name}',
            entry_type='standard',
            source_module='purchase',
            source_id=self.pk,
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=adv_account,
            description=f'Advance to {self.vendor.name}',
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_gl,
            description=f'Payment for advance {self.advance_number}',
            debit=Decimal('0.00'),
            credit=self.amount,
        )

        journal.calculate_totals()
        journal.post(user)

        self.journal_entry = journal
        self.status = 'posted'
        self.save(update_fields=['journal_entry', 'status'])
        return journal


class VendorAdvanceApplication(BaseModel):
    """
    Application of vendor advance against a posted vendor bill.

    Journal:
        Dr Accounts Payable 2000   → amount_applied
        Cr Advance to Vendor 1300  → amount_applied
    """
    advance = models.ForeignKey(
        VendorAdvance,
        on_delete=models.PROTECT,
        related_name='applications',
    )
    bill = models.ForeignKey(
        'purchase.VendorBill',
        on_delete=models.PROTECT,
        related_name='advance_applications',
    )
    date = models.DateField()
    amount_applied = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.TextField(blank=True)
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='vendor_advance_applications',
    )

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Vendor Advance Application'

    def __str__(self):
        return f'{self.advance.advance_number} → {self.bill.bill_number}'

    def apply(self, user=None):
        from apps.finance.models import (
            JournalEntry, JournalEntryLine, AccountMapping, FiscalYear,
        )

        if self.advance.status != 'posted':
            raise ValidationError('Advance must be posted before applying.')
        if self.bill.status not in ('posted', 'pending', 'partial', 'overdue'):
            raise ValidationError('Bill must be posted before applying advance.')
        if self.amount_applied <= 0:
            raise ValidationError('Amount to apply must be greater than zero.')
        if self.amount_applied > self.advance.balance:
            raise ValidationError(
                f'Amount exceeds advance balance (AED {self.advance.balance:,.2f}).'
            )

        bill_balance = self.bill.total_amount - self.bill.paid_amount
        if self.amount_applied > bill_balance:
            raise ValidationError(
                f'Amount exceeds bill balance due (AED {bill_balance:,.2f}).'
            )

        FiscalYear.validate_posting_allowed(self.date)

        ap_account = AccountMapping.get_account_or_default('vendor_bill_payable', '2000')
        adv_account = AccountMapping.get_account_or_default('vendor_advance_asset', '1310')

        if not ap_account:
            raise ValidationError('Accounts Payable (2000) account not configured.')
        if not adv_account:
            raise ValidationError('Advance to Vendor (1310) account not configured.')

        journal = JournalEntry.objects.create(
            date=self.date,
            reference=f'VA-APP-{self.advance.advance_number}',
            description=(
                f'Vendor Advance Application: {self.advance.advance_number} → '
                f'{self.bill.bill_number} — {self.advance.vendor.name}'
            ),
            entry_type='standard',
            source_module='purchase',
            source_id=self.advance.pk,
        )

        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=ap_account,
            description=f'AP clearing — {self.bill.bill_number}',
            debit=self.amount_applied,
            credit=Decimal('0.00'),
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=adv_account,
            description=f'Apply vendor advance {self.advance.advance_number}',
            debit=Decimal('0.00'),
            credit=self.amount_applied,
        )

        journal.calculate_totals()
        journal.post(user)

        self.journal_entry = journal
        self.save(update_fields=['journal_entry'])

        self.advance.applied_amount += self.amount_applied
        self.advance.save(update_fields=['applied_amount'])

        self.bill.paid_amount += self.amount_applied
        if self.bill.paid_amount >= self.bill.total_amount:
            self.bill.status = 'paid'
        else:
            self.bill.status = 'partial'
        self.bill.save(update_fields=['paid_amount', 'status'])

        return journal


# ---------------------------------------------------------------------------
# MODULE 3 — Security Cheque Outward
# ---------------------------------------------------------------------------

class SecurityChequeOutward(BaseModel):
    """
    Security cheque issued by the company to a vendor/party.

    On ISSUE:
        Dr Vendor Security Deposit 1360  → amount
        Cr Security Cheques Payable 2360 → amount

    On ENCASH (forfeiture / settlement):
        Dr Security Cheques Payable 2360 → amount
        Cr Bank                          → amount

    On RETURN (cheque returned to us):
        Dr Security Cheques Payable 2360 → amount
        Cr Vendor Security Deposit 1360  → amount
    """

    STATUS_CHOICES = [
        ('issued', 'Issued'),
        ('encashed', 'Encashed'),
        ('returned', 'Returned'),
    ]

    cheque_number = models.CharField(max_length=100)
    party_name = models.CharField(max_length=200)
    bank_name = models.CharField(max_length=200)
    cheque_date = models.DateField()
    issued_date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    purpose = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='issued')

    # Journal entries per event
    issue_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='security_cheque_issues',
    )
    encash_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='security_cheque_encashes',
    )
    return_journal = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='security_cheque_returns',
    )
    # Bank account used for encashment
    encash_bank_account = models.ForeignKey(
        'finance.BankAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='security_cheque_encashes',
    )
    encash_date = models.DateField(null=True, blank=True)
    return_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_date', '-created_at']
        verbose_name = 'Security Cheque Outward'
        verbose_name_plural = 'Security Cheques Outward'

    def __str__(self):
        return f'{self.cheque_number} — {self.party_name} (AED {self.amount})'

    def post_issue_journal(self, user=None):
        """
        Post issue journal:
            Dr Vendor Security Deposit 1360  → amount
            Cr Security Cheques Payable 2360 → amount
        """
        from apps.finance.models import (
            JournalEntry, JournalEntryLine, AccountMapping, FiscalYear,
        )

        if self.issue_journal_id:
            raise ValidationError('Issue journal already exists for this cheque.')
        if self.amount <= 0:
            raise ValidationError('Cheque amount must be greater than zero.')

        FiscalYear.validate_posting_allowed(self.issued_date)

        deposit_account = AccountMapping.get_account_or_default('vendor_security_deposit', '1360')
        payable_account = AccountMapping.get_account_or_default('security_cheques_payable', '2360')

        if not deposit_account:
            raise ValidationError('Vendor Security Deposit (1360) account not found.')
        if not payable_account:
            raise ValidationError('Security Cheques Payable (2360) account not found.')

        journal = JournalEntry.objects.create(
            date=self.issued_date,
            reference=self.cheque_number,
            description=f'Security Cheque Issued: {self.cheque_number} — {self.party_name}',
            entry_type='standard',
            source_module='manual',
            source_id=self.pk,
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=deposit_account,
            description=f'Security deposit — {self.party_name}',
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=payable_account,
            description=f'Security cheque payable — {self.cheque_number}',
            debit=Decimal('0.00'),
            credit=self.amount,
        )
        journal.calculate_totals()
        journal.post(user)

        self.issue_journal = journal
        self.save(update_fields=['issue_journal'])
        return journal

    def post_encash_journal(self, bank_account, encash_date, user=None):
        """
        Dr Security Cheques Payable 2360 → amount
        Cr Bank                          → amount
        """
        from apps.finance.models import (
            JournalEntry, JournalEntryLine, AccountMapping, FiscalYear,
        )

        if self.status != 'issued':
            raise ValidationError('Only issued cheques can be encashed.')
        if self.encash_journal_id:
            raise ValidationError('Encash journal already posted.')
        if not bank_account.gl_account:
            raise ValidationError('Bank account has no linked GL account.')

        FiscalYear.validate_posting_allowed(encash_date)

        payable_account = AccountMapping.get_account_or_default('security_cheques_payable', '2360')
        if not payable_account:
            raise ValidationError('Security Cheques Payable (2360) account not found.')

        journal = JournalEntry.objects.create(
            date=encash_date,
            reference=f'ENC-{self.cheque_number}',
            description=f'Security Cheque Encashed: {self.cheque_number} — {self.party_name}',
            entry_type='standard',
            source_module='manual',
            source_id=self.pk,
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=payable_account,
            description=f'Security cheque cleared — {self.cheque_number}',
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=bank_account.gl_account,
            description=f'Encash payment — {self.party_name}',
            debit=Decimal('0.00'),
            credit=self.amount,
        )
        journal.calculate_totals()
        journal.post(user)

        self.encash_journal = journal
        self.encash_bank_account = bank_account
        self.encash_date = encash_date
        self.status = 'encashed'
        self.save(update_fields=['encash_journal', 'encash_bank_account', 'encash_date', 'status'])
        return journal

    def post_return_journal(self, return_date, user=None):
        """
        Dr Security Cheques Payable 2360 → amount
        Cr Vendor Security Deposit 1360  → amount
        """
        from apps.finance.models import (
            JournalEntry, JournalEntryLine, AccountMapping, FiscalYear,
        )

        if self.status != 'issued':
            raise ValidationError('Only issued cheques can be returned.')
        if self.return_journal_id:
            raise ValidationError('Return journal already posted.')

        FiscalYear.validate_posting_allowed(return_date)

        deposit_account = AccountMapping.get_account_or_default('vendor_security_deposit', '1360')
        payable_account = AccountMapping.get_account_or_default('security_cheques_payable', '2360')

        if not deposit_account:
            raise ValidationError('Vendor Security Deposit (1360) account not found.')
        if not payable_account:
            raise ValidationError('Security Cheques Payable (2360) account not found.')

        journal = JournalEntry.objects.create(
            date=return_date,
            reference=f'RET-{self.cheque_number}',
            description=f'Security Cheque Returned: {self.cheque_number} — {self.party_name}',
            entry_type='standard',
            source_module='manual',
            source_id=self.pk,
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=payable_account,
            description=f'Cheque returned — {self.cheque_number}',
            debit=self.amount,
            credit=Decimal('0.00'),
        )
        JournalEntryLine.objects.create(
            journal_entry=journal,
            account=deposit_account,
            description=f'Reverse deposit — {self.party_name}',
            debit=Decimal('0.00'),
            credit=self.amount,
        )
        journal.calculate_totals()
        journal.post(user)

        self.return_journal = journal
        self.return_date = return_date
        self.status = 'returned'
        self.save(update_fields=['return_journal', 'return_date', 'status'])
        return journal
