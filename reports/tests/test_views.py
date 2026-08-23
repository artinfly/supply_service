import json

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from reports.services.queries import contract_dupes

from .factories import contract_row, contracts_file, load, znp_file, znp_row
from .routes import IGK


class ExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_кдр_с_кривой_датой_отвечает_400_а_не_падает(self):
        resp = self.client.get(
            reverse("export_kdr", args=["2026"]),
            {"start": "notadate", "end": "2026-12-31"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_кдр_с_нормальным_периодом_отдаёт_файл(self):
        resp = self.client.get(
            reverse("export_kdr", args=["2026"]),
            {"start": "2026-01-01", "end": "2026-12-31"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_недопустимый_год_отвечает_400(self):
        resp = self.client.get(reverse("export_kdr", args=["1999"]))
        self.assertEqual(resp.status_code, 400)


class FilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss2", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row()]))

    def _rows(self, name, params):
        resp = self.client.get(reverse(name), params)
        self.assertEqual(resp.status_code, 200)
        return json.loads(resp.content)

    def test_без_фильтра_статусов_видно_всё(self):
        self.assertTrue(self._rows("api_all_contracts", {}))
        self.assertTrue(self._rows("api_znp_list", {}))

    def test_пустой_фильтр_статусов_ничего_не_показывает(self):
        self.assertEqual(self._rows("api_all_contracts", {"status": ""}), [])
        self.assertEqual(self._rows("api_znp_list", {"status": ""}), [])
        self.assertEqual(self._rows("api_znp_sap_list", {"status": ""}), [])

    def test_фильтр_по_статусу_работает(self):
        self.assertTrue(self._rows("api_all_contracts", {"status": "Исполняется"}))
        self.assertEqual(self._rows("api_all_contracts", {"status": "Черновик"}), [])


class DupeHashTests(TestCase):
    def test_хеш_дублей_совпадает_с_хешем_истории(self):
        load("load_contracts", contracts_file([contract_row(), contract_row()]))

        with connection.cursor() as cur:
            sql, params = contract_dupes()
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self.assertEqual(len(rows), 1)

        with connection.cursor() as cur:
            cur.execute("""
                SELECT encode(digest(concat(igk, c_agent, contract, item,
                       "order", TRIM(stage), plan_date), 'md5'), 'hex')
                FROM igk_stat_data LIMIT 1
                """)
            эталон = cur.fetchone()[0]
        self.assertEqual(rows[0]["hash"], эталон)


class ChartPeriodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss3", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row(znp_date="15.02.2026")]))

    def _chart(self, params):
        resp = self.client.get(reverse("api_chart_znp"), params)
        self.assertEqual(resp.status_code, 200)
        return json.loads(resp.content)

    def _stage_count(self, payload, stage):
        for ds in payload["datasets"]:
            if ds["label"] == stage:
                return sum(ds["counts"])
        return 0

    def test_период_включающий_дату_заявки_её_оставляет(self):
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
        payload = self._chart({"igk": IGK, "year": "2026"})
        self.assertEqual(self._stage_count(payload, "Оплачено"), 1)

    def test_кривая_дата_периода_отвечает_400(self):
        resp = self.client.get(
            reverse("api_chart_znp"),
            {"igk": IGK, "year": "2026", "start": "нет", "end": "2026-05-31"},
        )
        self.assertEqual(resp.status_code, 400)


class ChartPeriodPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("boss4", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row()]))

    def test_на_странице_есть_поля_периода(self):
        html = self.client.get(reverse("znp_table")).content.decode()
        self.assertIn('id="chart-start"', html)
        self.assertIn('id="chart-end"', html)
        self.assertIn('id="chart-apply"', html)
        self.assertIn('id="chart-reset"', html)

    def test_период_из_адреса_подставляется_в_поля(self):
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
        resp = self.client.get(reverse("znp_table"), {"start": "нет", "end": "нет"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            'id="chart-start" class="filter-input" style="width:160px" value=""',
            resp.content.decode(),
        )
