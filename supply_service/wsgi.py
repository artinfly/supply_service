# Точка входа для боевого веб-сервера. При runserver не используется.
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "supply_service.settings")
application = get_wsgi_application()
