import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.finance'
    verbose_name = 'Finance'

    def ready(self):
        """Validate core account mappings at finance module startup."""
        try:
            from django.db import connection
            from apps.finance.models import AccountMapping

            table_names = connection.introspection.table_names()
            if 'finance_accountmapping' not in table_names:
                return

            missing = AccountMapping.validate_core_mappings()
            if missing:
                labels = [
                    label
                    for code, label in AccountMapping.CORE_REQUIRED_MAPPINGS
                    if code in missing
                ]
                logger.warning(
                    'Finance core account mappings incomplete: %s',
                    ', '.join(labels),
                )
        except Exception:
            # App may load before migrations (e.g. migrate, test setup).
            pass





