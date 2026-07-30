# Точка входа для асинхронного сервера. Сейчас не используется.
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "supply_service.settings")
application = get_asgi_application()
