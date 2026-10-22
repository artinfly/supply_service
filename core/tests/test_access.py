"""Вход и права на разделы (core/middleware.py)."""

from django.test import TestCase
from django.urls import URLPattern, get_resolver, reverse

from core.middleware import PUBLIC_ROUTES, ROUTE_PERMISSIONS

from .helpers import make_user, messages_text


class AccessTests(TestCase):
    def test_every_route_has_a_section(self):
        """Новый маршрут нужно явно внести в middleware, иначе он только для суперпользователя."""
        names = {
            p.name
            for p in get_resolver("core.urls").url_patterns
            if isinstance(p, URLPattern)
        }
        self.assertEqual(names - PUBLIC_ROUTES - set(ROUTE_PERMISSIONS), set())

    def test_anonymous_page_redirects_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_anonymous_api_gets_json_401(self):
        response = self.client.get(reverse("api_all_contracts"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("Сессия истекла", response.json()["error"])

    def test_no_permission(self):
        self.client.force_login(make_user("viewer", "access_znp"))
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(page.status_code, 403)
        self.assertTemplateUsed(page, "access_denied.html")
        api = self.client.get(reverse("api_all_contracts"))
        self.assertEqual(api.status_code, 403)
        self.assertEqual(api.json(), {"error": "Нет доступа к разделу"})

    def test_permission_opens_only_its_section(self):
        self.client.force_login(make_user("viewer", "access_dashboard"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api_all_contracts")).status_code, 200)
        self.assertEqual(self.client.get(reverse("upload_excel")).status_code, 403)

    def test_sum_report_belongs_to_export_section(self):
        self.client.force_login(make_user("viewer", "access_upload"))
        response = self.client.post(reverse("sum_report_upload"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_sees_everything(self):
        self.client.force_login(make_user("admin", superuser=True))
        for name in ("dashboard", "znp_table", "znp_sap_table", "upload_excel",
                     "goz_report", "export_page", "sum_report_page"):  # fmt: skip
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_gk_directory_upload_needs_superuser(self):
        self.client.force_login(make_user("goz", "access_goz_report"))
        self.assertEqual(self.client.get(reverse("goz_report")).status_code, 200)
        response = self.client.post(reverse("upload_gk_directory"), follow=True)
        self.assertRedirects(response, reverse("goz_report"))
        self.assertIn("только суперпользователи", messages_text(response)[0])
