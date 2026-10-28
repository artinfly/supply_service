"""Настройки проекта: base.py (общие), dev.py (разработка), prod.py (сервер).

Обычно модуль указывается полностью:
    manage.py   -> config.settings.dev  (по умолчанию)
    wsgi / asgi -> config.settings.prod (по умолчанию)

Но если где-то (служба systemd, скрипт обновления, переменная окружения Windows)
осталось старое DJANGO_SETTINGS_MODULE=config.settings — раньше настройки лежали
одним файлом config/settings.py, — Django загрузил бы этот пустой пакет, не увидел
бы SECRET_KEY, базу и остальное из .env и упал. Поэтому в этом случае настройки
выбираются здесь по DEBUG из .env: DEBUG=True — dev, иначе — prod.
"""

import os
from pathlib import Path

if os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings":
    from dotenv import load_dotenv

    # .env лежит в корне проекта, рядом с manage.py
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=True)

    if os.getenv("DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
        from .dev import *  # noqa: F401,F403
    else:
        from .prod import *  # noqa: F401,F403
