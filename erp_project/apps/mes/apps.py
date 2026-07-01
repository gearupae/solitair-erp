from django.apps import AppConfig


class MesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.mes'
    verbose_name = 'Manufacturing Execution'

    def ready(self):
        import apps.mes.signals  # noqa: F401
