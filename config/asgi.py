"""ASGI-конфигурация проекта supply_service."""

import os

from django.core.asgi import get_asgi_application

# --- Настройки проекта ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
