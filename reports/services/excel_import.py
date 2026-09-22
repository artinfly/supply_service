"""
Модуль импорта данных из Excel-файлов в staging-таблицы.

Читает файлы .xlsx/.xls, находит заголовки колонок и загружает
сырые данные во временные таблицы без конвертации типов.
Конвертация и нормализация выполняется в services/normalize.py.
"""

import os
import re
from contextlib import contextmanager

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
    "payment_possible": 31,
    "init_payment_date": 26,
    "c_type": 8,
    "normalize_doc_num": 10,
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
