from io import BytesIO
from tempfile import NamedTemporaryFile

from django.test import TestCase
from openpyxl import Workbook, load_workbook

from reports.models import StagingSumExcel
from reports.services.excel_import import import_sum_report
from reports.services.sum_report import _generate_single_report, _sql_table1


class SumReportImportTests(TestCase):
    def _workbook(self, explicit_cycle=False):
        wb = Workbook()
        ws = wb.active
        ws.title = "1123"
        ws["B1"] = "ИГК 2224187315101412241211123"
        headers = [
            "ИГК", "Контрагент", "ИНН", "ЦФО", "Договор", "Состояние",
            "Этап графика", "Предмет", "Заказ", "СУММА договора",
            "ПЛАН аванса по договору (по условию)", "%", "Планируемая сумма аванса 40%",
            "ФАКТ ОПЛАТЫ АВАНСА", "Остаток аванса", "Остаток аванса 40%",
            "Резерв", "Срок оформления ЗнП на аванс", "Фактическая дата оформления ЗНП",
            "Примечание", "Планируемая дата заключения договора",
            "Фактическая дата заключения договора", "Оплачено в %",
            "Осталось доплатить авансов", "Стадия оформления ЗнП",
            "Сумма оформленных ЗНП", "Кол-во сданных ЗНП", "сумма 80% по договору",
            "Оплачено из сданных ЗНП", "Дата оплаты", "", "Сумма оформленных/не оформленных ЗнП",
            "Сумма оформленных и не оплаченных ЗнП",
        ]
        if explicit_cycle:
            headers.append("Цикл")
        ws.append([""] * len(headers))
        ws.append(headers)
        row = [
            "1123", "ООО Тест", "7700000000", "426", "Д-1", "Заключен",
            "№1. Аванс", "Изделие", "З-1", 10000000, 8000000, 0.8,
            4000000, 4000000, 4000000, 0, 0, None, None, "тест",
            None, None, 1, 0, None, 0, 1, 8000000, 4000000, None, None, 0, 0,
        ]
        if explicit_cycle:
            row.append(True)
        ws.append(row)
        return wb

    def test_current_format_without_cycle_column_loads_as_long_cycle(self):
        wb = self._workbook(explicit_cycle=False)
        with NamedTemporaryFile(suffix=".xlsx") as f:
            wb.save(f.name)
            loaded = import_sum_report(f.name)

        self.assertEqual(loaded, 1)
        obj = StagingSumExcel.objects.get()
        self.assertTrue(obj.is_cycle)
        self.assertEqual(obj.dep, "426")
        self.assertEqual(obj.percent_doc, 0.8)

    def test_explicit_cycle_column_is_respected(self):
        wb = self._workbook(explicit_cycle=True)
        wb["1123"]["AH3"] = False
        with NamedTemporaryFile(suffix=".xlsx") as f:
            wb.save(f.name)
            import_sum_report(f.name)

        self.assertFalse(StagingSumExcel.objects.get().is_cycle)

    def test_table1_sql_has_nine_parameters(self):
        sql = _sql_table1("1123", False)
        self.assertEqual(sql.count("%s"), 9)

    def test_report_generation_does_not_require_missing_template(self):
        StagingSumExcel.objects.create(
            igk="1123", is_cycle=True, dep="426", counteragent="ООО Тест",
            inn="7700000000", contract="Д-1", status="Заключен",
            stage="№1. Аванс", item="Изделие", order_doc="З-1",
            contract_sum=10000000, plan_avans=8000000, percent_doc=0.8,
            fact_paid=4000000, completed_sum=0, znp_count=1,
            sum_80=8000000, paid_from_znp=4000000, remains_pay=0,
            sum_avans=0, sum_issued_znp=0,
        )
        data = _generate_single_report("1123", False)
        wb = load_workbook(BytesIO(data), data_only=True)
        self.assertEqual(wb.sheetnames, ["1123"])
        self.assertEqual(wb["1123"]["A2"].value, "1123")
