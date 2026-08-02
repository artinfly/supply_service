# Чтение файлов Excel в таблицы staging_*.
# Здесь же перечислены колонки каждого файла: нет хотя бы одной — загрузка
# отменяется и база остаётся прежней.
import openpyxl
from django.core.management.base import CommandError
from django.db import connection, transaction

from .linking import contract_hash

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
}

ZNP_SAP_COLUMNS = {
    "ИГК (по договору)": "igk",
    "Отдел-исполнитель": "cfo",
    "Наименование кредитора": "c_agent",
    "Регистрационный номер": "reg_num",
    "Текст": "items",
    "Сумма во ВВ": "vv_sum",
    "Наименование Банка": "bank_name",
    "ЗнП 421 отдел (ГОЗ) - (E)": "stage_e",
    "ЗнП 18 отдел (ГОЗ) - (F)": "stage_f",
    "Платеж возможен - ( )": "payment_possible",
    "СП/ГП": "c_type",
    "ДокумВыравнивания": "normalize_doc_num",
}

BAD_FORMAT = "Документ не соответствует формату"


def _open_sheet(filepath):
    try:
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    except FileNotFoundError:
        raise CommandError(f"файл не найден: {filepath}")
    except Exception as exc:
        raise CommandError(str(exc))
    return wb, wb.active.iter_rows(values_only=True)


def _find_columns(rows, column_map):
    lookup = {name.strip().casefold(): field for name, field in column_map.items()}
    known = set(lookup)
    header = next(
        (r for r in rows if known & {str(c).strip().casefold() for c in r if c}), None
    )
    if header is None:
        raise CommandError(BAD_FORMAT)
    positions = {
        i: lookup[str(cell).strip().casefold()]
        for i, cell in enumerate(header)
        if cell and str(cell).strip().casefold() in lookup
    }
    if set(column_map.values()) - set(positions.values()):
        raise CommandError(BAD_FORMAT)
    return positions


def _read_row(row, positions, fields, empty_as_null=False):
    record = dict.fromkeys(fields)
    for i, field in positions.items():
        if i < len(row) and row[i] is not None:
            value = str(row[i]).strip()
            record[field] = None if empty_as_null and value == "" else value
    return record


def _replace_table(table, fields, data):
    insert_sql = (
        f"INSERT INTO {table} ({', '.join(fields)}) "
        f"VALUES ({', '.join(['%s'] * len(fields))})"
    )
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"TRUNCATE {table} RESTART IDENTITY")
        if data:
            cur.executemany(insert_sql, data)


def import_contracts(filepath):
    fields = list(CONTRACT_COLUMNS.values())
    wb, rows = _open_sheet(filepath)
    try:
        positions = _find_columns(rows, CONTRACT_COLUMNS)
        data = [
            tuple(_read_row(row, positions, fields)[f] for f in fields)
            for row in rows
            if any(row)
        ]
    finally:
        wb.close()
    _replace_table("staging_excel", fields, data)
    return len(data)


def import_znp(filepath):
    fields = list(ZNP_COLUMNS.values()) + ["crc32_hash"]
    wb, rows = _open_sheet(filepath)
    try:
        positions = _find_columns(rows, ZNP_COLUMNS)
        data = []
        for row in rows:
            if not any(row):
                continue
            record = _read_row(row, positions, fields)
            record["crc32_hash"] = contract_hash(
                record["igk"], record["c_agent"], record["contract"], record["stage"]
            )
            data.append(tuple(record[f] for f in fields))
    finally:
        wb.close()
    _replace_table("staging_znp_excel", fields, data)
    return len(data)


def import_znp_sap(filepath):
    fields = list(ZNP_SAP_COLUMNS.values())
    items_column = 4
    wb, rows = _open_sheet(filepath)
    try:
        positions = _find_columns(rows, ZNP_SAP_COLUMNS)
        data = []
        for row in rows:
            if not any(row):
                continue
            if len(row) > items_column and row[items_column] == "":
                continue
            record = _read_row(row, positions, fields, empty_as_null=True)
            data.append(tuple(record[f] for f in fields))
    finally:
        wb.close()
    _replace_table("staging_znp_sap_excel", fields, data)
    return len(data)
