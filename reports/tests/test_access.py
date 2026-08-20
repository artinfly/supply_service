from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import get_resolver, reverse

from reports.middleware import SECTIONS, perm_for

from .routes import ALL


class RouteMapTests(TestCase):
    def test_список_маршрутов_в_тестах_совпадает_с_urls(self):
        из_urls = {p.name for p in get_resolver("reports.urls").url_patterns} - {
            "login",
            "logout",
        }
        self.assertEqual(из_urls, {name for name, _ in ALL})

    def test_каждый_маршрут_кроме_служебных_отнесён_к_разделу(self):
        без_раздела = [name for name, _ in ALL if perm_for(name) is None]
        self.assertEqual(без_раздела, ["root"])


class SectionAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.перм = {
            section: Permission.objects.get(codename=section) for section, _ in SECTIONS
        }

    def _пользователь(self, *sections):
        user = User.objects.create_user("u" + "_".join(sections) or "u0", password="x")
        for s in sections:
            user.user_permissions.add(self.перм[s])
        return user

    def test_без_прав_закрыты_все_разделы(self):
        self.client.force_login(self._пользователь())
        self.assertEqual(self.client.get(reverse("root")).status_code, 200)
        for name, args in ALL:
            if name == "root":
                continue
            with self.subTest(маршрут=name):
                resp = self.client.get(reverse(name, args=args))
                self.assertEqual(resp.status_code, 403)

    def test_право_открывает_ровно_свой_раздел(self):
        for section, _ in SECTIONS:
            user = self._пользователь(section)
            self.client.force_login(user)
            for name, args in ALL:
                нужно = perm_for(name)
                ожидание = 200 if нужно in (None, f"reports.{section}") else 403
                with self.subTest(право=section, маршрут=name):
                    resp = self.client.get(reverse(name, args=args))
                    self.assertEqual(resp.status_code, ожидание)
            self.client.logout()

    def test_api_отвечает_json_а_не_страницей(self):
        self.client.force_login(self._пользователь())
        resp = self.client.get(reverse("api_znp_list"))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp["Content-Type"], "application/json")

    def test_суперпользователь_проходит_везде(self):
        self.client.force_login(
            User.objects.create_superuser("root_user", password="x")
        )
        for name, args in ALL:
            with self.subTest(маршрут=name):
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code, 200
                )

    def test_гостя_отправляет_на_вход(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])


class AdminSectionFormTests(TestCase):
    def test_галки_разделов_сохраняются_и_не_трогают_чужие_права(self):
        admin = User.objects.create_superuser("admin_user", password="x")
        user = User.objects.create_user("worker", password="x")
        чужое = Permission.objects.get(codename="add_user")
        user.user_permissions.add(чужое)

        self.client.force_login(admin)
        доступ = Permission.objects.get(codename="access_kdr")
        resp = self.client.post(
            f"/admin/auth/user/{user.pk}/change/",
            {
                "username": "worker",
                "first_name": "",
                "last_name": "",
                "email": "",
                "is_active": "on",
                "last_login_0": "",
                "last_login_1": "",
                "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
                "sections": [str(доступ.pk)],
            },
        )
        self.assertEqual(resp.status_code, 302)
        коды = set(user.user_permissions.values_list("codename", flat=True))
        self.assertEqual(коды, {"add_user", "access_kdr"})
