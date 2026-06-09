"""Tests for new inventory reports and AI forecast."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.inventory.models import Category, Item, Stock, StockMovement, Warehouse
from apps.inventory.models_reporting import InventoryCostLayer, InventoryForecast
from apps.inventory.reports.demand_supply_gap import build_demand_supply_gap_report
from apps.inventory.reports.reorder import build_reorder_report
from apps.inventory.services.ai_forecast import ForecastRateLimited, refresh_item_forecast
from apps.inventory.services.fifo_service import rebuild_fifo_layers

User = get_user_model()


class FIFOServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('fifo', password='x')
        self.wh = Warehouse.objects.create(
            code='WH-T', name='Test WH', status='active', created_by=self.user,
        )
        self.cat = Category.objects.create(name='T', code='T', created_by=self.user)
        self.item = Item.objects.create(
            name='FIFO Item', category=self.cat, purchase_price=Decimal('10'),
            minimum_stock=Decimal('5'), created_by=self.user,
        )

    def test_fifo_layers_rebuild_and_consume(self):
        StockMovement.objects.create(
            item=self.item, warehouse=self.wh, movement_type='in', source='opening',
            quantity=Decimal('10'), unit_cost=Decimal('10'), movement_date=date.today(),
            created_by=self.user,
        )
        StockMovement.objects.create(
            item=self.item, warehouse=self.wh, movement_type='in', source='purchase',
            quantity=Decimal('5'), unit_cost=Decimal('12'), movement_date=date.today(),
            created_by=self.user,
        )
        StockMovement.objects.create(
            item=self.item, warehouse=self.wh, movement_type='out', source='manual',
            quantity=Decimal('8'), unit_cost=Decimal('10'), movement_date=date.today(),
            created_by=self.user,
        )
        n = rebuild_fifo_layers()
        self.assertGreater(n, 0)
        layers = list(
            InventoryCostLayer.objects.filter(item=self.item, qty_remaining__gt=0).order_by('received_date')
        )
        self.assertTrue(layers)
        total_qty = sum(l.qty_remaining for l in layers)
        self.assertEqual(total_qty, Decimal('7'))


class ReorderReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reorder', password='x')
        self.wh = Warehouse.objects.create(
            code='WH-R', name='R WH', status='active', created_by=self.user,
        )
        self.cat = Category.objects.create(name='R', code='R', created_by=self.user)
        self.item = Item.objects.create(
            name='Low Item', category=self.cat, purchase_price=Decimal('5'),
            minimum_stock=Decimal('20'), created_by=self.user,
        )
        Stock.objects.create(item=self.item, warehouse=self.wh, quantity=Decimal('5'))

    def test_reorder_qty_calculation(self):
        data = build_reorder_report(below_min_only=True)
        self.assertGreaterEqual(data['summary']['below_min'], 1)
        row = next(r for r in data['rows'] if r['sku'] == self.item.item_code)
        self.assertEqual(row['reorder_qty'], 15.0)


class DemandSupplyGapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('gap', password='x')
        self.wh = Warehouse.objects.create(
            code='WH-G', name='G WH', status='active', created_by=self.user,
        )
        self.cat = Category.objects.create(name='G', code='G', created_by=self.user)
        self.item = Item.objects.create(
            name='Gap Item', category=self.cat, purchase_price=Decimal('1'),
            minimum_stock=Decimal('0'), created_by=self.user,
        )
        Stock.objects.create(item=self.item, warehouse=self.wh, quantity=Decimal('10'))

    def test_gap_report_includes_item(self):
        data = build_demand_supply_gap_report(period_days=30)
        row = next((r for r in data['rows'] if r['sku'] == self.item.item_code), None)
        self.assertIsNotNone(row)
        self.assertGreaterEqual(row['supply'], 10.0)


class AIForecastReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('fc', password='x')
        self.wh = Warehouse.objects.create(
            code='WH-F', name='F WH', status='active', created_by=self.user,
        )
        self.cat = Category.objects.create(name='F', code='F', created_by=self.user)
        self.item = Item.objects.create(
            name='Forecast Item',
            category=self.cat,
            purchase_price=Decimal('10'),
            minimum_stock=Decimal('5'),
            lead_time_days=14,
            safety_stock_qty=5,
            created_by=self.user,
        )
        Stock.objects.create(item=self.item, warehouse=self.wh, quantity=Decimal('10'))
        InventoryForecast.objects.create(
            item=self.item,
            forecast_date=date.today(),
            forecast_30=Decimal('20'),
            forecast_60=Decimal('40'),
            forecast_90=Decimal('60'),
            avg_monthly_consumption=Decimal('15'),
            confidence='high',
            refreshed_at=timezone.now(),
        )

    def test_report_includes_enhanced_columns(self):
        from apps.inventory.services.ai_forecast import build_ai_forecast_report

        data = build_ai_forecast_report()
        row = next(r for r in data['all_rows'] if r['sku'] == self.item.item_code)
        self.assertIn('current_stock', row)
        self.assertIn('stockout_risk', row)
        self.assertIn('suggested_order_qty', row)
        self.assertIn('status', row)
        self.assertIn('trend_label', row)
        self.assertGreaterEqual(data['summary']['stockout_risk_count'], 0)


class AIForecastServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ai', password='x')
        self.cat = Category.objects.create(name='A', code='A', created_by=self.user)
        self.item = Item.objects.create(
            name='AI Item', category=self.cat, purchase_price=Decimal('1'),
            created_by=self.user,
        )

    @patch('apps.inventory.services.ai_forecast.fetch_forecast_from_openai')
    @patch('apps.inventory.services.ai_forecast.get_openai_api_key', return_value='sk-test')
    def test_refresh_creates_forecast(self, _key, mock_fetch):
        mock_fetch.return_value = {
            'forecast_30': 10,
            'forecast_60': 20,
            'forecast_90': 30,
            'confidence': 'high',
            'reasoning': 'test',
        }
        fc = refresh_item_forecast(self.item)
        self.assertEqual(fc.forecast_30, Decimal('10'))
        self.assertEqual(InventoryForecast.objects.filter(item=self.item).count(), 1)

    @patch('apps.inventory.services.ai_forecast.get_openai_api_key', return_value='sk-test')
    def test_rate_limit(self, _key):
        InventoryForecast.objects.create(
            item=self.item,
            forecast_date=date.today(),
            refreshed_at=timezone.now(),
        )
        with self.assertRaises(ForecastRateLimited):
            refresh_item_forecast(self.item)
