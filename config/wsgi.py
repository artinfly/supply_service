"""WSGI-конфигурация проекта supply_service."""

import os

from django.core.wsgi import get_wsgi_application

# --- Настройки проекта ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
