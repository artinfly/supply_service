from django.apps import AppConfig


class DemoConfig(AppConfig):
    """Демо-данные для разработки (manage.py seed_demo). Подключается только при DEBUG=True."""

    name = "apps.demo"
    label = "demo"
    verbose_name = "Демо-данные"
