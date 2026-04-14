from django.apps import AppConfig


class StockTakeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.stock_take'
    label = 'stock_take'
    verbose_name = 'Stock Take'
