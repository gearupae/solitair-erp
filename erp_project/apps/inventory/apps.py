from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.inventory'
    verbose_name = 'Inventory'

    def ready(self):
        import apps.inventory.signals  # noqa: F401
        import apps.inventory.models_requisition  # noqa: F401
        import apps.inventory.models_inter_entity  # noqa: F401
        import apps.inventory.admin_procurement  # noqa: F401





