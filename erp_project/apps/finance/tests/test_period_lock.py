"""
Period Lock & Superuser Bypass Tests.

Enterprise control matrix:
- Superuser + allow_posting_to_closed_period=False → Cannot bypass
- Superuser + allow_posting_to_closed_period=True  → Can bypass
- Normal user + allow_posting_to_closed_period=False → Cannot bypass
- Normal user + allow_posting_to_closed_period=True  → Cannot bypass (superuser required)

Run: python manage.py test apps.finance.tests.test_period_lock -v 2
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import date

from apps.finance.models import (
    FiscalYear, AccountingPeriod, Account, AccountType,
    JournalEntry, JournalEntryLine, AccountingSettings
)
from apps.settings_app.models import AuditLog


class PeriodLockTestCase(TestCase):
    """Base setup for period lock tests."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='superuser',
            email='super@example.com',
            password='testpass123'
        )
        cls.normal_user = User.objects.create_user(
            username='normaluser',
            email='normal@example.com',
            password='testpass123',
            is_staff=True,
        )

        # Closed fiscal year + locked period
        cls.closed_fy = FiscalYear.objects.create(
            name='FY 2024',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            is_closed=True,
        )
        cls.locked_period = AccountingPeriod.objects.create(
            fiscal_year=cls.closed_fy,
            name='January 2024',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            is_locked=True,
        )

        # Leaf accounts for balanced journal
        cls.debit_acc = Account.objects.create(
            code='1101', name='AR Test', account_type=AccountType.ASSET
        )
        cls.credit_acc = Account.objects.create(
            code='4101', name='Income Test', account_type=AccountType.INCOME
        )

    def _create_draft_entry(self):
        """Create a balanced draft journal in closed period."""
        entry = JournalEntry.objects.create(
            date=date(2024, 1, 15),
            reference='TEST-001',
            description='Test entry',
            fiscal_year=self.closed_fy,
            period=self.locked_period,
        )
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=self.debit_acc,
            debit=Decimal('100.00'),
            credit=Decimal('0.00'),
        )
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=self.credit_acc,
            debit=Decimal('0.00'),
            credit=Decimal('100.00'),
        )
        return entry


class PeriodLockSuperuserFalse(PeriodLockTestCase):
    """Superuser + allow_posting_to_closed_period=False → Cannot bypass."""

    def setUp(self):
        settings = AccountingSettings.get_settings()
        settings.allow_posting_to_closed_period = False
        settings.save()

    def test_validate_for_posting_returns_errors(self):
        entry = self._create_draft_entry()
        errors = entry.validate_for_posting(user=self.superuser)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any('closed' in e.lower() or 'locked' in e.lower() for e in errors))

    def test_post_raises_validation_error(self):
        entry = self._create_draft_entry()
        with self.assertRaises(ValidationError):
            entry.post(user=self.superuser)


class PeriodLockSuperuserTrue(PeriodLockTestCase):
    """Superuser + allow_posting_to_closed_period=True → Can bypass."""

    def setUp(self):
        settings = AccountingSettings.get_settings()
        settings.allow_posting_to_closed_period = True
        settings.save()

    def test_validate_for_posting_passes(self):
        entry = self._create_draft_entry()
        errors = entry.validate_for_posting(user=self.superuser)
        self.assertEqual(errors, [])

    def test_post_succeeds(self):
        entry = self._create_draft_entry()
        entry.post(user=self.superuser)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'posted')

    def test_bypass_creates_audit_log(self):
        entry = self._create_draft_entry()
        initial_count = AuditLog.objects.filter(action='post_bypass').count()
        entry.post(user=self.superuser)
        self.assertEqual(
            AuditLog.objects.filter(action='post_bypass').count(),
            initial_count + 1
        )
        log = AuditLog.objects.filter(action='post_bypass').order_by('-timestamp').first()
        self.assertEqual(log.record_id, str(entry.pk))
        self.assertIn('bypass', str(log.changes).lower() or '')


class PeriodLockNormalUserFalse(PeriodLockTestCase):
    """Normal user + allow_posting_to_closed_period=False → Cannot bypass."""

    def setUp(self):
        settings = AccountingSettings.get_settings()
        settings.allow_posting_to_closed_period = False
        settings.save()

    def test_validate_for_posting_returns_errors(self):
        entry = self._create_draft_entry()
        errors = entry.validate_for_posting(user=self.normal_user)
        self.assertGreater(len(errors), 0)

    def test_post_raises_validation_error(self):
        entry = self._create_draft_entry()
        with self.assertRaises(ValidationError):
            entry.post(user=self.normal_user)


class PeriodLockNormalUserTrue(PeriodLockTestCase):
    """Normal user + allow_posting_to_closed_period=True → Still cannot bypass (superuser required)."""

    def setUp(self):
        settings = AccountingSettings.get_settings()
        settings.allow_posting_to_closed_period = True
        settings.save()

    def test_validate_for_posting_returns_errors(self):
        entry = self._create_draft_entry()
        errors = entry.validate_for_posting(user=self.normal_user)
        self.assertGreater(len(errors), 0)

    def test_post_raises_validation_error(self):
        entry = self._create_draft_entry()
        with self.assertRaises(ValidationError):
            entry.post(user=self.normal_user)


class PeriodLockUserNone(PeriodLockTestCase):
    """user=None → Bypass never works (API/background job safety)."""

    def setUp(self):
        settings = AccountingSettings.get_settings()
        settings.allow_posting_to_closed_period = True
        settings.save()

    def test_validate_for_posting_returns_errors_when_user_none(self):
        entry = self._create_draft_entry()
        errors = entry.validate_for_posting(user=None)
        self.assertGreater(len(errors), 0)

    def test_post_raises_validation_error_when_user_none(self):
        entry = self._create_draft_entry()
        with self.assertRaises(ValidationError):
            entry.post(user=None)
