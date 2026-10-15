"""Импорт данных из Excel-файлов в staging-таблицы."""

import os
import re
from contextlib import contextmanager

import openpyxl
import xlrd
from django.core.management.base import CommandError
from django.db import connection, transaction

from .linking import contract_hash

# --- Маппинги колонок Excel → поля БД ---


# Договоры: заголовок → поле (порядок колонок не важен)
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

# Заявки ФЗД: заголовок → поле
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

# Заявки SAP: поле → индекс колонки (нумерация с 0, шапка пропускается)
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
    """Открывает .xlsx в режиме read-only. Возвращает (итератор строк, функция закрытия)."""
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    return wb.active.iter_rows(values_only=True), wb.close


def _xls_value(cell, datemode):
    """Значение ячейки .xls в том же виде, в каком его отдаёт openpyxl для .xlsx.

    xlrd хранит даты числом (45678.0), а любые числа — как float (421 -> 421.0).
    Без приведения в базу попадали «45678.0» вместо даты и «421.0» вместо ЦФО 421.
    """
    if cell.ctype == xlrd.XL_CELL_EMPTY or cell.value == "":
        return None
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode)
        except (ValueError, OverflowError, xlrd.xldate.XLDateError):
            return cell.value
    if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
        return int(cell.value)
    return cell.value


def _xls_rows(filepath):
    """Открывает .xls через xlrd. Возвращает (итератор строк, функция закрытия)."""
    book = xlrd.open_workbook(filepath)
    sheet = book.sheet_by_index(0)

    def _iter():
        for i in range(sheet.nrows):
            yield tuple(_xls_value(c, book.datemode) for c in sheet.row(i))

    return _iter(), book.release_resources


@contextmanager
def _sheet(filepath):
    """Контекстный менеджер для безопасного чтения Excel-файлов."""
    ext = os.path.splitext(filepath)[1].lower()
    loader = _xls_rows if ext == ".xls" else _xlsx_rows

    try:
        rows, close = loader(filepath)
    except FileNotFoundError as exc:
        raise CommandError(f"Файл не найден: {filepath}") from exc
    except Exception as exc:
        # Битый или не Excel-файл: текст исключения показывается пользователю
        raise CommandError(str(exc)) from exc

    try:
        yield rows
    finally:
        rows.close()
        close()


# --- Обработка заголовков и данных ---


def clean_header(text):
    """Нормализует заголовок колонки для сопоставления: убирает спецсимволы, приводит к нижнему регистру."""
    if not text:
        return ""

    text = str(text)
    # Оставляем только буквы, цифры, пробелы и базовые символы
    text = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9\s/*()«»'_-]", "", text)
    text = re.sub(r"\s+", "", text).strip()
    return text.casefold()


def _find_columns(rows, column_map):
    """Находит позиции нужных колонок в файле по заголовкам.

    Возвращает словарь {индекс_колонки: поле_БД}.
    Если не все нужные колонки найдены — выбрасывает CommandError.
    """
    lookup = {clean_header(name): field for name, field in column_map.items()}
    known = set(lookup)

    # Ищем первую строку, содержащую хотя бы один известный заголовок
    header = next((r for r in rows if known & {clean_header(c) for c in r if c}), None)
    if header is None:
        raise CommandError(BAD_FORMAT)

    # Сопоставляем индексы колонок с полями БД
    positions = {
        i: lookup[clean_header(cell)]
        for i, cell in enumerate(header)
        if cell and clean_header(cell) in lookup
    }

    # Проверяем, что все нужные поля найдены
    if set(column_map.values()) - set(positions.values()):
        raise CommandError(BAD_FORMAT)

    return positions


def _read_row(row, positions, fields, empty_as_null=False):
    """Извлекает значения из строки по позициям колонок."""
    record = dict.fromkeys(fields)

    for idx, field in positions.items():
        if idx < len(row) and row[idx] is not None:
            value = str(row[idx]).strip()
            record[field] = None if empty_as_null and value == "" else value

    return record


def _is_blank(record, field):
    """Проверяет, пусто ли значение поля (None или пустая строка)."""
    value = record.get(field)
    return value is None or str(value).strip() == ""


def _replace_table(table, fields, data):
    """Очищает таблицу и вставляет новые данные в одной транзакции."""
    insert_sql = (
        f"INSERT INTO {table} ({', '.join(fields)}) "
        f"VALUES ({', '.join(['%s'] * len(fields))})"
    )

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"TRUNCATE {table} RESTART IDENTITY")
        if data:
            cur.executemany(insert_sql, data)


# --- Функции импорта ---


def import_contracts(filepath):
    """Импортирует файл договоров в staging_excel. Возвращает количество строк."""
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
    """Импортирует файл заявок ФЗД в staging_znp_excel. Вычисляет crc32_hash для привязки."""
    fields = list(ZNP_COLUMNS.values()) + ["crc32_hash"]

    with _sheet(filepath) as rows:
        positions = _find_columns(rows, ZNP_COLUMNS)
        data = []

        for row in rows:
            if not any(row):
                continue

            record = _read_row(row, positions, fields)

            # Пропускаем строки без номера планового документа
            if _is_blank(record, "plan_doc"):
                continue

            # Вычисляем хеш для привязки к договору
            record["crc32_hash"] = contract_hash(
                record["igk"],
                record["c_agent"],
                record["contract"],
                record["stage"],
            )

            data.append(tuple(record[f] for f in fields))

    _replace_table("staging_znp_excel", fields, data)
    return len(data)


def import_znp_sap(filepath):
    """Импортирует файл заявок SAP в staging_znp_sap_excel. Колонки берутся по индексам."""
    fields = list(ZNP_SAP_COLUMNS.keys())
    positions = {idx: field for field, idx in ZNP_SAP_COLUMNS.items()}

    with _sheet(filepath) as rows:
        next(rows, None)  # Пропускаем строку заголовка
        data = []

        for row in rows:
            if not any(row):
                continue

            record = _read_row(row, positions, fields, empty_as_null=True)

            # Пропускаем строки без контрагента
            if _is_blank(record, "c_agent"):
                continue

            data.append(tuple(record[f] for f in fields))

    _replace_table("staging_znp_sap_excel", fields, data)
    return len(data)
