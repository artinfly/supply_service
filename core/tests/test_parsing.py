"""Разбор значений из файлов: числа, даты, ключи ГК, заголовки колонок."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from core.services.goz.analysis import _contract_label
from core.services.goz.gk_key import gk_key, key_from_contract, parse_gk_key
from core.services.importing.excel_import import clean_header
from core.services.importing.linking import contract_hash
from core.services.importing.normalize import (
    parse_date,
    plan_month,
    status_group,
    to_decimal,
    values_equal,
    year_flags,
)


class NumbersAndDatesTests(SimpleTestCase):
    def test_to_decimal(self):
        self.assertEqual(to_decimal("1 234,50"), Decimal("1234.50"))
        self.assertEqual(to_decimal("1\xa0000"), Decimal("1000"))
        self.assertEqual(to_decimal(15), Decimal("15"))
        for empty in (None, "", "-", "None", "abc"):
            self.assertIsNone(to_decimal(empty))

    def test_values_equal_to_kopecks(self):
        self.assertTrue(values_equal("100.001", 100))
        self.assertTrue(values_equal(None, ""))
        self.assertFalse(values_equal("100.01", 100))
        self.assertFalse(values_equal(None, 0))

    def test_plan_month(self):
        self.assertEqual(plan_month("15.03.2026"), "2026.03")
        self.assertEqual(plan_month("5.3.2026"), "2026.03")
        self.assertEqual(plan_month("2026.3"), "2026.03")
        self.assertEqual(plan_month("2026-03-15 00:00:00"), "2026.03")
        self.assertIsNone(plan_month(""))
        self.assertIsNone(plan_month("март"))

    def test_year_flags(self):
        self.assertEqual(year_flags("2026"), (False, True, False))
        self.assertEqual(year_flags(" 2025 г."), (True, False, False))
        self.assertEqual(year_flags(None), (False, False, False))

    def test_parse_date(self):
        self.assertEqual(parse_date("15.03.2026"), date(2026, 3, 15))
        self.assertEqual(parse_date("2026-03-15 10:00"), date(2026, 3, 15))
        self.assertEqual(parse_date("15 марта 2026 г."), date(2026, 3, 15))
        self.assertIsNone(parse_date("31.02.2026"))
        self.assertIsNone(parse_date("когда-нибудь"))

    def test_status_group(self):
        self.assertEqual(status_group("Подписан"), "concluded")
        self.assertEqual(status_group("Черновик"), "not_concluded")
        self.assertIsNone(status_group("Расторгнут"))


class ImportHelpersTests(SimpleTestCase):
    def test_clean_header_ignores_case_spaces_and_symbols(self):
        self.assertEqual(
            clean_header(" Сумма  руб\nоплаты "), clean_header("сумма руб оплаты")
        )
        self.assertEqual(
            clean_header("ДокументПланирования.Номер"), "документпланированияномер"
        )
        self.assertEqual(clean_header(None), "")

    def test_contract_hash(self):
        a = contract_hash("0001111", "ООО А", "Д-1", "Этап 1")
        self.assertEqual(a, contract_hash("0001111", "ООО А", "Д-1", "Этап 1"))
        self.assertEqual(
            contract_hash(None, "", None, ""), contract_hash("", "", "", "")
        )
        self.assertNotEqual(a, contract_hash("0001111", "ООО А", "Д-1", "Этап 2"))


class GkKeyTests(SimpleTestCase):
    """Таблица ключей из описания core/services/goz/gk_key.py."""

    def test_file_labels(self):
        cases = {
            "1493": "1493",
            "6766_12": "6766 12",
            "0087_334сб_137": "0087/334сб",
            "0276_481сб_137_138": "0276/481сб 138",
            "0998_439сб_19": "0998/439сб 19",
            "0262_137": "0262 137",  # без «сб» 137 — номер спецификации
            "0624_624_379сб_137": "0624/379сб",
        }
        for label, key in cases.items():
            with self.subTest(label=label):
                self.assertEqual(parse_gk_key(label), key)

    def test_long_label_kept_whole(self):
        self.assertEqual(gk_key("4238_3_3_6_30-2014-ДГОЗ"), "4238_3_3_6_30-2014-ДГОЗ")

    def test_contract_strings(self):
        cases = {
            "0123451493/137 от 01.02.2024": "1493",
            "0123456766/12 от 01.02.2024": "6766 12",
            "0123450087/334сб/137 от 01.02.2024": "0087/334сб",
            "0123450276/481сб/137 от 01.02.2024, спец/138": "0276/481сб 138",
            "0123450262/255сб/137 от 01.02.2024, спец/137": "0262/255сб 137",
        }
        for text, key in cases.items():
            with self.subTest(text=text):
                self.assertEqual(key_from_contract(text), key)
                self.assertEqual(parse_gk_key(text), key)

    def test_ready_key_and_garbage(self):
        self.assertEqual(parse_gk_key("1493/34сб 5"), "1493/34сб 5")
        self.assertIsNone(parse_gk_key("  "))
        self.assertEqual(gk_key("без номера"), "без номера")

    def test_archive_file_names(self):
        self.assertEqual(_contract_label("№ 12345671234_5.xls"), "1234 5")
        self.assertEqual(_contract_label("№0001230087_334сб_137.xls"), "0087/334сб")
        self.assertEqual(_contract_label("ИГК 6066.xls"), "6066")
