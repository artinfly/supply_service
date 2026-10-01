"""
Модуль импорта данных из Excel-файлов в staging-таблицы.

Читает файлы .xlsx/.xls, находит заголовки колонок и загружает
сырые данные во временные таблицы без конвертации типов.
Конвертация и нормализация выполняется в services/normalize.py.
"""

import os
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl
import xlrd
from django.core.management.base import CommandError
from django.db import connection, transaction

from .linking import contract_hash

# --- Маппинги колонок Excel на поля БД ---

# Договоры: имя колонки в Excel -> поле в staging_excel
CONTRACT_COLUMNS = {
    "ИГК": "igk",
    "Контрагент": "kontragent",
    "ЦФО": "cfo",
    "Договор": "dogovor",
    "Состояние": "sostoyanie",
    "Тип платежа": "tip_platezha",
    "Предмет": "predmet",
    "Заказ": "zakaz",
    "ПЛАН": "plan",
    "ФАКТ": "fakt",
    "Остаток": "ostatok",
    "Тол": "tol",
    "Этап графика": "etap_grafika",
    "ДатаПланПодп": "dataplan",
    "СУММА договора": "summa_dogovora",
    "ГодИГК": "god_igk",
}

# Заявки ФЗД: имя колонки в Excel -> поле в staging_znp_excel
ZNP_COLUMNS = {
    "ИГК договора": "igk",
    "ИГК заявки": "znp_igk",
    "Контрагент": "c_agent",
    "ДокументПланирования.Номер": "plan_doc",
    "Этап": "stage",
    "Назначение платежа": "payment_purpose",
    "Договор": "contract",
    "Прогнозная дата оплаты": "plan_payment_date",
    "Фактическая дата оплаты": "fact_payment_date",
    "Сумма руб планирования": "plan_sum",
    "Сумма руб оплаты": "fact_sum",
    "ТипПлатежа": "znp_payment_type",
    "Статус": "znp_status",
    "Дата": "znp_date",
}

# Заявки SAP: поле в БД -> фиксированный индекс колонки в Excel
# Формат файла SAP стабилен, поэтому используются индексы вместо имён
ZNP_SAP_COLUMNS = {
    "igk": 19,
    "cfo": 22,
    "c_agent": 14,
    "reg_num": 18,
    "items": 11,
    "vv_sum": 12,
    "bank_name": 24,
    "stage_e": 29,
    "stage_f": 30,
    "stage_c": 27,
    "payment_possible": 31,
    "c_type": 8,
    "normalize_doc_num": 10,
    "created_date": 33,
}

BAD_FORMAT = "Документ не соответствует формату"


# --- Чтение Excel-файлов ---


def _xlsx_rows(filepath):
    """Открывает .xlsx и возвращает (итератор строк, функция закрытия)."""
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    return wb.active.iter_rows(values_only=True), wb.close


def _xls_rows(filepath):
    """Открывает .xls и возвращает (итератор строк, функция освобождения ресурсов)."""
    book = xlrd.open_workbook(filepath)
    sheet = book.sheet_by_index(0)

    def _iter():
        for i in range(sheet.nrows):
            yield tuple(v if v != "" else None for v in sheet.row_values(i))

    return _iter(), book.release_resources


@contextmanager
def _sheet(filepath):
    """Контекстный менеджер для открытия Excel-файла (.xlsx или .xls)."""
    ext = os.path.splitext(filepath)[1].lower()
    loader = _xls_rows if ext == ".xls" else _xlsx_rows
    try:
        rows, close = loader(filepath)
    except FileNotFoundError:
        raise CommandError(f"Файл не найден: {filepath}")
    except Exception as exc:
        raise CommandError(str(exc))
    try:
        yield rows
    finally:
        rows.close()
        close()


# --- Обработка заголовков и строк ---


def clean_header(text):
    """Нормализует заголовок колонки для гибкого поиска."""
    if not text:
        return ""
    text = str(text)
    text = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9\s/*()«»\'\-\_]", "", text)
    text = re.sub(r"\s+", "", text).strip()
    return text.casefold()


def _find_columns(rows, column_map):
    """
    Ищет строку заголовков и определяет позиции нужных колонок.
    Возвращает словарь {индекс: поле}. При неполных данных — CommandError.
    """
    lookup = {clean_header(name): field for name, field in column_map.items()}
    known = set(lookup)
    header = next((r for r in rows if known & {clean_header(c) for c in r if c}), None)
    if header is None:
        raise CommandError(BAD_FORMAT)
    positions = {
        i: lookup[clean_header(cell)]
        for i, cell in enumerate(header)
        if cell and clean_header(cell) in lookup
    }
    if set(column_map.values()) - set(positions.values()):
        raise CommandError(BAD_FORMAT)
    return positions


def _read_row(row, positions, fields, empty_as_null=False):
    """Читает строку по маппингу {индекс: поле} и возвращает словарь значений."""
    record = dict.fromkeys(fields)
    for idx, field in positions.items():
        if idx < len(row) and row[idx] is not None:
            value = str(row[idx]).strip()
            record[field] = None if empty_as_null and value == "" else value
    return record


def _is_blank(record, field):
    """Проверяет, является ли значение поля пустым."""
    value = record.get(field)
    return value is None or str(value).strip() == ""


# --- Загрузка данных в staging-таблицы ---


def _replace_table(table, fields, data):
    """Полностью заменяет staging-таблицу новыми данными (TRUNCATE + INSERT)."""
    insert_sql = (
        f"INSERT INTO {table} ({', '.join(fields)}) "
        f"VALUES ({', '.join(['%s'] * len(fields))})"
    )
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"TRUNCATE {table} RESTART IDENTITY")
        if data:
            cur.executemany(insert_sql, data)


def import_contracts(filepath):
    """Импортирует файл договоров в staging_excel. Возвращает число строк."""
    fields = list(CONTRACT_COLUMNS.values())
    with _sheet(filepath) as rows:
        positions = _find_columns(rows, CONTRACT_COLUMNS)
        data = [
            tuple(_read_row(row, positions, fields)[f] for f in fields)
            for row in rows
            if any(row)
        ]
    _replace_table("staging_excel", fields, data)
    return len(data)


def import_znp(filepath):
    """
    Импортирует файл заявок ФЗД в staging_znp_excel.
    Вычисляет crc32_hash для привязки к договорам. Возвращает число строк.
    """
    fields = list(ZNP_COLUMNS.values()) + ["crc32_hash"]
    with _sheet(filepath) as rows:
        positions = _find_columns(rows, ZNP_COLUMNS)
        data = []
        for row in rows:
            if not any(row):
                continue
            record = _read_row(row, positions, fields)
            if _is_blank(record, "plan_doc"):
                continue
            record["crc32_hash"] = contract_hash(
                record["igk"], record["c_agent"], record["contract"], record["stage"]
            )
            data.append(tuple(record[f] for f in fields))
    _replace_table("staging_znp_excel", fields, data)
    return len(data)


def import_znp_sap(filepath):
    """
    Импортирует файл заявок SAP в staging_znp_sap_excel.
    Использует фиксированные индексы колонок. Возвращает число строк.
    """
    fields = list(ZNP_SAP_COLUMNS.keys())
    positions = {idx: field for field, idx in ZNP_SAP_COLUMNS.items()}
    with _sheet(filepath) as rows:
        next(rows, None)  # Пропускаем строку заголовка
        data = []
        for row in rows:
            if not any(row):
                continue
            record = _read_row(row, positions, fields, empty_as_null=True)
            if _is_blank(record, "c_agent"):
                continue
            data.append(tuple(record[f] for f in fields))
    _replace_table("staging_znp_sap_excel", fields, data)
    return len(data)


# --- Конвертация значений для Краткой справки ---


def _sum_to_decimal(val):
    """Конвертирует значение суммы в Decimal. Пустое/ошибка -> None."""
    if val is None:
        return None
    try:
        s = str(val).replace(" ", "").replace(",", ".").replace("\xa0", "")
        if s in ("", "-", "None"):
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _percent_to_decimal(val):
    """Конвертирует процент в Decimal (убирает % и пробелы)."""
    if val is None:
        return None
    try:
        s = str(val).replace("%", "").replace(" ", "").replace(",", ".")
        if s in ("", "-", "None"):
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _date_to_date(val):
    """Конвертирует значение даты в date. Поддерживает datetime и строки."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _int_or_zero(val):
    """Конвертирует значение в int. Пустое/ошибка -> 0."""
    if val is None:
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def import_sum_report(filepath):
    """
    Импортирует файл Краткой справки в staging_sum_excel.
    Читает все листы. Имя листа = ИГК. Данные парсятся по позициям колонок.
    Флаг is_cycle определяется по значению 7-й колонки, если в источнике она содержит булев признак.
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)

    fields = [
        "igk",
        "is_cycle",
        "dep",
        "counteragent",
        "inn",
        "contract",
        "status",
        "stage",
        "item",
        "order_doc",
        "contract_sum",
        "plan_avans",
        "percent_doc",
        "fact_paid",
        "note",
        "completed_sum",
        "znp_count",
        "sum_80",
        "paid_from_znp",
        "remains_pay",
        "sum_avans",
        "sum_issued_znp",
        "period_reg_date",
        "plan_date_contract",
    ]

    data = []
    try:
        for sheet_name in wb.sheetnames:
            if not sheet_name.strip() or sheet_name.strip().casefold() == "свод (2)":
                continue

            ws = wb[sheet_name]
            curr_row_orig = 3

            # Читаем все строки листа в список для доступа по индексам
            all_rows = list(ws.iter_rows(min_row=1, values_only=True))

            while curr_row_orig <= len(all_rows):
                row = all_rows[curr_row_orig - 1]  # 1-based -> 0-based
                if not row or not any(row):
                    curr_row_orig += 1
                    continue

                first_col_val = str(row[0] or "").strip()
                counteragent_val = str(row[1] or "").strip()

                # Проверка выхода: "Общий итог" или "Всего" в 1-й или 2-й колонке
                lower_first = first_col_val.lower()
                lower_second = counteragent_val.lower()
                if (
                    "общий итог" in lower_first
                    or "общий итог" in lower_second
                    or "всего" in lower_first
                    or "всего" in lower_second
                ):
                    break

                # Проверка пропуска: "итого: 42" или "в том числе"
                if (
                    "итого: 42" in lower_first
                    or "итого: 42" in lower_second
                    or "в том числе" in lower_first
                    or "в том числе" in lower_second
                ):
                    curr_row_orig += 1
                    continue

                # Извлекаем значения по позициям (1-based -> 0-based)
                def cell(idx):
                    """Возвращает значение ячейки по 1-базовому индексу колонки."""
                    return row[idx - 1] if idx <= len(row) else None

                dep = str(cell(4) or "").strip()
                condition = str(cell(6) or "").strip()
                stage_val = str(cell(7) or "").strip()

                # В исходной SumReportWCycle 7-я колонка содержит отдельный булев признак.
                # В текущей Краткой справке 7-я колонка — «Этап графика», поэтому обычные
                # значения этапов не должны ошибочно превращать строки в длинноцикловые.
                raw_cycle = cell(7)
                if isinstance(raw_cycle, bool):
                    is_cycle = raw_cycle
                else:
                    is_cycle = str(raw_cycle or "").strip().casefold() in ("да", "1", "true", "yes", "д")

                record = {
                    "igk": sheet_name,
                    "is_cycle": is_cycle,
                    "dep": dep,
                    "counteragent": str(cell(2) or "").strip(),
                    "inn": str(cell(3) or "").strip(),
                    "contract": str(cell(5) or "").strip(),
                    "status": condition,
                    "stage": stage_val,
                    "item": str(cell(8) or "").strip(),
                    "order_doc": str(cell(9) or "").strip(),
                    "contract_sum": _sum_to_decimal(cell(10)),
                    "plan_avans": _sum_to_decimal(cell(11)),
                    "percent_doc": _percent_to_decimal(cell(12)),
                    "fact_paid": _sum_to_decimal(cell(14)),
                    "note": str(cell(20) or "").replace("\n", " ").strip(),
                    "completed_sum": _sum_to_decimal(cell(26)),
                    "znp_count": _int_or_zero(cell(27)),
                    "sum_80": _sum_to_decimal(cell(28)),
                    "paid_from_znp": _sum_to_decimal(cell(29)),
                    "remains_pay": _sum_to_decimal(cell(24)),
                    "sum_avans": _sum_to_decimal(cell(33)),
                    "sum_issued_znp": _sum_to_decimal(cell(32)),
                    "period_reg_date": _date_to_date(cell(18)),
                    "plan_date_contract": _date_to_date(cell(21)),
                }
                data.append(tuple(record[f] for f in fields))
                curr_row_orig += 1
    finally:
        wb.close()

    _replace_table("staging_sum_excel", fields, data)
    return len(data)
