# Регистрация приложения в Django. Трогать не нужно.
from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = "reports"
    default_auto_field = "django.db.models.BigAutoField"
