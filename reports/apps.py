"""
Конфигурация приложения reports.

Здесь настраивается приложение Django и выполняется импорт сигналов
при запуске (метод ready).
"""

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ReportsConfig(AppConfig):
    """
    Конфигурация для приложения reports.
    default_auto_field — тип автоинкрементного поля для моделей.
    """

    name = "reports"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """
        Вызывается при инициализации приложения.
        Импортируем модуль signals, чтобы зарегистрировать обработчики
        сигналов (например, для автоматического создания профиля пользователя).
        """
        import reports.signals  # noqa: F401

        logger.debug("Сигналы приложения reports зарегистрированы")
