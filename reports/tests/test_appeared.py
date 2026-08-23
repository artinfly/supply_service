import json

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from reports.models import ContractsAppeared
from reports.services.queries import contract_dupes, contract_dupes_by_order

from .factories import contract_row, contracts_file, load


def rows(sql_and_params):
    sql, params = sql_and_params
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


class AppearedTests(TestCase):
    def test_первая_загрузка_журнал_не_заполняет(self):
        load("load_contracts", contracts_file([contract_row()]))
        self.assertEqual(ContractsAppeared.objects.count(), 0)

    def test_новая_позиция_попадает_как_заключённая(self):
        load("load_contracts", contracts_file([contract_row()]))
        load(
            "load_contracts",
            contracts_file([contract_row(), contract_row(dogovor="Д-2", zakaz="З-2")]),
        )
        появилось = ContractsAppeared.objects.get()
        self.assertEqual(появилось.kind, "concluded")
        self.assertEqual(появилось.reason, "новая позиция")
        self.assertEqual(появилось.contract, "Д-2")
        self.assertEqual(появилось.cfo, "421")

    def test_смена_статуса_на_заключённый(self):
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполняется")]))
        появилось = ContractsAppeared.objects.get(kind="concluded")
        self.assertEqual(появилось.reason, "смена статуса")
        self.assertEqual(появилось.status, "Исполняется")

    def test_смена_статуса_на_незаключённый(self):
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполняется")]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        появилось = ContractsAppeared.objects.get(kind="not_concluded")
        self.assertEqual(появилось.reason, "смена статуса")

    def test_повторная_загрузка_ничего_не_добавляет(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row()]))
        self.assertEqual(ContractsAppeared.objects.count(), 0)

    def test_расторгнутые_в_журнал_не_идут(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Расторгнут")]))
        self.assertEqual(ContractsAppeared.objects.count(), 0)

    def test_журнал_накапливается_между_загрузками(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполняется")]))
        self.assertEqual(ContractsAppeared.objects.count(), 2)
        self.assertEqual(
            sorted(ContractsAppeared.objects.values_list("kind", flat=True)),
            ["concluded", "not_concluded"],
        )


class AppearedExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("app_boss", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_обе_выгрузки_отдают_файл(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        for name in ("export_appeared_concluded", "export_appeared_not_concluded"):
            with self.subTest(выгрузка=name):
                resp = self.client.get(reverse(name))
                self.assertEqual(resp.status_code, 200)
                self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_выгрузка_дублей_по_заказу_отдаёт_файл(self):
        load("load_contracts", contracts_file([contract_row(), contract_row()]))
        resp = self.client.get(reverse("export_contract_dupes_by_order"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])


class DupeFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("dupe_boss", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        load(
            "load_contracts",
            contracts_file(
                [
                    contract_row(cfo="421"),
                    contract_row(cfo="421"),
                    contract_row(cfo="422", dogovor="Д-9", zakaz="З-9"),
                    contract_row(cfo="422", dogovor="Д-9", zakaz="З-9"),
                    contract_row(cfo="423", dogovor="Д-7", god_igk="2025"),
                    contract_row(cfo="423", dogovor="Д-7", god_igk="2025"),
                ]
            ),
        )

    def test_без_фильтра_видны_все_группы(self):
        self.assertEqual(len(rows(contract_dupes())), 3)

    def test_фильтр_цфо_оставляет_свою_группу(self):
        отобрано = rows(contract_dupes("422", ""))
        self.assertEqual(len(отобрано), 1)
        self.assertEqual(отобрано[0]["contract"], "Д-9")

    def test_фильтр_года_работает(self):
        отобрано = rows(contract_dupes("", "2025"))
        self.assertEqual(len(отобрано), 1)
        self.assertEqual(отобрано[0]["contract"], "Д-7")

    def test_колонка_цфо_есть_в_обоих_запросах(self):
        self.assertIn("cfo", rows(contract_dupes())[0])
        self.assertIn("cfo", rows(contract_dupes_by_order())[0])

    def test_группа_из_разных_цфо_показывает_оба(self):
        load(
            "load_contracts",
            contracts_file(
                [
                    contract_row(cfo="431", dogovor="Д-5", zakaz="З-5"),
                    contract_row(cfo="432", dogovor="Д-5", zakaz="З-5"),
                ]
            ),
        )
        группа = rows(contract_dupes())[0]
        self.assertEqual(группа["cfo"], "431, 432")

    def test_фильтры_доходят_до_api(self):
        resp = self.client.get(reverse("api_contract_dupes"), {"cfo": "422"})
        self.assertEqual(resp.status_code, 200)
        данные = json.loads(resp.content)
        self.assertEqual(len(данные), 1)
        self.assertEqual(данные[0]["contract"], "Д-9")

    def test_фильтры_доходят_до_выгрузки(self):
        resp = self.client.get(reverse("export_contract_dupes"), {"cfo": "422"})
        self.assertEqual(resp.status_code, 200)
