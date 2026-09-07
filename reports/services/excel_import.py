"""
Загрузка Excel-файлов в staging-таблицы.
Поддерживает .xlsx (openpyxl) и .xls (xlrd).
Каждый тип файла имеет свой словарь колонок.
"""

import os
import re
from contextlib import contextmanager

import openpyxl
import xlrd
from django.core.management.base import CommandError
from django.db import connection, transaction

from .linking import contract_hash

# Словари соответствия заголовков в файле -> поля staging-таблиц
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

ZNP_SAP_COLUMNS = {
    "ИГК (по договору)": "igk",
    "Отдел-исполнитель": "cfo",
    "Наименование кредитора": "c_agent",
    "Регистрационный номер": "reg_num",
    "Текст": "items",
    "Сумма": "vv_sum",
    "Наименование Банка": "bank_name",
    "ЗнП 421 отдел (ГОЗ) - (E)": "stage_e",
    "ЗнП 18 отдел (ГОЗ) - (F)": "stage_f",
    "Платеж возможен - ( )": "payment_possible",
    "Иниц-но для платежа - (B)": "init_payment_date",
    "СП/ГП": "c_type",
    "ДокумВыравнивания": "normalize_doc_num",
}

BAD_FORMAT = "Документ не соответствует формату"


def _xlsx_rows(filepath):
    """Генератор строк из .xlsx файла (openpyxl)."""
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    rows = wb.active.iter_rows(values_only=True)
    return rows, wb.close


def _xls_rows(filepath):
    """Генератор строк из .xls файла (xlrd)."""
    book = xlrd.open_workbook(filepath)
    sheet = book.sheet_by_index(0)

    def _iter():
        for i in range(sheet.nrows):
            yield tuple(v if v != "" else None for v in sheet.row_values(i))

    return _iter(), book.release_resources


@contextmanager
def _sheet(filepath):
    """
    Контекстный менеджер для чтения листа Excel.
    Автоматически закрывает ресурсы после чтения.
    """
    ext = os.path.splitext(filepath)[1].lower()
    loader = _xls_rows if ext == ".xls" else _xlsx_rows
    try:
        rows, close = loader(filepath)
    except FileNotFoundError:
        raise CommandError(f"файл не найден: {filepath}")
    except Exception as exc:
        raise CommandError(str(exc))
    try:
        yield rows
    finally:
        # Закрываем итератор (если он имеет метод close)
        if hasattr(rows, "close"):
            rows.close()
        close()


def clean_header(text):
    """
    Приводит заголовок к каноническому виду для сравнения:
    - убирает непечатаемые символы
    - заменяет неразрывные пробелы на обычные
    - удаляет все пробелы
    - приводит к нижнему регистру
    """
    if not text:
        return ""
    text = str(text)
    # Замена неразрывных пробелов и прочих управляющих символов
    text = text.replace("\u00a0", " ")  # неразрывный пробел
    # Удаляем все управляющие символы (коды < 32)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    # Оставляем только буквы, цифры, скобки, кавычки, дефис, подчёркивание, точку
    text = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9\s/()"«»\'\-_\.]', "", text)
    # Удаляем все пробелы (пробелы, табуляции, переносы)
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def _find_columns(rows, column_map):
    """
    Находит строку-заголовок, определяет позиции колонок.
    Возвращает словарь {позиция: имя_поля}.
    Если нужные колонки не найдены, бросает CommandError(BAD_FORMAT).
    """
    # Сопоставляем очищенный заголовок -> поле
    lookup = {clean_header(name): field for name, field in column_map.items()}
    known_headers = set(lookup.keys())
    expected_fields = set(column_map.values())

    # Пропускаем пустые строки, ищем заголовок
    header_row = None
    for row in rows:
        # Пропускаем полностью пустые строки
        if not any(cell for cell in row if cell):
            continue
        # Очищаем все ячейки строки, отбрасываем пустые
        cleaned_cells = {clean_header(cell) for cell in row if cell}
        # Проверяем, что найденная строка содержит БОЛЬШИНСТВО ожидаемых заголовков
        # (например, не менее 80% от expected_fields)
        match_count = len(cleaned_cells & known_headers)
        if match_count >= len(expected_fields) * 0.8:
            header_row = row
            break

    if header_row is None:
        raise CommandError(BAD_FORMAT)

    # Определяем позиции колонок, которые есть в заголовке
    positions = {}
    for i, cell in enumerate(header_row):
        if cell:
            cleaned = clean_header(cell)
            if cleaned in lookup:
                positions[i] = lookup[cleaned]

    # Проверяем, что все ожидаемые поля найдены
    if set(positions.values()) != expected_fields:
        raise CommandError(BAD_FORMAT)

    return positions


def _read_row(row, positions, fields, empty_as_null=False):
    """
    Извлекает значения из строки по позициям колонок.
    Возвращает словарь {поле: значение}.
    """
    record = dict.fromkeys(fields)
    for i, field in positions.items():
        if i < len(row) and row[i] is not None:
            value = str(row[i]).strip()
            record[field] = None if empty_as_null and value == "" else value
    return record


def _is_blank(record, field):
    """Проверяет, что поле в записи пустое."""
    value = record.get(field)
    return value is None or str(value).strip() == ""


def _replace_table(table, fields, data):
    """
    Очищает staging-таблицу и вставляет новые данные.
    Использует транзакцию.
    """
    insert_sql = (
        f"INSERT INTO {table} ({', '.join(fields)}) "
        f"VALUES ({', '.join(['%s'] * len(fields))})"
    )
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"TRUNCATE {table} RESTART IDENTITY")
        if data:
            cur.executemany(insert_sql, data)


def import_contracts(filepath):
    """
    Загружает файл договоров в staging_excel.
    Возвращает количество импортированных строк.
    """
    fields = list(CONTRACT_COLUMNS.values())
    with _sheet(filepath) as rows:
        positions = _find_columns(rows, CONTRACT_COLUMNS)
        data = []
        for row in rows:
            if not any(row):
                continue
            record = _read_row(row, positions, fields)
            data.append(tuple(record[f] for f in fields))
    _replace_table("staging_excel", fields, data)
    return len(data)


def import_znp(filepath):
    """
    Загружает файл заявок ФЗД в staging_znp_excel.
    Дополнительно вычисляет crc32_hash для привязки к договорам.
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
            # Вычисляем хеш для привязки к позиции договора
            record["crc32_hash"] = contract_hash(
                record["igk"], record["c_agent"], record["contract"], record["stage"]
            )
            data.append(tuple(record[f] for f in fields))
    _replace_table("staging_znp_excel", fields, data)
    return len(data)


def import_znp_sap(filepath):
    """
    Загружает файл заявок SAP в staging_znp_sap_excel.
    """
    fields = list(ZNP_SAP_COLUMNS.values())
    with _sheet(filepath) as rows:
        positions = _find_columns(rows, ZNP_SAP_COLUMNS)
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
