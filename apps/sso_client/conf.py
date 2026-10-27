"""
Настройки единого входа. Берутся из settings.py, если заданы там, иначе из переменных окружения (.env).

Единый вход включён, только если задан SSO_SERVER_URL; иначе работает обычный вход по паролю.

    SSO_SERVER_URL           адрес сервиса авторизации для браузера, например http://auth.local/
    SSO_SERVER_INTERNAL_URL  адрес сервиса авторизации для запросов с этого сервера (по умолчанию SSO_SERVER_URL),
                             например http://127.0.0.1:8000/
    SSO_CLIENT_ID            код приложения из карточки «Единый вход → Приложения» сервиса авторизации
    SSO_CLIENT_SECRET        секрет оттуда же
    SSO_CLIENT_URL           адрес этого приложения для браузера (по умолчанию определяется по запросу)
    SSO_AUTO_CREATE          True (по умолчанию) - при первом входе создавать пользователя без прав;
                             False - пускать только тех, кто уже есть в этом проекте (по логину)
"""

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _value(name, default=None):
    value = getattr(settings, name, None)
    if value is None:
        value = os.getenv(name, default)
    return value


def _bool(name, default):
    value = _value(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _url(value):
    return value if value.endswith("/") else value + "/"


def enabled():
    """Единый вход включён (в .env задан адрес сервиса авторизации)."""
    return bool(_value("SSO_SERVER_URL"))


def server_url():
    value = _value("SSO_SERVER_URL")
    if not value:
        raise ImproperlyConfigured(
            "Задайте SSO_SERVER_URL в .env (адрес сервиса авторизации)."
        )
    return _url(value)


def server_internal_url():
    value = _value("SSO_SERVER_INTERNAL_URL")
    return _url(value) if value else server_url()


def client_id():
    return _value("SSO_CLIENT_ID", "")


def client_secret():
    return _value("SSO_CLIENT_SECRET", "")


def auto_create():
    return _bool("SSO_AUTO_CREATE", True)


def client_url():
    value = _value("SSO_CLIENT_URL")
    return _url(value) if value else None
