"""
Загрузка Excel-файлов в staging-таблицы.
Поддерживает .xlsx (openpyxl), .xls (xlrd) и .csv.
Каждый тип файла имеет свой словарь колонок.
"""

import csv
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
    """
    Генератор строк из .xlsx файла (openpyxl).
    ИСПРАВЛЕНО: Расплетает merged cells в первых 15 строках, чтобы заголовок не слипался.
    """
    # Загружаем БЕЗ read_only=True, чтобы получить доступ к merged_cells
    wb = openpyxl.load_workbook(filepath, data_only=True)
    sheet = wb.active

    # Расплетаем merged cells в первых 15 строках
    # Это решает проблему "слипаются шапки" при выгрузке из SAP
    for merged_range in list(sheet.merged_cells.ranges):
        if merged_range.min_row <= 15:
            # Получаем значение из верхней левой ячейки
            top_left_value = sheet.cell(
                row=merged_range.min_row, column=merged_range.min_col
            ).value
            # Заполняем все ячейки в объединенном диапазоне этим значением
            for row in range(merged_range.min_row, min(merged_range.max_row + 1, 16)):
                for col in range(merged_range.min_col, merged_range.max_col + 1):
                    sheet.cell(row=row, column=col).value = top_left_value
            # Разъединяем ячейки
            sheet.unmerge_cells(str(merged_range))

    # Итерируем по строкам
    rows = sheet.iter_rows(values_only=True)

    def close():
        wb.close()

    return rows, close


def _xls_rows(filepath):
    """Генератор строк из .xls файла (xlrd)."""
    book = xlrd.open_workbook(filepath)
    sheet = book.sheet_by_index(0)

    def _iter():
        for i in range(sheet.nrows):
            yield tuple(v if v != "" else None for v in sheet.row_values(i))

    return _iter(), book.release_resources


def _csv_rows(filepath):
    """
    Генератор строк из CSV файла.
    Автоопределяет разделитель и кодировку.
    """
    # Пробуем разные кодировки
    for encoding in ["utf-8-sig", "cp1251", "utf-8", "latin-1"]:
        try:
            with open(filepath, "r", encoding=encoding) as f:
                # Определяем разделитель
                sample = f.read(8192)
                f.seek(0)

                # Пробуем разные разделители
                try:
                    # Создаем sniffer для определения формата
                    dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
                    reader = csv.reader(f, dialect)

                    def _iter():
                        for row in reader:
                            # Пропускаем полностью пустые строки
                            if any(cell.strip() for cell in row):
                                yield tuple(row)

                    return _iter(), lambda: None  # CSV не требует явного закрытия
                except csv.Error:
                    continue
        except UnicodeDecodeError:
            continue

    raise CommandError(f"Не удалось определить кодировку CSV файла: {filepath}")


@contextmanager
def _sheet(filepath):
    """
    Контекстный менеджер для чтения листа Excel или CSV.
    Автоматически закрывает ресурсы после чтения.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext in (".csv", ".txt"):
        loader = _csv_rows
    elif ext == ".xls":
        loader = _xls_rows
    else:  # .xlsx
        loader = _xlsx_rows

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

    # Минимальное количество совпадений для признания строки заголовком
    # (не менее 70% от ожидаемых полей, но не менее 3)
    min_matches = max(3, int(len(expected_fields) * 0.7))

    # Пропускаем пустые строки, ищем заголовок
    header_row = None
    for row in rows:
        # Пропускаем полностью пустые строки
        if not any(cell for cell in row if cell):
            continue
        # Очищаем все ячейки строки, отбрасываем пустые
        cleaned_cells = {clean_header(cell) for cell in row if cell}
        # Проверяем, что найденная строка содержит достаточно ожидаемых заголовков
        match_count = len(cleaned_cells & known_headers)
        if match_count >= min_matches:
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
    missing_fields = expected_fields - set(positions.values())
    if missing_fields:
        missing_names = [
            name for name, field in column_map.items() if field in missing_fields
        ]
        raise CommandError(
            f"{BAD_FORMAT}. Отсутствуют колонки: {', '.join(missing_names)}"
        )

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
