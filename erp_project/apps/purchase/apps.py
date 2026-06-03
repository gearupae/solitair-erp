from django.apps import AppConfig


class PurchaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.purchase'
    verbose_name = 'Purchase'

    def ready(self):
        import apps.purchase.models_grn  # noqa: F401
        import apps.purchase.models_rfq  # noqa: F401





