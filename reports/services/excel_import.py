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
    text = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9\s/%*()«»\'\-\_]", "", text)
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

SUM_REPORT_FIELDS = [
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

# Названия полей Краткой справки намеренно привязаны к смыслу заголовка,
# а не к номеру колонки. В исходных файлах несколько заголовков отличаются
# незначительными деталями ("80%" / "90%", переносы строк и т.п.).
SUM_REPORT_COLUMN_ALIASES = {
    "dep": ("ЦФО",),
    "counteragent": ("Контрагент",),
    "inn": ("ИНН",),
    "contract": ("Договор",),
    "status": ("Состояние",),
    "stage": ("Этап графика",),
    "item": ("Предмет",),
    "order_doc": ("Заказ",),
    "contract_sum": ("СУММА договора", "Сумма договора"),
    "plan_avans": (
        "ПЛАН аванса по договору (по условию)",
        "ПЛАН аванса по договору",
    ),
    "percent_doc": ("%", "Процент"),
    "fact_paid": (
        "ФАКТ ОПЛАТЫ АВАНСА",
        "ФАКТ ОПЛАТЫ АВАНС",
        "ФАКТ ОПЛАТЫ АВАНСЫ",
    ),
    "note": ("Примечание",),
    "completed_sum": ("Сумма оформленных ЗНП",),
    "znp_count": ("Кол-во сданных ЗНП",),
    "sum_80": (
        "сумма 90% по договору",
        "сумма 80% по договору",
        "сумма 80/90% по договору",
        "сумма аванса по договору 80%",
    ),
    "paid_from_znp": ("Оплачено из сданных ЗНП",),
    "remains_pay": ("Осталось доплатить авансов",),
    "sum_avans": ("Сумма оформленных и не оформленных ЗнП",),
    "sum_issued_znp": ("Сумма оформленных/не оформленных ЗнП",),
    "period_reg_date": ("Срок оформления ЗнП на аванс",),
    "plan_date_contract": (
        "Планируемая дата заключения договора",
        "Дата заключения договора",
    ),
}

SUM_REPORT_CYCLE_ALIASES = (
    "Цикл",
    "Длинный цикл",
    "Длинноцикличный",
    "is_cycle",
    "cycle",
)

SUM_REPORT_REQUIRED_FIELDS = set(SUM_REPORT_COLUMN_ALIASES)


def _sum_to_decimal(val):
    """Конвертирует денежное значение в Decimal. Пустое/ошибка -> None."""
    if val is None or isinstance(val, bool):
        return None
    try:
        s = str(val).replace("\xa0", "").replace(" ", "").replace(",", ".")
        if s in ("", "-", "None"):
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _percent_to_decimal(val):
    """
    Конвертирует процент в долю от 1.
    80% -> 0.80, 80 -> 0.80, 0.8 -> 0.80, 1 -> 1.00.
    """
    if val is None or isinstance(val, bool):
        return None
    try:
        s = str(val).replace("%", "").replace("\xa0", "").replace(" ", "")
        s = s.replace(",", ".")
        if s in ("", "-", "None"):
            return None
        result = Decimal(s)
        if abs(result) > Decimal("1"):
            result /= Decimal("100")
        return result
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
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _int_or_zero(val):
    """Конвертирует значение в int. Пустое/ошибка -> 0."""
    if val is None:
        return 0
    if isinstance(val, bool):
        return int(val)
    try:
        return int(float(str(val).replace(",", ".")))
    except (ValueError, TypeError):
        return 0


def _bool_value(val):
    """Приводит явный признак цикла к bool."""
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    if isinstance(val, (int, float, Decimal)):
        return bool(val)
    normalized = str(val).strip().casefold()
    return normalized in {
        "да",
        "д",
        "yes",
        "y",
        "true",
        "1",
        "цикл",
        "длинный цикл",
        "длинноцикл",
        "длинноцикличный",
    }


def _sum_report_header(ws):
    """
    Возвращает (строка шапки, mapping field -> zero-based column,
    zero-based cycle column or None).

    На текущем файле это строка 2. Поиск сделан динамическим, чтобы перенос
    строк/перестановка колонок не ломали импорт.
    """
    max_scan_row = min(ws.max_row, 40)
    alias_lookup = {}
    for field, aliases in SUM_REPORT_COLUMN_ALIASES.items():
        for alias in aliases:
            alias_lookup[clean_header(alias)] = field

    cycle_keys = {clean_header(v) for v in SUM_REPORT_CYCLE_ALIASES}

    for row_idx, row in enumerate(
        ws.iter_rows(min_row=1, max_row=max_scan_row, values_only=True), start=1
    ):
        field_positions = {}
        cycle_position = None

        for col_idx, value in enumerate(row):
            key = clean_header(value)
            if not key:
                continue
            if key in alias_lookup:
                field_positions.setdefault(alias_lookup[key], col_idx)
            if key in cycle_keys and cycle_position is None:
                cycle_position = col_idx

        if SUM_REPORT_REQUIRED_FIELDS.issubset(field_positions):
            return row_idx, field_positions, cycle_position

    return None, None, None


def _is_sum_report_summary_sheet(sheet_name):
    """Определяет служебные листы, такие как «СВОД (2)»."""
    normalized = clean_header(sheet_name)
    return normalized.startswith("свод") or normalized.startswith("итог")


def _is_sum_report_control_row(row):
    """Проверки переноса из Pascal для управляющих/итоговых строк."""
    first = str(row[0] or "").strip().casefold() if len(row) > 0 else ""
    second = str(row[1] or "").strip().casefold() if len(row) > 1 else ""

    first_two = (first, second)
    if any("общий итог" in value or "всего" in value for value in first_two):
        return "break"

    if any("итого: 42" in value or "в том числе" in value for value in first_two):
        return "skip"

    return "data"


def import_sum_report(filepath):
    """
    Импортирует файл Краткой справки в staging_sum_excel.

    Отличия от первоначального переноса Pascal:
    - служебный лист «СВОД» не загружается;
    - шапка и нужные колонки ищутся по названию;
    - колонка «Этап графика» никогда не интерпретируется как is_cycle;
    - признак длинного цикла читается только из явной колонки цикла, если она
      присутствует в исходном файле;
    - расчётные формулы читаются через data_only=True, т.е. берутся их
      сохранённые Excel-значения.
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)

    data = []
    try:
        for sheet_name in wb.sheetnames:
            if not str(sheet_name).strip():
                continue
            if _is_sum_report_summary_sheet(sheet_name):
                continue

            ws = wb[sheet_name]
            header_row, positions, cycle_position = _sum_report_header(ws)
            if header_row is None:
                raise CommandError(
                    f"{BAD_FORMAT}: лист «{sheet_name}» не содержит шапку Краткой справки"
                )

            sheet_title = str(ws.cell(row=1, column=2).value or sheet_name).strip()

            for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                if not row or not any(row):
                    continue

                control = _is_sum_report_control_row(row)
                if control == "break":
                    break
                if control == "skip":
                    continue

                def cell(field):
                    idx = positions[field]
                    return row[idx] if idx < len(row) else None

                record = {
                    "igk": str(sheet_name).strip(),
                    "is_cycle": _bool_value(
                        row[cycle_position] if cycle_position is not None and cycle_position < len(row) else None
                    ),
                    "dep": str(cell("dep") or "").strip(),
                    "counteragent": str(cell("counteragent") or "").strip(),
                    "inn": str(cell("inn") or "").strip(),
                    "contract": str(cell("contract") or "").strip(),
                    "status": str(cell("status") or "").strip(),
                    "stage": str(cell("stage") or "").strip(),
                    "item": str(cell("item") or "").strip(),
                    "order_doc": str(cell("order_doc") or "").strip(),
                    "contract_sum": _sum_to_decimal(cell("contract_sum")),
                    "plan_avans": _sum_to_decimal(cell("plan_avans")),
                    "percent_doc": _percent_to_decimal(cell("percent_doc")),
                    "fact_paid": _sum_to_decimal(cell("fact_paid")),
                    "note": str(cell("note") or "").replace("\n", " ").strip(),
                    "completed_sum": _sum_to_decimal(cell("completed_sum")),
                    "znp_count": _int_or_zero(cell("znp_count")),
                    "sum_80": _sum_to_decimal(cell("sum_80")),
                    "paid_from_znp": _sum_to_decimal(cell("paid_from_znp")),
                    "remains_pay": _sum_to_decimal(cell("remains_pay")),
                    "sum_avans": _sum_to_decimal(cell("sum_avans")),
                    "sum_issued_znp": _sum_to_decimal(cell("sum_issued_znp")),
                    "period_reg_date": _date_to_date(cell("period_reg_date")),
                    "plan_date_contract": _date_to_date(cell("plan_date_contract")),
                }
                data.append(tuple(record[f] for f in SUM_REPORT_FIELDS))
    finally:
        wb.close()

    _replace_table("staging_sum_excel", SUM_REPORT_FIELDS, data)
    return len(data)
