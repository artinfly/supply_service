"""Общие настройки проекта supply_service (для всех машин).

Всё, что отличается от машины к машине (секретный ключ, доступ к базе, адреса
сайта и внешних сервисов), берётся из файла .env в корне проекта; образец — .env.example.
Настройки конкретного окружения — в dev.py (разработка) и prod.py (сервер).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Корень проекта — папка, где лежит manage.py
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    """Значение из .env; без значения по умолчанию переменная обязательна."""
    value = os.getenv(name, default)
    if value is None:
        raise ImproperlyConfigured(
            f"В .env не задана переменная {name} (см. .env.example)"
        )
    return value


def env_bool(name, default=False):
    """Да/нет из .env: True, 1, yes, on — да."""
    return env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    """Список из переменной .env через запятую."""
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("SECRET_KEY")


# --- Приложения ---

INSTALLED_APPS = [
    "core",
    # Единый вход через сервис авторизации (включается адресом SSO_SERVER_URL в .env)
    "apps.sso_client",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SectionAccessMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --- База данных PostgreSQL ---

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "supply_service_test"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "OPTIONS": {"client_encoding": "UTF8"},
    }
}


# --- Пользователи и вход ---

# Вход и выход — страницы /reports/login/ и /reports/logout/; при включённом
# едином входе они передают работу apps.sso_client
LOGIN_URL = "/reports/login/"
LOGIN_REDIRECT_URL = "/reports/"
LOGOUT_REDIRECT_URL = "/reports/login/"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Если несколько сервисов открываются по одному имени сервера (разные порты/пути),
# у каждого должны быть свои cookie, иначе вход в одном выбивает из другого
SESSION_COOKIE_NAME = env("SESSION_COOKIE_NAME", "sessionid")
CSRF_COOKIE_NAME = env("CSRF_COOKIE_NAME", "csrftoken")


# --- Язык и время ---

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Yekaterinburg"
USE_I18N = True
USE_TZ = True


# --- Статические файлы (CSS, JavaScript, шрифты, шаблоны Excel) ---

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]


# --- Внешние сервисы (пустой адрес — функция выключена) ---

# Кадровый сервис: подтягивание ФИО и статуса сотрудника в админке
HR_SERVICE_API_URL = env("HR_SERVICE_API_URL", "")
