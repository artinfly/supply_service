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
    def test_две_строки_договоров_дают_две_записи(self):
        path = contracts_file(
            [contract_row(), contract_row(dogovor="Д-2", zakaz="З-2")]
        )
        load("load_contracts", path)
        self.assertEqual(IgkStatData.objects.count(), 2)

    def test_нулевые_суммы_не_превращаются_в_null(self):
        path = contracts_file([contract_row(plan=0, fakt=0, ostatok=0)])
        load("load_contracts", path)
        row = IgkStatData.objects.get()
        self.assertEqual(row.plan, 0.0)
        self.assertEqual(row.fact, 0.0)
        self.assertEqual(row.remainder, 0.0)

    def test_нулевая_оплата_знп_остаётся_нулём(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row(plan_sum=0, fact_sum=0)]))
        znp = ZnpData.objects.get()
        self.assertEqual(znp.plan_sum, 0.0)
        self.assertEqual(znp.fact_sum, 0.0)

    def test_заявка_знп_привязывается_к_договору(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_znp", znp_file([znp_row()]))
        znp = ZnpData.objects.get()
        self.assertIsNotNone(znp.parent_id)
        self.assertEqual(znp.parent.contract, "Д-1")

    def test_изменение_плана_попадает_в_историю(self):
        load("load_contracts", contracts_file([contract_row(plan=100.0)]))
        self.assertEqual(ContractsHistory.objects.count(), 0)

        load("load_contracts", contracts_file([contract_row(plan=200.0)]))
        change = ContractsHistory.objects.get()
        self.assertEqual(change.old_plan, 100.0)
        self.assertEqual(change.new_plan, 200.0)
        self.assertIsNotNone(change.plan_changed_date)
        self.assertIsNone(change.old_status)

    def test_изменение_статуса_попадает_в_историю(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row(sostoyanie="Исполнен")]))
        change = ContractsHistory.objects.get()
        self.assertEqual(change.old_status, "Исполняется")
        self.assertEqual(change.new_status, "Исполнен")

    def test_повторная_загрузка_без_правок_историю_не_пишет(self):
        load("load_contracts", contracts_file([contract_row()]))
        load("load_contracts", contracts_file([contract_row()]))
        self.assertEqual(IgkStatData.objects.count(), 1)
        self.assertEqual(ContractsHistory.objects.count(), 0)

    def test_загрузка_знп_sap(self):
        load("load_znp_sap", znp_sap_file([znp_sap_row()]))
        self.assertEqual(ZnpDataSAP.objects.count(), 1)

    def test_знп_sap_берёт_только_гоз(self):
        load(
            "load_znp_sap",
            znp_sap_file([znp_sap_row(), znp_sap_row(reg_num="SAP-2", c_type="СП")]),
        )
        self.assertEqual(ZnpDataSAP.objects.count(), 1)

    def test_чужой_файл_отвергается(self):
        with self.assertRaises(CommandError):
            load("load_znp", contracts_file([]))
