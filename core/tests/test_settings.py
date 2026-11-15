"""Проверка единого модуля настроек Django."""

from django.conf import settings
from django.test import SimpleTestCase

from config import settings as project_settings


class SettingsTests(SimpleTestCase):
    """Проверки конфигурации без изменения окружения."""

    def test_standard_module_is_used(self):
        self.assertEqual(settings.SETTINGS_MODULE, "config.settings")

    def test_development_only_demo_app(self):
        self.assertEqual(
            "apps.demo" in settings.INSTALLED_APPS,
            project_settings.DEBUG,
        )

    def test_staticfiles_backend_matches_mode(self):
        actual = settings.STORAGES["staticfiles"]["BACKEND"]

        expected = (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if project_settings.DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )

        self.assertEqual(actual, expected)

    def test_custom_access_middleware_kept(self):
        self.assertIn(
            "core.middleware.SectionAccessMiddleware",
            settings.MIDDLEWARE,
        )
