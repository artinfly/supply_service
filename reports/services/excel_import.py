"""
Модуль импорта данных из Excel-файлов в staging-таблицы базы данных.

Отвечает за:
- Чтение файлов форматов .xlsx и .xls
- Поиск заголовков колонок и маппинг на поля БД
- Валидацию структуры документа
- Загрузку сырых данных во временные staging-таблицы

Логика работы:
1. Файл открывается через openpyxl (xlsx) или xlrd (xls)
2. Для договоров и ЗНП ФЗД заголовки ищутся по именам колонок (гибкий поиск)
3. Для ЗНП SAP используются фиксированные индексы колонок (формат стабилен)
4. Данные загружаются в staging-таблицы без конвертации типов
5. Конвертация и нормализация происходит в services/normalize.py
"""

import os
import re
from contextlib import contextmanager

import openpyxl
import xlrd
from django.core.management.base import CommandError
from django.db import connection, transaction

from .linking import contract_hash

# ============================================================================
# Маппинги колонок Excel на поля staging-таблиц
# ============================================================================

# Маппинг для файла договоров: имя колонки в Excel -> имя поля в staging_excel
# Поиск колонок осуществляется по именам заголовков (гибкий порядок)
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

# Маппинг для файла заявок ФЗД: имя колонки в Excel -> имя поля в staging_znp_excel
# Поиск колонок осуществляется по именам заголовков (гибкий порядок)
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

# Маппинг для файла заявок SAP: имя поля в staging_znp_sap_excel -> индекс колонки в Excel
# ВАЖНО: используются фиксированные индексы колонок, а не имена заголовков.
# Это сделано намеренно: формат файла SAP стабилен, а поиск по именам ломается
# из-за невидимых символов в заголовках. При изменении структуры файла SAP
# индексы нужно обновлять вручную.
ZNP_SAP_COLUMNS = {
    "igk": 20,
    "cfo": 23,
    "c_agent": 15,
    "reg_num": 19,
    "items": 12,
    "vv_sum": 13,
    "bank_name": 25,
    "stage_e": 30,
    "stage_f": 31,
    "payment_possible": 32,
    "init_payment_date": 27,
    "c_type": 9,
    "normalize_doc_num": 11,
}

# Сообщение об ошибке при несоответствии структуры файла ожидаемому формату
BAD_FORMAT = "Документ не соответствует формату"


# ============================================================================
# Функции чтения Excel-файлов
# ============================================================================


def _xlsx_rows(filepath):
    """
    Открывает .xlsx файл и возвращает итератор по строкам активного листа.

    Используется режим read_only=True для оптимизации памяти на больших файлах.
    data_only=True возвращает вычисленные значения формул, а не сами формулы.

    Возвращает кортеж: (итератор строк, функция закрытия книги)
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    return wb.active.iter_rows(values_only=True), wb.close


def _xls_rows(filepath):
    """
    Открывает .xls файл (старый формат Excel) и возвращает итератор по строкам.

    Пустые строки заменяются на None для единообразия с openpyxl.

    Возвращает кортеж: (итератор строк, функция освобождения ресурсов)
    """
    book = xlrd.open_workbook(filepath)
    sheet = book.sheet_by_index(0)

    def _iter():
        for i in range(sheet.nrows):
            yield tuple(v if v != "" else None for v in sheet.row_values(i))

    return _iter(), book.release_resources


@contextmanager
def _sheet(filepath):
    """
    Контекстный менеджер для безопасного открытия Excel-файла.

    Автоматически выбирает нужный парсер (openpyxl или xlrd) по расширению файла.
    Гарантирует закрытие файла и освобождение ресурсов после использования.

    При ошибках чтения файла выбрасывает CommandError с понятным сообщением.
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
        rows.close()
        close()


# ============================================================================
# Функции обработки заголовков и чтения строк
# ============================================================================


def clean_header(text):
    """
    Нормализует текст заголовка колонки для гибкого поиска.

    Удаляет все символы кроме букв, цифр и базовых разделителей.
    Убирает пробелы и приводит к нижнему регистру.

    Это позволяет находить колонки даже если в заголовках есть опечатки,
    лишние пробелы или специальные символы.
    """
    if not text:
        return ""
    text = str(text)
    text = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9\s/()«»\'\-\_]", "", text)
    text = re.sub(r"\s+", "", text).strip()
    return text.casefold()


def _find_columns(rows, column_map):
    """
    Ищет строку заголовков в файле и определяет позиции нужных колонок.

    Сканирует строки файла до тех пор, пока не найдёт строку, содержащую
    хотя бы одно ожидаемое имя колонки. Затем для каждой найденной колонки
    определяет её позицию (индекс) в строке.

    Если не все ожидаемые колонки найдены — выбрасывает CommandError.

    Возвращает словарь: {индекс колонки: имя поля в БД}
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
    """
    Читает одну строку Excel и преобразует её в словарь значений полей.

    Использует маппинг positions для извлечения значений из нужных колонок.
    Пустые строки могут быть преобразованы в None (если empty_as_null=True).

    Возвращает словарь: {имя поля: значение}
    """
    record = dict.fromkeys(fields)
    for i, field in positions.items():
        if i < len(row) and row[i] is not None:
            value = str(row[i]).strip()
            record[field] = None if empty_as_null and value == "" else value
    return record


def _read_row_sap(row, column_map, empty_as_null=False):
    """
    Читает одну строку Excel для SAP-файла, используя фиксированные индексы колонок.

    В отличие от _read_row, работает не по именам заголовков, а по номерам колонок.
    Это необходимо для файлов SAP, где формат стабилен, но заголовки содержат
    невидимые символы, ломающие поиск по именам.

    Возвращает словарь: {имя поля: значение}
    """
    record = {}
    for field, col_idx in column_map.items():
        if col_idx < len(row) and row[col_idx] is not None:
            value = str(row[col_idx]).strip()
            record[field] = None if empty_as_null and value == "" else value
        else:
            record[field] = None
    return record


def _is_blank(record, field):
    """
    Проверяет, является ли значение поля пустым или отсутствующим.

    Используется для фильтрации некорректных строк при импорте.
    """
    value = record.get(field)
    return value is None or str(value).strip() == ""


# ============================================================================
# Функции загрузки данных в staging-таблицы
# ============================================================================


def _replace_table(table, fields, data):
    """
    Полностью заменяет содержимое staging-таблицы новыми данными.

    Выполняется в одной транзакции: сначала TRUNCATE, затем массовый INSERT.
    При ошибке на любом шаге транзакция откатывается — таблица остаётся нетронутой.

    Параметры:
    - table: имя staging-таблицы
    - fields: список имён полей для вставки
    - data: список кортежей со значениями (каждый кортеж — одна строка)
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
    Импортирует файл договоров в staging-таблицу staging_excel.

    Читает файл, находит заголовки колонок по именам, извлекает данные
    и загружает их в БД без конвертации типов (всё остаётся в виде строк).

    Возвращает количество загруженных строк.
    """
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
    Импортирует файл заявок ФЗД в staging-таблицу staging_znp_excel.

    Аналогично import_contracts, но дополнительно вычисляет crc32_hash
    для каждой заявки (на основе ИГК + контрагент + договор + этап).
    Этот хеш используется для привязки заявок к позициям договоров.

    Пропускает строки без планового документа (plan_doc).

    Возвращает количество загруженных строк.
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
    Импортирует файл заявок SAP в staging-таблицу staging_znp_sap_excel.

    Использует фиксированные индексы колонок (ZNP_SAP_COLUMNS), а не поиск по именам.
    Пропускает первую строку (предполагается, что это заголовок).
    Пропускает строки без контрагента (c_agent).

    Возвращает количество загруженных строк.
    """
    fields = list(ZNP_SAP_COLUMNS.keys())
    with _sheet(filepath) as rows:
        next(rows, None)  # Пропускаем строку заголовка
        data = []
        for row in rows:
            if not any(row):
                continue
            record = _read_row_sap(row, ZNP_SAP_COLUMNS, empty_as_null=True)
            if _is_blank(record, "c_agent"):
                continue
            data.append(tuple(record[f] for f in fields))
    _replace_table("staging_znp_sap_excel", fields, data)
    return len(data)
