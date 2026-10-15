"""Конфигурация приложения core."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # Импорт нужен ради побочного эффекта: при импорте модуля
        # регистрируются обработчики сигналов (создание профиля пользователя).
        import core.signals  # noqa: F401
