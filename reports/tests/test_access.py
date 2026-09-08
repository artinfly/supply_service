"""
Тесты прав доступа к разделам приложения.

Проверяют:
- Соответствие маршрутов в тестах и в `urls.py`
- Работу `SectionAccessMiddleware`: закрытие разделов без прав,
  открытие только своего раздела, доступ суперпользователя
- Форму в админке: сохранение галочек разделов без потери чужих прав
"""

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import get_resolver, reverse

from reports.middleware import SECTIONS, perm_for

from .routes import ALL

# ============================================================================
# Соответствие маршрутов
# ============================================================================


class RouteMapTests(TestCase):
    """Проверка, что список маршрутов в тестах не расходится с `urls.py`."""

    def test_список_маршрутов_в_тестах_совпадает_с_urls(self):
        """
        Все маршруты из `urls.py` (кроме служебных login/logout)
        присутствуют в тестовом списке ALL из `routes.py`.

        Если добавить новый маршрут и забыть про тесты — этот тест упадёт.
        """
        из_urls = {p.name for p in get_resolver("reports.urls").url_patterns} - {
            "login",
            "logout",
        }
        self.assertEqual(из_urls, {name for name, _ in ALL})

    def test_каждый_маршрут_кроме_служебных_отнесён_к_разделу(self):
        """
        Все маршруты, кроме главной страницы (root), относятся к какому-то разделу.

        Если новый маршрут не попадает ни в один раздел из `SECTIONS`,
        middleware его не проверяет — тест напоминает про это.
        """
        без_раздела = [name for name, _ in ALL if perm_for(name) is None]
        self.assertEqual(без_раздела, ["root"])


# ============================================================================
# Проверка прав доступа через middleware
# ============================================================================


class SectionAccessTests(TestCase):
    """Проверки работы `SectionAccessMiddleware`."""

    @classmethod
    def setUpTestData(cls):
        # Кэш прав: имя раздела -> объект Permission
        cls.перм = {
            section: Permission.objects.get(codename=section) for section, _ in SECTIONS
        }

    def _пользователь(self, *sections):
        """
        Создаёт пользователя с указанными правами доступа к разделам.

        Если права не указаны — создаётся пользователь без прав.
        """
        user = User.objects.create_user("u" + "_".join(sections) or "u0", password="x")
        for s in sections:
            user.user_permissions.add(self.перм[s])
        return user

    def test_без_прав_закрыты_все_разделы(self):
        """Пользователь без прав видит только главную, остальные разделы — 403."""
        self.client.force_login(self._пользователь())
        # Главная страница доступна всем вошедшим
        self.assertEqual(self.client.get(reverse("root")).status_code, 200)
        # Остальные маршруты закрыты
        for name, args in ALL:
            if name == "root":
                continue
            with self.subTest(маршрут=name):
                resp = self.client.get(reverse(name, args=args))
                self.assertEqual(resp.status_code, 403)

    def test_право_открывает_ровно_свой_раздел(self):
        """
        Право на раздел открывает только маршруты этого раздела.

        Для каждого права проверяем все маршруты:
        - маршруты этого раздела и без раздела → 200
        - маршруты других разделов → 403
        """
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
        """
        При отказе в доступе к API возвращается JSON с ошибкой,
        а не страница «Нет доступа».
        """
        self.client.force_login(self._пользователь())
        resp = self.client.get(reverse("api_znp_list"))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp["Content-Type"], "application/json")

    def test_суперпользователь_проходит_везде(self):
        """Суперпользователь имеет доступ ко всем разделам."""
        self.client.force_login(
            User.objects.create_superuser("root_user", password="x")
        )
        for name, args in ALL:
            with self.subTest(маршрут=name):
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code, 200
                )

    def test_гостя_отправляет_на_вход(self):
        """Неаутентифицированный пользователь редиректится на страницу входа."""
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])


# ============================================================================
# Форма в админке: галочки разделов
# ============================================================================


class AdminSectionFormTests(TestCase):
    """Проверка сохранения галочек доступа в админке пользователя."""

    def test_галки_разделов_сохраняются_и_не_трогают_чужие_права(self):
        """
        При сохранении галочек разделов в админке:
        - выбранные права добавляются пользователю
        - остальные права пользователя не теряются

        Это проверяет логику `save_related` в `UserWithSectionsAdmin`:
        права, не начинающиеся с "access_", сохраняются как есть.
        """
        admin = User.objects.create_superuser("admin_user", password="x")
        user = User.objects.create_user("worker", password="x")
        # Даём пользователю «чужое» право, не связанное с разделами
        чужое = Permission.objects.get(codename="add_user")
        user.user_permissions.add(чужое)

        # Сохраняем форму в админке с одной галочкой раздела
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
        # У пользователя должно быть и чужое право, и право на раздел
        коды = set(user.user_permissions.values_list("codename", flat=True))
        self.assertEqual(коды, {"add_user", "access_kdr"})
