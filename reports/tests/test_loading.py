"""
Тесты загрузки данных из Excel-файлов.

Проверяют:
- Импорт договоров, заявок ФЗД и заявок SAP
- Обработку нулевых сумм (не превращаются в NULL)
- Привязку заявок ФЗД к позициям договоров
- Запись изменений в историю (план, статус)
- Повторную загрузку без изменений (история не пишется)
- Отклонение файлов не по формату
"""

from django.core.management.base import CommandError
from django.test import TestCase

from reports.models import ContractsHistory, IgkStatData, ZnpData, ZnpDataSAP

from .factories import (
    contract_row,
    contracts_file,
    load,
    znp_file,
    znp_row,
    znp_sap_file,
    znp_sap_row,
)


class LoadTests(TestCase):
    """Проверки загрузки данных из Excel-файлов."""

    # ------------------------------------------------------------------
    # Импорт договоров
    # ------------------------------------------------------------------

    def test_две_строки_договоров_дают_две_записи(self):
        """Каждая строка файла становится отдельной записью в базе."""
        path = contracts_file(
            [contract_row(), contract_row(dogovor="Д-2", zakaz="З-2")]
        )
        load("load_contracts", path)
        self.assertEqual(IgkStatData.objects.count(), 2)

    def test_нулевые_суммы_не_превращаются_в_null(self):
        """Нулевые суммы сохраняются как 0.0, а не как NULL."""
        path = contracts_file([contract_row(plan=0, fakt=0, ostatok=0)])
        load("load_contracts", path)
        row = IgkStatData.objects.get()
        self.assertEqual(row.plan, 0.0)
        self.assertEqual(row.fact, 0.0)
        self.assertEqual(row.remainder, 0.0)

    # ------------------------------------------------------------------
    # Импорт заявок ФЗД
    # ------------------------------------------------------------------

    def test_нулевая_оплата_знп_остаётся_нулём(self):
        """Нулевые суммы в заявке сохраняются как 0.0."""
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row(plan_sum=0, fact_sum=0)]))
        znp = ZnpData.objects.get()
        self.assertEqual(znp.plan_sum, 0.0)
        self.assertEqual(znp.fact_sum, 0.0)

    def test_заявка_знп_привязывается_к_договору(self):
        """
        Заявка привязывается к позиции договора по хешу.

        Если ИГК, контрагент, договор и этап совпадают,
        заявка получает parent и попадает на страницы.
        """
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row()]))
        znp = ZnpData.objects.get()
        self.assertIsNotNone(znp.parent_id)
        self.assertEqual(znp.parent.contract, "Д-1")

    # ------------------------------------------------------------------
    # История изменений
    # ------------------------------------------------------------------

    def test_изменение_плана_попадает_в_историю(self):
        """
        При изменении плана создаётся запись в истории.

        Проверяются:
        - старое и новое значения плана
        - дата изменения плана
        - статус не меняется (поля статуса пустые)
        """
        load("load_contracts", contracts_file([contract_row(plan=100.0)]))
        self.assertEqual(ContractsHistory.objects.count(), 0)

        load("load_contracts", contracts_file([contract_row(plan=200.0)]))
        change = ContractsHistory.objects.get()
        self.assertEqual(change.old_plan, 100.0)
        self.assertEqual(change.new_plan, 200.0)
        self.assertIsNotNone(change.plan_changed_date)
        self.assertIsNone(change.old_status)

    def test_изменение_статуса_попадает_в_историю(self):
        """При изменении статуса создаётся запись в истории."""
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполнен")]))
        change = ContractsHistory.objects.get()
        self.assertEqual(change.old_status, "Исполняется")
        self.assertEqual(change.new_status, "Исполнен")

    def test_повторная_загрузка_без_правок_историю_не_пишет(self):
        """
        Повторная загрузка того же файла не создаёт записей в истории.

        История пишется только при изменении данных.
        """
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row()]))
        self.assertEqual(IgkStatData.objects.count(), 1)
        self.assertEqual(ContractsHistory.objects.count(), 0)

    # ------------------------------------------------------------------
    # Импорт заявок SAP
    # ------------------------------------------------------------------

    def test_загрузка_знп_sap(self):
        """Базовая загрузка заявок SAP."""
        load("load_znp_sap", znp_sap_file([znp_sap_row()]))
        self.assertEqual(ZnpDataSAP.objects.count(), 1)

    def test_знп_sap_берёт_только_гоз(self):
        """
        Из заявок SAP загружаются только ГОЗ (государственный оборонный заказ).

        Заявки с типом «СП» (собственные средства) отфильтровываются.
        """
        load(
            "load_znp_sap",
            znp_sap_file([znp_sap_row(), znp_sap_row(reg_num="SAP-2", c_type="СП")]),
        )
        self.assertEqual(ZnpDataSAP.objects.count(), 1)

    # ------------------------------------------------------------------
    # Обработка ошибок
    # ------------------------------------------------------------------

    def test_чужой_файл_отвергается(self):
        """Файл не по формату отклоняется с ошибкой."""
        with self.assertRaises(CommandError):
            load("load_znp", contracts_file([]))
