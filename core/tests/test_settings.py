"""Regression checks for the unified Django settings module."""

from django.conf import settings
from django.test import SimpleTestCase


class SettingsTests(SimpleTestCase):
    def test_standard_module_is_used(self):
        self.assertEqual(settings.SETTINGS_MODULE, "config.settings")

    def test_development_only_demo_app(self):
        self.assertEqual("apps.demo" in settings.INSTALLED_APPS, settings.DEBUG)

    def test_staticfiles_backend_matches_mode(self):
        actual = settings.STORAGES["staticfiles"]["BACKEND"]
        if settings.DEBUG:
            self.assertEqual(
                actual, "django.contrib.staticfiles.storage.StaticFilesStorage"
            )
        else:
            self.assertEqual(
                actual, "whitenoise.storage.CompressedManifestStaticFilesStorage"
            )

    def test_custom_access_middleware_kept(self):
        self.assertIn("core.middleware.SectionAccessMiddleware", settings.MIDDLEWARE)
