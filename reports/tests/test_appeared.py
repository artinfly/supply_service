"""
Тесты журнала появившихся договоров и фильтров дубликатов.

Проверяют:
- Логику заполнения журнала при загрузке договоров
- Выгрузки «Новые заключённые» и «Новые незаключённые»
- Фильтры дубликатов по ЦФО и году (в SQL и в API/выгрузках)
"""

import json

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from reports.models import ContractsAppeared
from reports.services.queries import contract_dupes, contract_dupes_by_order

from .factories import contract_row, contracts_file, load


def rows(sql_and_params):
    """
    Выполняет SQL-запрос и возвращает результат как список словарей.

    Вспомогательная функция для тестов: упрощает доступ к полям
    по именам колонок вместо индексов.
    """
    sql, params = sql_and_params
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ============================================================================
# Журнал появившихся договоров
# ============================================================================


class AppearedTests(TestCase):
    """Проверки логики заполнения журнала появившихся договоров."""

    def test_первая_загрузка_журнал_не_заполняет(self):
        """При первой загрузке нет предыдущих данных для сравнения."""
        load("load_contracts", contracts_file([contract_row()]))
        self.assertEqual(ContractsAppeared.objects.count(), 0)

    def test_новая_позиция_попадает_как_заключённая(self):
        """
        Новая позиция договора (которой не было в прошлой загрузке)
        попадает в журнал как «новая позиция» с видом «заключённая».
        """
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
        """
        Смена статуса с незаключённого на заключённый
        попадает в журнал как «смена статуса».
        """
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполняется")]))
        появилось = ContractsAppeared.objects.get(kind="concluded")
        self.assertEqual(появилось.reason, "смена статуса")
        self.assertEqual(появилось.status, "Исполняется")

    def test_смена_статуса_на_незаключённый(self):
        """
        Смена статуса с заключённого на незаключённый
        попадает в журнал как «смена статуса».
        """
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполняется")]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        появилось = ContractsAppeared.objects.get(kind="not_concluded")
        self.assertEqual(появилось.reason, "смена статуса")

    def test_повторная_загрузка_ничего_не_добавляет(self):
        """Повторная загрузка того же файла не создаёт записей в журнале."""
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row()]))
        self.assertEqual(ContractsAppeared.objects.count(), 0)

    def test_расторгнутые_в_журнал_не_идут(self):
        """Расторгнутые договоры не попадают в журнал появившихся."""
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Расторгнут")]))
        self.assertEqual(ContractsAppeared.objects.count(), 0)

    def test_журнал_накапливается_между_загрузками(self):
        """
        Записи в журнале накапливаются от загрузки к загрузке.

        Сначала статус меняется на незаключённый, потом обратно на заключённый —
        оба события записываются в журнал.
        """
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполняется")]))
        self.assertEqual(ContractsAppeared.objects.count(), 2)
        self.assertEqual(
            sorted(ContractsAppeared.objects.values_list("kind", flat=True)),
            ["concluded", "not_concluded"],
        )


# ============================================================================
# Выгрузки журнала и дубликатов
# ============================================================================


class AppearedExportTests(TestCase):
    """Проверки выгрузок «Новые заключённые/незаключённые» и дубликатов."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("app_boss", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_обе_выгрузки_отдают_файл(self):
        """Обе выгрузки появившихся договоров возвращают 200 и xlsx."""
        # Создаём событие в журнале: статус меняется на незаключённый
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Черновик")]))
        for name in ("export_appeared_concluded", "export_appeared_not_concluded"):
            with self.subTest(выгрузка=name):
                resp = self.client.get(reverse(name))
                self.assertEqual(resp.status_code, 200)
                self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_выгрузка_дублей_по_заказу_отдаёт_файл(self):
        """Выгрузка дубликатов по заказу возвращает 200 и xlsx."""
        load("load_contracts", contracts_file([contract_row(), contract_row()]))
        resp = self.client.get(reverse("export_contract_dupes_by_order"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])


# ============================================================================
# Фильтры дубликатов
# ============================================================================


class DupeFilterTests(TestCase):
    """
    Проверки фильтров дубликатов по ЦФО и году.

    Данные: три группы дублей в разных ЦФО и годах.
    - 421: две одинаковые строки (без года)
    - 422: две одинаковые строки (без года)
    - 423: две одинаковые строки (год 2025)
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("dupe_boss", password="x")

    def setUp(self):
        self.client.force_login(self.user)
        # Загружаем три группы дублей в разных ЦФО
        load(
            "load_contracts",
            contracts_file(
                [
                    contract_row(cfo="421"),
                    contract_row(cfo="421"),
                    contract_row(cfo="422", dogovor="Д-9", zakaz="З-9"),
                    contract_row(cfo="422", dogovor="Д-9", zakaz="З-9"),
                    contract_row(cfo="423", dogovor="Д-7", zakaz="З-7", god_igk="2025"),
                    contract_row(cfo="423", dogovor="Д-7", zakaz="З-7", god_igk="2025"),
                ]
            ),
        )

    # ------------------------------------------------------------------
    # Базовые проверки
    # ------------------------------------------------------------------

    def test_без_фильтра_видны_все_группы(self):
        """Без фильтров видны все три группы дублей."""
        self.assertEqual(len(rows(contract_dupes())), 3)

    def test_колонка_цфо_есть_в_обоих_запросах(self):
        """Колонка cfo присутствует в обоих запросах дубликатов."""
        self.assertIn("cfo", rows(contract_dupes())[0])
        self.assertIn("cfo", rows(contract_dupes_by_order())[0])

    # ------------------------------------------------------------------
    # Фильтр по ЦФО
    # ------------------------------------------------------------------

    def test_фильтр_цфо_оставляет_свою_группу(self):
        """Фильтр по ЦФО показывает только дубли этого ЦФО."""
        отобрано = rows(contract_dupes("422", ""))
        self.assertEqual(len(отобрано), 1)
        self.assertEqual(отобрано[0]["contract"], "Д-9")

    def test_фильтр_цфо_работает_для_дублей_по_заказу(self):
        """Фильтр по ЦФО работает и для дубликатов по заказу."""
        отобрано = rows(contract_dupes_by_order("422", ""))
        self.assertEqual(len(отобрано), 1)
        self.assertEqual(отобрано[0]["order"], "З-9")

    # ------------------------------------------------------------------
    # Фильтр по году
    # ------------------------------------------------------------------

    def test_фильтр_года_работает_для_дублей_по_заказу(self):
        """Фильтр по году работает для дубликатов по заказу."""
        отобрано = rows(contract_dupes_by_order("", "2025"))
        self.assertEqual(len(отобрано), 1)
        self.assertEqual(отобрано[0]["order"], "З-7")

    def test_фильтр_года_работает(self):
        """Фильтр по году работает для полных дублей."""
        отобрано = rows(contract_dupes("", "2025"))
        self.assertEqual(len(отобрано), 1)
        self.assertEqual(отобрано[0]["contract"], "Д-7")

    # ------------------------------------------------------------------
    # Специальные случаи
    # ------------------------------------------------------------------

    def test_группа_из_разных_цфо_показывает_оба(self):
        """
        Если дубли имеют разные ЦФО, в колонке cfo они перечисляются
        через запятую (например: "431, 432").
        """
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

    # ------------------------------------------------------------------
    # Фильтры в API и выгрузках
    # ------------------------------------------------------------------

    def test_фильтры_доходят_до_api(self):
        """Фильтр по ЦФО передаётся через API и применяется в запросе."""
        resp = self.client.get(reverse("api_contract_dupes"), {"cfo": "422"})
        self.assertEqual(resp.status_code, 200)
        данные = json.loads(resp.content)
        self.assertEqual(len(данные), 1)
        self.assertEqual(данные[0]["contract"], "Д-9")

    def test_фильтры_доходят_до_выгрузки(self):
        """Фильтр по ЦФО передаётся в выгрузку и запрос возвращает 200."""
        resp = self.client.get(reverse("export_contract_dupes"), {"cfo": "422"})
        self.assertEqual(resp.status_code, 200)
