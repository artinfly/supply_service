import hashlib
import hmac
import json
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import views
from .models import SsoSession

User = get_user_model()
SSO = {
    "SSO_SERVER_URL": "http://auth.local:8000/",
    "SSO_SERVER_INTERNAL_URL": "http://127.0.0.1:8000/",
    "SSO_CLIENT_ID": "supply",
    "SSO_CLIENT_SECRET": "secret",
}
PAYLOAD = {
    "sid": "sid-1",
    "user": {
        "username": "ivanov",
        "first_name": "Иван",
        "last_name": "Иванов",
        "patronymic": "П",
        "department": "Цех",
        "position": "Мастер",
    },
}


@override_settings(**SSO)
class SsoClientTests(TestCase):
    def start_login(self, next_url="/reports/"):
        response = self.client.get(reverse("sso_client:login"), {"next": next_url})
        self.assertEqual(response.status_code, 200)
        url = urlparse(response.context["url"])
        self.assertEqual(
            f"{url.scheme}://{url.netloc}{url.path}",
            "http://auth.local:8000/sso/authorize/",
        )
        return parse_qs(url.query)

    def finish_login(self, payload=PAYLOAD):
        params = self.start_login()
        with mock.patch.object(views, "_validate", return_value=payload) as validate:
            response = self.client.get(
                reverse("sso_client:callback"),
                {"ticket": "t1", "state": params["state"][0]},
            )
        validate.assert_called_once()
        return response

    def test_guest_goes_to_sso(self):
        response = self.client.get("/reports/")
        self.assertRedirects(
            response, "/reports/login/?next=/reports/", fetch_redirect_response=False
        )
        response = self.client.get(response["Location"])
        self.assertRedirects(
            response, "/sso/login/?next=%2Freports%2F", fetch_redirect_response=False
        )
        response = self.client.get(response["Location"])
        self.assertContains(response, "http://auth.local:8000/sso/authorize/")
        params = self.start_login()
        self.assertEqual(params["client_id"], ["supply"])
        self.assertEqual(params["redirect_uri"], ["http://testserver/sso/callback/"])

    def test_callback_creates_user_and_logs_in(self):
        response = self.finish_login()
        self.assertRedirects(response, "/reports/", fetch_redirect_response=False)
        user = User.objects.get(username="ivanov")
        self.assertEqual(user.last_name, "Иванов")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.client.get("/reports/").status_code, 200)
        self.assertTrue(
            SsoSession.objects.filter(sid="sid-1", username="ivanov").exists()
        )

    def test_existing_local_user_is_reused(self):
        local = User.objects.create_user("ivanov", "old-pass-1!")
        self.finish_login()
        self.assertEqual(User.objects.get(username="ivanov").pk, local.pk)
        self.assertEqual(self.client.get("/reports/").status_code, 200)

    @override_settings(SSO_AUTO_CREATE=False)
    def test_unknown_user_rejected_without_auto_create(self):
        params = self.start_login()
        with mock.patch.object(views, "_validate", return_value=PAYLOAD):
            response = self.client.get(
                reverse("sso_client:callback"),
                {"ticket": "t1", "state": params["state"][0]},
            )
        self.assertContains(response, "нет учётной записи", status_code=403)
        self.assertFalse(User.objects.exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(SSO_AUTO_CREATE=False)
    def test_known_user_allowed_without_auto_create(self):
        User.objects.create_user("ivanov", "x")
        response = self.finish_login()
        self.assertRedirects(response, "/reports/", fetch_redirect_response=False)

    def test_local_rights_are_kept(self):
        from django.contrib.auth.models import Group

        local = User.objects.create_superuser("ivanov", "old-pass-1!")
        local.groups.add(Group.objects.create(name="Местная"))
        self.finish_login()
        local.refresh_from_db()
        self.assertTrue(local.is_superuser)
        self.assertEqual(list(local.groups.values_list("name", flat=True)), ["Местная"])

    def test_home_falls_back_when_login_redirect_url_is_missing(self):
        # "/accounts/profile/" - значение Django по умолчанию, такого адреса в проекте нет
        for value in (None, "", "no_such:route", "/accounts/profile/", "/nowhere/"):
            with self.subTest(value), override_settings(LOGIN_REDIRECT_URL=value):
                self.assertEqual(views.home(), "/")
        with override_settings(LOGIN_REDIRECT_URL="/reports/"):
            self.assertEqual(views.home(), "/reports/")
        with override_settings(LOGIN_REDIRECT_URL="root"):
            self.assertEqual(views.home(), "/reports/")

    def test_bad_state_restarts_login(self):
        response = self.client.get(
            reverse("sso_client:callback"), {"ticket": "t1", "state": "forged"}
        )
        self.assertRedirects(
            response, reverse("sso_client:login"), fetch_redirect_response=False
        )

    def test_validation_error_shown(self):
        params = self.start_login()
        with mock.patch.object(
            views, "_validate", side_effect=views.SsoError("сервис недоступен")
        ):
            response = self.client.get(
                reverse("sso_client:callback"),
                {"ticket": "t1", "state": params["state"][0]},
            )
        self.assertContains(response, "сервис недоступен", status_code=502)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_external_next_ignored(self):
        params = self.start_login("https://evil.example/")
        with mock.patch.object(views, "_validate", return_value=PAYLOAD):
            response = self.client.get(
                reverse("sso_client:callback"),
                {"ticket": "t1", "state": params["state"][0]},
            )
        self.assertRedirects(response, "/reports/", fetch_redirect_response=False)

    def test_logout_goes_to_sso_logout(self):
        self.finish_login()
        response = self.client.post(reverse("sso_client:logout"))
        self.assertContains(response, "http://auth.local:8000/sso/logout/")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(SsoSession.objects.exists())

    def test_password_change_goes_to_sso(self):
        self.finish_login()
        for url in (reverse("admin:password_change"),):
            self.assertRedirects(
                self.client.get(url),
                "http://auth.local:8000/password/change/",
                fetch_redirect_response=False,
            )

    def backchannel(self, payload, secret="secret"):
        body = json.dumps(
            {"client_id": "supply", "iat": int(time.time()), **payload}
        ).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("sso_client:backchannel_logout"),
            body,
            content_type="application/json",
            HTTP_X_SSO_SIGNATURE=signature,
        )

    def test_backchannel_logout_by_sid_and_username(self):
        for payload in ({"sid": "sid-1"}, {"username": "ivanov"}):
            with self.subTest(payload):
                self.finish_login()
                self.assertEqual(self.client.get("/reports/").status_code, 200)
                self.assertEqual(self.backchannel(payload).status_code, 200)
                self.assertEqual(self.client.get("/reports/").status_code, 302)

    def test_backchannel_rejects_bad_signature(self):
        self.finish_login()
        self.assertEqual(
            self.backchannel({"sid": "sid-1"}, secret="wrong").status_code, 403
        )
        self.assertEqual(self.client.get("/reports/").status_code, 200)


@override_settings(SSO_SERVER_URL="")
class SsoDisabledTests(TestCase):
    """Без SSO_SERVER_URL единый вход выключен: обычный вход по паролю."""

    def test_password_login(self):
        self.assertEqual(self.client.get(reverse("sso_client:login")).status_code, 404)
        response = self.client.get("/reports/login/")
        self.assertContains(response, 'name="password"')
        User.objects.create_user("petrov", password="pass-123!")
        response = self.client.post(
            "/reports/login/", {"username": "petrov", "password": "pass-123!"}
        )
        self.assertRedirects(response, "/reports/", fetch_redirect_response=False)

    def test_logout_is_local(self):
        user = User.objects.create_user("petrov", password="pass-123!")
        self.client.force_login(user)
        response = self.client.post("/reports/logout/")
        self.assertRedirects(response, "/reports/login/", fetch_redirect_response=False)
