"""Tests for estimate overhead, UOM, and installation profit calculations."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.crm.models import Customer
from apps.finance.models import TaxCode
from apps.inventory.models import Category, Item, ItemGroup
from apps.sales.estimate_overhead import expense_type_exempt_from_overhead, resolve_apply_overhead
from apps.sales.models import Estimate, EstimateItem
from apps.settings_app.models import ItemSubGroupExpenseType


class EstimateOverheadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('estuser', 'e@t.com', 'test')
        cls.customer = Customer.objects.create(name='Test Customer')
        cls.tax = TaxCode.objects.create(
            code='VAT5T',
            name='VAT 5 Test',
            rate=Decimal('5.00'),
            tax_type='standard',
            is_active=True,
        )
        cls.cat = Category.objects.create(name='Cat')
        cls.product = Item.objects.create(
            name='Product A',
            category=cls.cat,
            item_type='product',
            selling_price=Decimal('100.00'),
            no_overhead=False,
        )
        cls.service = Item.objects.create(
            name='Service A',
            category=cls.cat,
            item_type='service',
            selling_price=Decimal('50.00'),
            no_overhead=True,
        )
        cls.expense_type, _ = ItemSubGroupExpenseType.objects.get_or_create(
            name='Other expenses',
            defaults={'sort_order': 1, 'is_active': True},
        )
        cls.authority_type, _ = ItemSubGroupExpenseType.objects.get_or_create(
            name='Authority fees',
            defaults={'sort_order': 2, 'is_active': True},
        )
        cls.expense_group = ItemGroup.objects.create(
            name='Pass Through Group',
            expense_type=cls.expense_type,
        )

    def _estimate(self, **kwargs):
        defaults = {
            'date': date.today(),
            'overhead_percent': Decimal('10.00'),
        }
        defaults.update(kwargs)
        return Estimate.objects.create(
            customer=self.customer,
            assigned_to=self.user,
            **defaults,
        )

    def _line(self, estimate, **kwargs):
        defaults = {
            'description': 'Line',
            'quantity': Decimal('2'),
            'unit_price': Decimal('100.00'),
            'selling_cost': Decimal('120.00'),
            'installation_cost': Decimal('10.00'),
            'installation_selling_cost': Decimal('15.00'),
            'installation_profit_type': 'amount',
            'profit_type': 'percent',
            'tax_code': self.tax,
        }
        defaults.update(kwargs)
        return EstimateItem.objects.create(estimate=estimate, **defaults)

    def test_no_overhead_inventory_sets_apply_overhead_false_on_create(self):
        estimate = self._estimate()
        line = self._line(estimate, inventory_item=self.service, unit_price=Decimal('50.00'), selling_cost=Decimal('50.00'))
        self.assertFalse(line.apply_overhead)

    def test_apply_overhead_recomputed_on_save(self):
        estimate = self._estimate()
        line = self._line(estimate, inventory_item=self.product, apply_overhead=True)
        line.description = 'Updated'
        line.save()
        line.refresh_from_db()
        self.assertTrue(line.apply_overhead)

    def test_service_inventory_always_exempt_even_if_flag_true(self):
        estimate = self._estimate()
        line = self._line(
            estimate,
            inventory_item=self.service,
            apply_overhead=True,
            unit_price=Decimal('50.00'),
            selling_cost=Decimal('50.00'),
        )
        line.description = 'Updated'
        line.save()
        line.refresh_from_db()
        self.assertFalse(line.apply_overhead)

    def test_expense_group_auto_no_overhead_on_new_line(self):
        estimate = self._estimate()
        line = EstimateItem(
            estimate=estimate,
            group_name='Pass Through Group',
            description='Expense line',
            quantity=Decimal('1'),
            unit_price=Decimal('100.00'),
            selling_cost=Decimal('100.00'),
            tax_code=self.tax,
        )
        line.save()
        self.assertFalse(line.apply_overhead)

    def test_authority_expense_type_exempt(self):
        self.assertTrue(expense_type_exempt_from_overhead('Authority fees'))
        self.assertTrue(expense_type_exempt_from_overhead('Labour expenses'))
        self.assertFalse(expense_type_exempt_from_overhead('Materials'))

    def test_overhead_amount_when_enabled(self):
        estimate = self._estimate(overhead_percent=Decimal('10.00'))
        line = self._line(estimate, apply_overhead=True)
        # total cost = (100*2) + (10*2) = 220
        self.assertEqual(line.total_cost, Decimal('220.00'))
        self.assertEqual(line.overhead_amount, Decimal('22.00'))
        self.assertEqual(line.total_cost_with_oh, Decimal('242.00'))

    def test_overhead_amount_when_disabled(self):
        estimate = self._estimate(overhead_percent=Decimal('10.00'))
        line = self._line(
            estimate,
            inventory_item=self.service,
            unit_price=Decimal('50.00'),
            selling_cost=Decimal('50.00'),
        )
        self.assertFalse(line.apply_overhead)
        self.assertEqual(line.overhead_amount, Decimal('0.00'))
        self.assertEqual(line.total_cost_with_oh, line.total_cost)

    def test_installation_profit_percent(self):
        estimate = self._estimate()
        line = self._line(
            estimate,
            installation_cost=Decimal('10.00'),
            installation_selling_cost=Decimal('12.00'),
            installation_profit_type='percent',
        )
        self.assertEqual(line.installation_profit_value, Decimal('20.00'))
        self.assertEqual(line.net_installation_profit_amount, Decimal('4.00'))

    def test_installation_profit_amount(self):
        estimate = self._estimate()
        line = self._line(
            estimate,
            installation_cost=Decimal('10.00'),
            installation_selling_cost=Decimal('13.00'),
            installation_profit_type='amount',
        )
        self.assertEqual(line.installation_profit_value, Decimal('3.00'))

    def test_installation_profit_none_forces_selling_equals_cost(self):
        estimate = self._estimate()
        line = self._line(
            estimate,
            installation_cost=Decimal('10.00'),
            installation_selling_cost=Decimal('99.00'),
            installation_profit_type='none',
        )
        self.assertEqual(line.installation_profit_value, Decimal('0.00'))
        self.assertEqual(line.installation_selling_cost, Decimal('10.00'))

    def test_total_selling_and_vat_base(self):
        estimate = self._estimate()
        line = self._line(
            estimate,
            quantity=Decimal('2'),
            selling_cost=Decimal('120.00'),
            installation_selling_cost=Decimal('15.00'),
        )
        self.assertEqual(line.line_net_excl_vat, Decimal('240.00'))
        self.assertEqual(line.installation_net_selling, Decimal('30.00'))
        self.assertEqual(line.total_selling_price, Decimal('270.00'))
        self.assertEqual(line.total, Decimal('270.00'))
        self.assertEqual(line.vat_amount, Decimal('13.50'))
        self.assertEqual(line.quote_unit_rate, Decimal('135.00'))

    def test_estimate_calculate_totals_uses_total_selling(self):
        estimate = self._estimate()
        self._line(estimate)
        estimate.calculate_totals()
        estimate.refresh_from_db()
        self.assertEqual(estimate.subtotal, Decimal('270.00'))

    def test_resolve_apply_overhead_ignores_stale_manual_flag(self):
        line = EstimateItem(
            inventory_item=self.service,
            apply_overhead=True,
            group_name='',
            description='x',
            quantity=Decimal('1'),
            unit_price=Decimal('1'),
            selling_cost=Decimal('1'),
        )
        self.assertFalse(resolve_apply_overhead(line))
