"""Django settings for supply_service.

Configuration is kept in one standard settings.py. Local differences are read
from .env; DEBUG controls development-only features and static storage.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Existing deployments use the .env file as the source of settings.
load_dotenv(BASE_DIR / ".env", override=True)


def env(name, default=None):
    """Return a required or optional environment setting."""
    value = os.getenv(name, default)
    if value is None:
        raise ImproperlyConfigured(
            f"В .env не задана переменная {name} (см. .env.example)"
        )
    return value


def env_bool(name, default=False):
    """Read an environment toggle as a boolean."""
    return str(env(name, str(default))).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    """Read a comma-separated environment setting."""
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# Security: if DEBUG is not set, the application runs in production mode.
SECRET_KEY = env("SECRET_KEY")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else ""
)

INSTALLED_APPS = [
    "core",
    "apps.sso_client",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
if DEBUG:
    # The seed_demo command intentionally exists only in development.
    INSTALLED_APPS.append("apps.demo")

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

# PostgreSQL schema and migration paths remain unchanged.
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

LOGIN_URL = "/reports/login/"
LOGIN_REDIRECT_URL = "/reports/"
LOGOUT_REDIRECT_URL = "/reports/login/"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Separate cookie names are important if several services share one hostname.
SESSION_COOKIE_NAME = env("SESSION_COOKIE_NAME", "sessionid")
CSRF_COOKIE_NAME = env("CSRF_COOKIE_NAME", "csrftoken")

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Yekaterinburg"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]

# Preserve the original development/production distinction without extra modules.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
if DEBUG:
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = True
else:
    USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST")
    if env_bool("SECURE_PROXY_SSL_HEADER"):
        # Only enable when the reverse proxy strips client-supplied headers.
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
    SESSION_COOKIE_SECURE = env_bool("HTTPS")
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    CSRF_COOKIE_HTTPONLY = True

# Integration endpoints: empty URL disables the optional integration.
HR_SERVICE_API_URL = env("HR_SERVICE_API_URL", "")
