"""Tests for GRN and RFQ / CPA."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.finance.models import Account, AccountType, FiscalYear
from apps.inventory.models import Category, Item, Warehouse
from apps.purchase.models import PurchaseOrder, PurchaseOrderItem, Vendor
from apps.purchase.models_grn import GoodsReceiptNote
from apps.purchase.models_rfq import RFQ, RFQLine, SupplierQuote, SupplierQuoteLine
from apps.purchase.services.grn_service import post_grn_from_po
from apps.purchase.services.rfq_service import award_rfq, build_comparison_matrix, convert_awards_to_pos


class GRNServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('grnuser', 'g@t.com', 'test')
        cls.vendor = Vendor.objects.create(name='Supplier Co')
        cls.wh = Warehouse.objects.create(name='Store', status='active')
        cls.cat = Category.objects.create(name='Parts')
        cls.item = Item.objects.create(name='Bolt', category=cls.cat, purchase_price=Decimal('2'))
        Account.objects.create(code='1500', name='Inventory', account_type=AccountType.ASSET)
        Account.objects.create(code='2010', name='GRN Clearing', account_type=AccountType.LIABILITY)
        Account.objects.create(code='5100', name='COGS', account_type=AccountType.EXPENSE)
        Account.objects.create(code='5200', name='Variance', account_type=AccountType.EXPENSE)
        cls.po = PurchaseOrder.objects.create(vendor=cls.vendor, order_date=date.today(), status='confirmed')
        cls.po_line = PurchaseOrderItem.objects.create(
            purchase_order=cls.po,
            description='Bolts',
            quantity=Decimal('10'),
            unit_price=Decimal('2'),
            inventory_item=cls.item,
        )
        FiscalYear.objects.get_or_create(
            name='FY 2026',
            defaults={'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'is_closed': False},
        )

    def test_post_grn_from_po_creates_document(self):
        payloads = [{
            'purchase_order_item_id': self.po_line.pk,
            'qty_raw': '5',
            'unit_price_raw': '2',
        }]
        grn = post_grn_from_po(
            self.po.pk, self.wh.pk, date.today(), 'test', payloads, self.user,
        )
        self.assertEqual(grn.status, GoodsReceiptNote.STATUS_POSTED)
        self.assertEqual(grn.lines.count(), 1)
        self.po_line.refresh_from_db()
        self.assertEqual(self.po_line.quantity_received, Decimal('5'))


class RFQServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('rfquser', 'r@t.com', 'test')
        cls.v1 = Vendor.objects.create(name='Vendor One')
        cls.v2 = Vendor.objects.create(name='Vendor Two')
        cls.rfq = RFQ.objects.create(title='Steel RFQ', status='quotes_received', created_by=cls.user)
        cls.line = RFQLine.objects.create(rfq=cls.rfq, description='Steel bar', quantity=Decimal('100'))
        q1 = SupplierQuote.objects.create(rfq=cls.rfq, supplier=cls.v1, created_by=cls.user)
        q2 = SupplierQuote.objects.create(rfq=cls.rfq, supplier=cls.v2, created_by=cls.user)
        SupplierQuoteLine.objects.create(quote=q1, rfq_line=cls.line, unit_price=Decimal('10'))
        SupplierQuoteLine.objects.create(quote=q2, rfq_line=cls.line, unit_price=Decimal('9'))

    def test_comparison_highlights_lowest_price(self):
        matrix = build_comparison_matrix(self.rfq)
        row = matrix['rows'][0]
        self.assertEqual(row['lowest_price_supplier_id'], self.v2.pk)

    def test_award_and_po_conversion(self):
        award_rfq(self.rfq, self.user, [{
            'rfq_line_id': self.line.pk,
            'supplier_id': self.v2.pk,
            'awarded_qty': '100',
            'unit_price': '9',
        }], justification='price')
        pos = convert_awards_to_pos(self.rfq, self.user)
        self.assertEqual(len(pos), 1)
        self.assertEqual(pos[0].items.count(), 1)
