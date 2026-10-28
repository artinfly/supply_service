"""Загрузка файлов через страницу «Загрузка данных» и нормализация."""

from datetime import datetime

from django.test import TestCase

from core.models import (
    ContractsAppeared,
    ContractsHistory,
    IgkStatData,
    NsiIgk,
    SystemEvent,
    ZnpData,
    ZnpDataSAP,
)

from .helpers import (
    contract_row,
    contracts_file,
    make_user,
    messages_text,
    upload,
    xlsx_bytes,
    znp_file,
    znp_row,
)


def sap_row(c_type="ГОЗ", igk="000000001111", agent="ООО Ромашка", vv_sum=500):
    """Строка файла SAP: колонки по номерам (ZNP_SAP_COLUMNS)."""
    row = [None] * 34
    row[8], row[10], row[11], row[12] = c_type, "ПД-1", "Подшипники", vv_sum
    row[14], row[18], row[19], row[22] = agent, "4500000001", igk, "421"
    row[24], row[27] = "Банк", datetime(2026, 8, 20)
    row[33] = datetime(2026, 8, 19)
    return row


class ContractsUploadTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("admin", superuser=True))

    def test_first_upload(self):
        response = upload(
            self.client,
            "contracts",
            contracts_file(
                contract_row(),
                contract_row(order="1002", payment="Постоплата", status="Черновик"),
                contract_row(payment="Итого"),  # не аванс и не постоплата — не грузится
            ),
        )
        self.assertIn("Файл успешно загружен и нормализован", messages_text(response))
        self.assertContains(response, "обработано строк: 2, изменений записано: 0")

        position = IgkStatData.objects.get(order="1001")
        self.assertEqual(position.plan_date, "2026.03")
        self.assertEqual(position.c_date, "2026")
        self.assertEqual(position.plan, 1000)
        self.assertEqual(
            list(NsiIgk.objects.values_list("igk", flat=True)), ["000000001111"]
        )
        self.assertTrue(SystemEvent.objects.filter(event_key="contracts_load").exists())
        # Первая загрузка — сравнивать не с чем, журнал «появившихся» пуст
        self.assertFalse(ContractsAppeared.objects.exists())

    def test_second_upload_records_changes(self):
        upload(
            self.client, "contracts", contracts_file(contract_row(status="Черновик"))
        )
        upload(
            self.client,
            "contracts",
            contracts_file(
                contract_row(status="Подписан", plan=1500),
                contract_row(igk="000000002222", order="2001"),
            ),
        )
        history = ContractsHistory.objects.get()
        self.assertEqual(
            (history.old_status, history.new_status), ("Черновик", "Подписан")
        )
        self.assertEqual((history.old_plan, history.new_plan), (1000, 1500))
        self.assertEqual(
            sorted(ContractsAppeared.objects.values_list("reason", "kind")),
            [("новая позиция", "concluded"), ("смена статуса", "concluded")],
        )

    def test_igk_directory_follows_file(self):
        upload(
            self.client,
            "contracts",
            contracts_file(contract_row(), contract_row(igk="000000002222")),
        )
        upload(
            self.client, "contracts", contracts_file(contract_row(igk="000000002222"))
        )
        self.assertEqual(
            list(NsiIgk.objects.values_list("igk", flat=True)), ["000000002222"]
        )

    def test_file_without_positions_keeps_data(self):
        upload(self.client, "contracts", contracts_file(contract_row()))
        with self.assertLogs("core.views.upload", "ERROR"):
            response = upload(
                self.client, "contracts", contracts_file(contract_row(payment="Итого"))
            )
        self.assertIn("данные не изменены", messages_text(response)[0])
        self.assertEqual(IgkStatData.objects.count(), 1)

    def test_wrong_columns(self):
        with self.assertLogs("core.views.upload", "ERROR"):
            response = upload(
                self.client, "contracts", xlsx_bytes([["Номер", "Сумма"], [1, 2]])
            )
        self.assertEqual(
            messages_text(response), ["Ошибка: Документ не соответствует формату"]
        )

    def test_wrong_extension(self):
        response = upload(self.client, "contracts", b"a;b", name="data.csv")
        self.assertIn("Неподдерживаемый формат файла: .csv", messages_text(response)[0])

    def test_unknown_file_type(self):
        response = upload(self.client, "other", contracts_file(contract_row()))
        self.assertEqual(messages_text(response), ["Неизвестный тип файла: other"])


class ZnpUploadTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("admin", superuser=True))
        upload(self.client, "contracts", contracts_file(contract_row()))

    def test_requests_link_to_positions(self):
        response = upload(
            self.client,
            "znp",
            znp_file(znp_row(), znp_row(plan_doc="ПД-2", contract="Д-404")),
        )
        self.assertContains(
            response, "обработано заявок: 2, без совпадения с договором: 1"
        )
        linked = ZnpData.objects.get(plan_doc="ПД-1")
        self.assertEqual(linked.parent, IgkStatData.objects.get())
        self.assertEqual(str(linked.plan_payment_date), "2026-03-20")
        self.assertIsNone(ZnpData.objects.get(plan_doc="ПД-2").parent)

    def test_contracts_reload_keeps_links(self):
        upload(self.client, "znp", znp_file(znp_row()))
        upload(self.client, "contracts", contracts_file(contract_row(plan=2000)))
        self.assertEqual(ZnpData.objects.get().parent, IgkStatData.objects.get())

    def test_file_without_plan_docs_keeps_data(self):
        upload(self.client, "znp", znp_file(znp_row()))
        with self.assertLogs("core.views.upload", "ERROR"):
            response = upload(self.client, "znp", znp_file(znp_row(plan_doc="")))
        self.assertIn("данные не изменены", messages_text(response)[0])
        self.assertEqual(ZnpData.objects.count(), 1)


class SapUploadTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("admin", superuser=True))

    def test_only_goz_requests_are_loaded(self):
        header = ["шапка"] * 34
        response = upload(
            self.client,
            "znp_sap",
            xlsx_bytes(
                [header, sap_row(), sap_row(c_type="НЕ ГОЗ"), sap_row(igk=None)]
            ),
        )
        self.assertContains(response, "обработано заявок: 2, без ИГК: 1")
        self.assertEqual(ZnpDataSAP.objects.count(), 2)
        self.assertTrue(SystemEvent.objects.filter(event_key="sap_load").exists())

    def test_file_without_goz_keeps_data(self):
        header = ["шапка"] * 34
        upload(self.client, "znp_sap", xlsx_bytes([header, sap_row()]))
        with self.assertLogs("core.views.upload", "ERROR"):
            response = upload(
                self.client, "znp_sap", xlsx_bytes([header, sap_row(c_type="НЕ ГОЗ")])
            )
        self.assertIn("нет заявок с типом «ГОЗ»", messages_text(response)[0])
        self.assertEqual(ZnpDataSAP.objects.count(), 1)
