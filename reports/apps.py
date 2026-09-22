"""Конфигурация приложения reports."""

from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reports"

    def ready(self):
        """Подключение сигналов при запуске приложения."""
        import reports.signals
