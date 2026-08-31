"""
Тесты представлений: выгрузки, фильтры, дубликаты и графики.

Проверяют:
- Выгрузку КДР с периодами и обработкой ошибок
- Фильтры реестров (по статусам и без них)
- Совпадение хеша дубликатов с хешем истории изменений
- Период графика заявок ФЗД (включение/исключение заявок по датам)
- Подстановку периода из адресной строки на странице
"""

import json

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from reports.services.queries import contract_dupes

from .factories import contract_row, contracts_file, load, znp_file, znp_row
from .routes import IGK

# ============================================================================
# Выгрузка КДР
# ============================================================================


class ExportTests(TestCase):
    """Проверки выгрузки «Контроль договорной работы»."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_кдр_с_кривой_датой_отвечает_400_а_не_падает(self):
        """Невалидная дата периода возвращает 400, а не 500."""
        resp = self.client.get(
            reverse("export_kdr", args=["2026"]),
            {"start": "notadate", "end": "2026-12-31"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_кдр_с_нормальным_периодом_отдаёт_файл(self):
        """Валидный период возвращает 200 и xlsx-файл."""
        resp = self.client.get(
            reverse("export_kdr", args=["2026"]),
            {"start": "2026-01-01", "end": "2026-12-31"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_недопустимый_год_отвечает_400(self):
        """Год не из списка YEARS возвращает 400."""
        resp = self.client.get(reverse("export_kdr", args=["1999"]))
        self.assertEqual(resp.status_code, 400)


# ============================================================================
# Фильтры реестров
# ============================================================================


class FilterTests(TestCase):
    """Проверки фильтров по статусам в реестрах договоров и заявок."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss2", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        # Загружаем по одной строке договоров и заявок для проверки
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row()]))

    def _rows(self, name, params):
        """Выполняет запрос к API и возвращает распарсенный JSON."""
        resp = self.client.get(reverse(name), params)
        self.assertEqual(resp.status_code, 200)
        return json.loads(resp.content)

    def test_без_фильтра_статусов_видно_всё(self):
        """Без фильтра статусов реестры показывают все данные."""
        self.assertTrue(self._rows("api_all_contracts", {}))
        self.assertTrue(self._rows("api_znp_list", {}))

    def test_пустой_фильтр_статусов_ничего_не_показывает(self):
        """Пустое значение фильтра статусов возвращает пустой список."""
        self.assertEqual(self._rows("api_all_contracts", {"status": ""}), [])
        self.assertEqual(self._rows("api_znp_list", {"status": ""}), [])
        self.assertEqual(self._rows("api_znp_sap_list", {"status": ""}), [])

    def test_фильтр_по_статусу_работает(self):
        """Фильтр по существующему статусу находит данные, по несуществующему — нет."""
        self.assertTrue(self._rows("api_all_contracts", {"status": "Исполняется"}))
        self.assertEqual(self._rows("api_all_contracts", {"status": "Черновик"}), [])


# ============================================================================
# Дубликаты: проверка хеша
# ============================================================================


class DupeHashTests(TestCase):
    """Проверка, что хеш дубликатов совпадает с хешем истории изменений."""

    def test_хеш_дублей_совпадает_с_хешем_истории(self):
        """
        Хеш в таблице дубликатов строится из тех же полей, что и хеш истории:
        ИГК + контрагент + договор + предмет + заказ + этап + дата плана.
        Если они совпадают — значит дубль найден корректно.
        """
        # Загружаем две одинаковые строки — они должны стать дублями
        load("load_contracts", contracts_file([contract_row(), contract_row()]))

        # Запрашиваем дубликаты через SQL
        with connection.cursor() as cur:
            sql, params = contract_dupes()
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self.assertEqual(len(rows), 1)

        # Вычисляем эталонный хеш напрямую из таблицы через pgcrypto
        with connection.cursor() as cur:
            cur.execute("""
                SELECT encode(digest(concat(igk, c_agent, contract, item,
                       "order", TRIM(stage), plan_date), 'md5'), 'hex')
                FROM igk_stat_data LIMIT 1
                """)
            эталон = cur.fetchone()[0]
        self.assertEqual(rows[0]["hash"], эталон)


# ============================================================================
# Период графика заявок ФЗД
# ============================================================================


class ChartPeriodTests(TestCase):
    """Проверки периода графика заявок ФЗД (старт/энд)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss3", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        # Загружаем заявку с датой 15.02.2026 для проверки периода
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row(znp_date="15.02.2026")]))

    def _chart(self, params):
        """Выполняет запрос к графику и возвращает распарсенный JSON."""
        resp = self.client.get(reverse("api_chart_znp"), params)
        self.assertEqual(resp.status_code, 200)
        return json.loads(resp.content)

    def _stage_count(self, payload, stage):
        """Возвращает суммарное количество заявок на указанной стадии."""
        for ds in payload["datasets"]:
            if ds["label"] == stage:
                return sum(ds["counts"])
        return 0

    def test_период_включающий_дату_заявки_её_оставляет(self):
        """Заявка попадает в график, если её дата внутри периода."""
        payload = self._chart(
            {
                "igk": IGK,
                "year": "2026",
                "start": "2026-02-01",
                "end": "2026-02-28",
            }
        )
        self.assertEqual(self._stage_count(payload, "Оплачено"), 1)

    def test_период_вне_даты_заявки_её_убирает(self):
        """Заявка не попадает в график, если её дата вне периода."""
        payload = self._chart(
            {
                "igk": IGK,
                "year": "2026",
                "start": "2026-05-01",
                "end": "2026-05-31",
            }
        )
        self.assertEqual(self._stage_count(payload, "Оплачено"), 0)

    def test_без_периода_заявка_на_месте(self):
        """Без фильтра по периоду все заявки видны."""
        payload = self._chart({"igk": IGK, "year": "2026"})
        self.assertEqual(self._stage_count(payload, "Оплачено"), 1)

    def test_кривая_дата_периода_отвечает_400(self):
        """Невалидная дата периода возвращает 400."""
        resp = self.client.get(
            reverse("api_chart_znp"),
            {"igk": IGK, "year": "2026", "start": "нет", "end": "2026-05-31"},
        )
        self.assertEqual(resp.status_code, 400)


# ============================================================================
# Страница с периодом графика
# ============================================================================


class ChartPeriodPageTests(TestCase):
    """Проверки подстановки периода в поля на странице сводки заявок."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss4", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row()]))

    def test_на_странице_есть_поля_периода(self):
        """На странице есть все элементы управления периодом."""
        html = self.client.get(reverse("znp_table")).content.decode()
        self.assertIn('id="chart-start"', html)
        self.assertIn('id="chart-end"', html)
        self.assertIn('id="chart-apply"', html)
        self.assertIn('id="chart-reset"', html)

    def test_период_из_адреса_подставляется_в_поля(self):
        """Валидный период из URL подставляется в поля формы."""
        resp = self.client.get(
            reverse("znp_table"), {"start": "2026-02-01", "end": "2026-02-28"}
        )
        html = resp.content.decode()
        self.assertIn(
            'id="chart-start" class="filter-input" style="width:160px" value="2026-02-01"',
            html,
        )
        self.assertIn('value="2026-02-28"', html)

    def test_кривой_период_из_адреса_игнорируется(self):
        """Невалидный период из URL игнорируется, поля остаются пустыми."""
        resp = self.client.get(reverse("znp_table"), {"start": "нет", "end": "нет"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            'id="chart-start" class="filter-input" style="width:160px" value=""',
            resp.content.decode(),
        )
