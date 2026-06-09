"""Tests for Inter-entity transfers."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.finance.models import Account, AccountType, FiscalYear
from apps.inventory.models import Category, Item, Stock, Warehouse
from apps.inventory.models_inter_entity import InterEntityTransfer, InterEntityTransferLine, InterEntityVatTreatment
from apps.settings_app.models import Company


def _ensure_fiscal_year():
    FiscalYear.objects.get_or_create(
        name='FY 2026',
        defaults={'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'is_closed': False},
    )


class InterEntityTransferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('admin2', 'b@t.com', 'test')
        cls.entity_a = Company.objects.create(name='Entity A')
        cls.entity_b = Company.objects.create(name='Entity B')
        cls.wh_a = Warehouse.objects.create(name='WH A', status='active', legal_entity=cls.entity_a)
        cls.wh_b = Warehouse.objects.create(name='WH B', status='active', legal_entity=cls.entity_b)
        cls.cat = Category.objects.create(name='Stock')
        cls.item = Item.objects.create(name='Widget', category=cls.cat, purchase_price=Decimal('5'))
        Stock.objects.create(item=cls.item, warehouse=cls.wh_a, quantity=Decimal('50'))
        cls.recv_acct = Account.objects.create(code='1350', name='Interco Recv', account_type=AccountType.ASSET)
        cls.pay_acct = Account.objects.create(code='2350', name='Interco Pay', account_type=AccountType.LIABILITY)
        cls.inv_acct = Account.objects.create(code='1500', name='Inventory', account_type=AccountType.ASSET)
        cls.cogs_acct = Account.objects.create(code='5100', name='COGS', account_type=AccountType.EXPENSE)
        cls.entity_a.intercompany_receivable_account = cls.recv_acct
        cls.entity_a.save(update_fields=['intercompany_receivable_account'])
        cls.entity_b.intercompany_payable_account = cls.pay_acct
        cls.entity_b.save(update_fields=['intercompany_payable_account'])
        InterEntityVatTreatment.objects.get_or_create(code='intra_emirate', defaults={'name': 'Intra-emirate'})
        _ensure_fiscal_year()

    def test_transfer_issue_reduces_source_stock(self):
        from apps.inventory.services.inter_entity_service import approve_transfer, issue_transfer

        t = InterEntityTransfer.objects.create(
            source_entity=self.entity_a,
            source_warehouse=self.wh_a,
            destination_entity=self.entity_b,
            destination_warehouse=self.wh_b,
            transfer_date=date.today(),
            created_by=self.user,
        )
        InterEntityTransferLine.objects.create(transfer=t, item=self.item, quantity=Decimal('5'))
        approve_transfer(t, self.user, 'source')
        issue_transfer(t, self.user)
        stock = Stock.objects.get(item=self.item, warehouse=self.wh_a)
        self.assertEqual(stock.quantity, Decimal('45'))
        t.refresh_from_db()
        self.assertEqual(t.status, 'in_transit')
